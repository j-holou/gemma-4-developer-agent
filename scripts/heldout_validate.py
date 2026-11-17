"""Keep only mined tasks whose new/changed tests fail before the gold patch and pass after.

    python scripts/heldout_validate.py REPOS_DIR VENVS_DIR CANDIDATES.jsonl OUT.jsonl [--per-repo 8]

Each task gets its own git worktree at the base commit (the clone itself is never reset); the
repo's venv holds its dependencies and the worktree is put first on PYTHONPATH. Repos run in
parallel. For each task: apply test_patch, run the touched test files (junit); apply the gold
patch, run again. FAIL_TO_PASS = tests failing before and passing after. A task is kept if
FAIL_TO_PASS is non-empty and no touched test fails after the gold patch.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def junit(venv, repo, files):
    env = dict(os.environ, PYTHONPATH=f'{repo}/src:{repo}')
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
        xml = f.name
    try:
        run([f'{venv}/bin/python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=',
             f'--junitxml={xml}', *files], repo, timeout=300, env=env)
        res = {}
        for tc in ET.parse(xml).getroot().iter('testcase'):
            name = f"{tc.get('classname')}::{tc.get('name')}"
            res[name] = not any(c.tag in ('failure', 'error') for c in tc)
        return res
    except Exception:
        return None


def apply(repo, patch):
    return run(['git', 'apply', '--whitespace=nowarn', '-'], repo, input=patch).returncode == 0


def validate_repo(clone, venv, tasks, work):
    out = []
    for t in tasks:
        repo = work / t['instance_id']
        if repo.exists() or run(['git', 'worktree', 'add', '-q', '--detach', str(repo), t['base_commit']],
                                clone).returncode:
            continue
        files = sorted({l[6:] for l in t['test_patch'].splitlines() if l.startswith('+++ b/') and l.endswith('.py')
                        and '/conftest' not in l and not l.endswith('__init__.py')})
        if not files or not apply(repo, t['test_patch']):
            continue
        before = junit(venv, repo, [f for f in files if (repo / f).exists()])
        if not apply(repo, t['patch']):
            continue
        after = junit(venv, repo, files)
        if before is None or after is None or not after:
            continue
        f2p = sorted(n for n, ok in after.items() if ok and not before.get(n, False))
        broken = sorted(n for n, ok in after.items() if not ok)
        if f2p and not broken:
            out.append(dict(t, FAIL_TO_PASS=f2p, n_tests=len(after)))
            print('KEEP', t['instance_id'], len(f2p), flush=True)
    return out


def main():
    repos, venvs, cand, out = (Path(a).resolve() for a in sys.argv[1:5])
    per = int(sys.argv[sys.argv.index('--per-repo') + 1]) if '--per-repo' in sys.argv else 8
    rows = [json.loads(l) for l in cand.read_text().splitlines()]
    random.seed(0)
    by = {}
    for r in rows:
        by.setdefault(r['repo'], []).append(r)
    work = out.parent / 'worktrees'
    work.mkdir(exist_ok=True)
    jobs = []
    for slug, ts in by.items():
        name = slug.split('/')[1]
        if not (venvs / name).exists():
            continue
        random.shuffle(ts)
        jobs.append((repos / name, venvs / name, ts[:per * 3], work))
    with ThreadPoolExecutor(len(jobs)) as ex:
        kept = [k for res in ex.map(lambda j: validate_repo(*j), jobs) for k in res]
    final = []
    for slug in by:
        final += [k for k in kept if k['repo'] == slug][:per]
    out.write_text(''.join(json.dumps(r) + '\n' for r in final))
    print('kept', len(kept), 'final', len(final))


if __name__ == '__main__':
    main()
