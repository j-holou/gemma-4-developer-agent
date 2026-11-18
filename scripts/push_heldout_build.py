"""Build the held-out dev set (tasks from repositories other than the competition's) in a Kaggle CPU kernel.

    python scripts/push_heldout_build.py [--per-repo 5]
    kaggle kernels logs <user>/gemma-heldout-build | grep -E '^(KEEP|SUMMARY|REPO)'

Running other projects' test suites happens on Kaggle, not in our own container. The kernel
(internet on, no GPU) clones the repositories, mines candidate fixes (heldout_mine.py), builds a
Python 3.13 venv per repository, keeps fixes whose tests fail before and pass after the gold
patch (heldout_validate.py), and writes /kaggle/working/heldout/ in the competition layout:
tasks.jsonl, snapshots/<id>.tar.gz (repo at base commit with a fresh .git), wheels/ (cp313
binary wheels of every dependency), repos.json (repo -> own package name). An eval kernel can
mount it as a kernel source.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from push_eval import ROOT, kaggle_username

REPOS = ['pallets/click', 'python-attrs/attrs', 'marshmallow-code/marshmallow', 'more-itertools/more-itertools',
         'andialbrecht/sqlparse', 'Python-Markdown/markdown', 'pytest-dev/pluggy', 'python-poetry/tomlkit',
         'arrow-py/arrow', 'pallets/werkzeug', 'pallets/flask', 'jazzband/prettytable',
         'python-humanize/humanize', 'tox-dev/filelock', 'pypa/packaging']

KERNEL = r'''
import json, os, subprocess, sys, tarfile, tomllib, shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPOS = __REPOS__
PER = __PER__
DEBUG = __DEBUG__
REPOS = REPOS[:3] if DEBUG else REPOS
W = Path("/kaggle/working/build"); OUT = Path("/kaggle/working/heldout")
for d in (W / "repos", W / "venvs", OUT / "snapshots", OUT / "wheels"):
    d.mkdir(parents=True, exist_ok=True)
(W / "heldout_mine.py").write_text(__MINE__)
(W / "heldout_validate.py").write_text(__VALIDATE__)

def sh(cmd, cwd=None, env=None):
    r = subprocess.run(cmd, cwd=cwd, env=env, shell=True, capture_output=True, text=True)
    return r

print(sh("pip install -q uv").stderr[-300:], flush=True)
UV = f"{sys.executable} -m uv"
_p = sh(f"{UV} python install 3.13"); print("UVPY", _p.returncode, _p.stdout[-200:], _p.stderr[-300:], flush=True)

def clone(slug):
    name = slug.split("/")[1]
    sh(f"git clone -q --shallow-since=2025-01-01 https://github.com/{slug}.git {W/'repos'/name}")
    return name
with ThreadPoolExecutor(8) as ex:
    names = list(ex.map(clone, REPOS))
print("cloned", names, flush=True)
print(sh(f"{sys.executable} {W/'heldout_mine.py'} {W/'repos'} {W/'candidates.jsonl'}").stdout, flush=True)

def venv(name):
    v, r = W / "venvs" / name, W / "repos" / name
    env = {k: x for k, x in os.environ.items() if not k.startswith(("UV_", "PIP_", "PYTHON"))} | {"VIRTUAL_ENV": str(v)}
    a = sh(f"{UV} venv -q -p 3.13 {v}")
    b = sh(f"{UV} pip install -q --python {v}/bin/python pytest -e .", r, env)
    print("VENV", name, a.returncode, b.returncode, (a.stderr[-300:] + b.stderr[-300:]).replace("\n", " | "), flush=True)
    for g in ("tests", "test", "testing", "dev"):
        sh(f"{UV} pip install -q --python {v}/bin/python --group {g}", r, env)
        sh(f"{UV} pip install -q --python {v}/bin/python -e '.[{g}]'", r, env)
    for f in ("requirements/tests.txt", "requirements/test.txt", "requirements-test.txt", "test-requirements.txt"):
        if (r / f).exists():
            sh(f"{UV} pip install -q --python {v}/bin/python -r {f}", r, env)
    c = sh(f"{v}/bin/python -c 'import pytest; print(pytest.__version__)'")
    print("VENVCHECK", name, c.returncode, c.stdout.strip(), c.stderr[-200:].replace("\n", " | "), flush=True)
    return name
with ThreadPoolExecutor(4) as ex:
    list(ex.map(venv, names))
print("venvs done", flush=True)

r = sh(f"HELDOUT_DEBUG={DEBUG} {sys.executable} {W/'heldout_validate.py'} {W/'repos'} {W/'venvs'} {W/'candidates.jsonl'} {OUT/'tasks.jsonl'} --per-repo {PER}")
print(r.stdout[-20000:], r.stderr[-3000:], flush=True)
shutil.rmtree(OUT / "worktrees", ignore_errors=True)
tasks = [json.loads(l) for l in (OUT / "tasks.jsonl").read_text().splitlines()] if (OUT / "tasks.jsonl").exists() else []

own = {}
for name in names:
    try:
        own[name] = tomllib.loads((W / "repos" / name / "pyproject.toml").read_text())["project"]["name"]
    except Exception:
        own[name] = name
for t in tasks:
    name = t["repo"].split("/")[1]
    src = W / "snap" / t["instance_id"]
    src.mkdir(parents=True)
    a = subprocess.run(["git", "-C", str(W / "repos" / name), "archive", t["base_commit"]], capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(src)], input=a.stdout)
    sh("git init -q && git add -A && git -c user.email=a@b -c user.name=a commit -qm base", src)
    with tarfile.open(OUT / "snapshots" / f"{t['instance_id']}.tar.gz", "w:gz") as tf:
        for p in sorted(src.iterdir()):
            tf.add(p, arcname=p.name)
(OUT / "repos.json").write_text(json.dumps({s: own[s.split("/")[1]] for s in REPOS}, indent=1))

reqs = set()
for name in names:
    fr = sh(f"{UV} pip freeze --python {W/'venvs'/name}/bin/python", W / "repos" / name, dict(os.environ, VIRTUAL_ENV=str(W / "venvs" / name))).stdout
    for l in fr.splitlines():
        if l and not l.startswith(("-e", "#")) and " @ " not in l and l.split("==")[0].lower() not in {v.lower() for v in own.values()}:
            reqs.add(l.strip())
(W / "reqs.txt").write_text("\n".join(sorted(reqs)) + "\n")
for l in sorted(reqs):
    d = sh(f"{sys.executable} -m pip download -q --no-deps --only-binary :all: --python-version 3.13 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform any -d {OUT/'wheels'} '{l}'")
    if d.returncode:
        sh(f"{sys.executable} -m pip wheel -q --no-deps -w {OUT/'wheels'} '{l}'")
shutil.rmtree(W, ignore_errors=True)
print("SUMMARY", json.dumps({"tasks": len(tasks), "by_repo": {s: sum(t["repo"] == s for t in tasks) for s in REPOS},
                             "wheels": len(list((OUT / "wheels").glob("*.whl"))), "own": own}), flush=True)
for t in tasks:
    print("TASK", json.dumps({k: t[k] for k in ("instance_id", "repo", "gold_lines", "gold_files", "FAIL_TO_PASS")})[:600])
'''


def main() -> None:
    per = int(sys.argv[sys.argv.index('--per-repo') + 1]) if '--per-repo' in sys.argv else 5
    debug = int('--debug' in sys.argv)
    src = (KERNEL.replace('__REPOS__', repr(REPOS)).replace('__PER__', str(per)).replace('__DEBUG__', str(debug))
           .replace('__MINE__', repr((ROOT / 'scripts/heldout_mine.py').read_text()))
           .replace('__VALIDATE__', repr((ROOT / 'scripts/heldout_validate.py').read_text())))
    compile(src, 'build.py', 'exec')
    user = kaggle_username()
    meta = {
        'id': f'{user}/gemma-heldout-build', 'title': 'gemma-heldout-build', 'code_file': 'build.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_internet': True,
        'competition_sources': [], 'dataset_sources': [], 'kernel_sources': [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'build.py').write_text(src)
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
