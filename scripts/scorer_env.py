# ==== scorer_env.py (inlined by push_eval.py / push_regrade.py at the __SCORER_ENV__ marker) ====
# A scorer-like sandbox for swegemma's subprocess mode. The notebook sandbox sees Kaggle's
# own packages, installs nothing from wheels/ and lacks test-only packages, so many correct
# patches fail. This rebuilds the published harness environment (Python 3.13, clean venv,
# newest competition wheel of every package, pytest 8.4.2, the imp/telnetlib shims) and
# hooks it into both the agent and the verification sandbox. Setup and per-task
# calibration follow zbigniewkirchner's public notebook "Gemma 4 Agent: do gold patches
# pass locally" and use its datasets gemma-4-agent-local-eval-wheels / -pythons.
# Needs: swegemma installed, and CURRENT['id'] set to the task being run.
import re  # noqa: E402
import shutil  # noqa: E402
import tarfile  # noqa: E402
import tomllib  # noqa: E402
import zipfile  # noqa: E402
from packaging.requirements import Requirement  # noqa: E402
from packaging.version import Version  # noqa: E402
import swegemma.harness.agent_runner as agent_runner  # noqa: E402
import swegemma.harness.verification as verification  # noqa: E402

COMP = Path(next(h for pat in ('/kaggle/input/competitions/gemma-4-developer-agent/tasks.jsonl',
                                 '/kaggle/input/gemma-4-developer-agent/tasks.jsonl', '/kaggle/input/**/tasks.jsonl')
                 for h in glob.glob(pat, recursive=True))).parent
EXTRA = Path(glob.glob('/kaggle/input/**/inline_snapshot-*.whl', recursive=True)[0]).parent
PYDS = Path(glob.glob('/kaggle/input/**/cpython-3.13-linux.tgz.bin', recursive=True)[0]).parent


def fits(w, tag='cp313'):  # noqa: F811
    py, abi, plat = w.name[:-4].split('-')[-3:]
    if plat != 'any' and 'linux' not in plat:
        return False
    if abi == 'abi3':
        return int(py.split('.')[0][2:]) <= int(tag[2:])
    return any(t.startswith('py3') for t in py.split('.')) or tag in py.split('.')




# ---------------------------------------------------------------- scorer image per repo
norm = lambda n: re.sub(r'[-_.]+', '_', n).lower()  # noqa: E731
WHEELS = {}
for w in [*(COMP / 'wheels').glob('*.whl'), *EXTRA.glob('*.whl'), *PYDS.glob('*.whl')]:
    name, ver = w.name.split('-')[:2]
    WHEELS.setdefault(norm(name), []).append((Version(ver), w))

OWN = {'fastapi/fastapi': 'fastapi', 'Textualize/rich': 'rich', 'psf/requests': 'requests', 'encode/httpx': 'httpx'}
ONLY_FOR = {'pytest_httpbin': {'psf/requests'}, 'httpbin': {'psf/requests'}, 'flasgger': {'psf/requests'},
            'brotlicffi': {'psf/requests', 'encode/httpx'}, 'brotli': {'encode/httpx'}, 'zstandard': {'encode/httpx'}}
# Held-out dev set from other repositories (scripts/push_heldout_build.py), when mounted.
for _r in glob.glob('/kaggle/input/*/gemma-heldout-build/heldout/repos.json') + \
        glob.glob('/kaggle/input/*/*/gemma-heldout-build/heldout/repos.json') + \
        glob.glob('/kaggle/input/gemma-heldout-build/heldout/repos.json'):
    OWN.update({k: norm(v) for k, v in json.loads(Path(_r).read_text()).items()})
    for w in (Path(_r).parent / 'wheels').glob('*.whl'):
        name, ver = w.name.split('-')[:2]
        WHEELS.setdefault(norm(name), []).append((Version(ver), w))
    break
HOST_TAG = f'cp{sys.version_info.major}{sys.version_info.minor}'
PY = {HOST_TAG: Path(sys.executable)}


def python_for(tag):
    if tag not in PY:
        ver = f'{tag[2]}.{tag[3:]}'
        dest = Path(f'/kaggle/working/py{tag}')
        if not (dest / 'python' / 'bin' / f'python{ver}').exists():
            with tarfile.open(PYDS / f'cpython-{ver}-linux.tgz.bin', 'r:gz') as t:
                t.extractall(dest)
        PY[tag] = dest / 'python' / 'bin' / f'python{ver}'
    return PY[tag]


BASE = {}


def base_for(repo, tag):
    if (repo, tag) not in BASE:
        sel = {}
        for name, opts in WHEELS.items():
            opts = [(v, w) for v, w in opts if fits(w, tag)]
            if not opts or name == OWN[repo] or (name in ONLY_FOR and repo not in ONLY_FOR[name]):
                continue
            comp = [(v, w) for v, w in opts if w.parent == COMP / 'wheels']
            if name in ('pytest', 'pytest_timeout'):  # what Dockerfile.sandbox pip-installs
                sel[name] = next(w for v, w in opts if str(v) in ('8.4.2', '2.1.0'))
            elif comp:
                sel[name] = max(comp)[1]
            elif name != 'pygments':
                sel[name] = max(opts)[1]
        d = Path(f'/kaggle/working/scorer_site_{OWN[repo]}_{tag}')
        shutil.rmtree(d, ignore_errors=True)
        subprocess.run([str(python_for(tag)), '-m', 'pip', 'install', '-q', '--no-index', '--no-deps',
                        '--ignore-requires-python', '--target', str(d), *map(str, sel.values())])
        for shim in ('imp.py', 'telnetlib.py'):
            shutil.copy(COMP / 'docker' / shim, d / shim)
        BASE[(repo, tag)] = (d, sel)
    return BASE[(repo, tag)]


# ---------------------------------------------------------------- calibration for public tasks
CALIBRATION = {
    'rich_3064': {'pygments': '2.15.1'}, 'rich_3130': {'pygments': '2.15.1'}, 'rich_3296': {'pygments': '2.16.1'},
    'rich_3469': {'pygments': '2.18.0'}, 'rich_3782': {'pygments': '2.19.2'}, 'rich_4070': {'pygments': '2.19.2'},
    'rich_4079': {'pygments': '2.20.0'},
    'requests_6589': {'werkzeug': '2.3.8', 'flask': '2.3.3'}, 'requests_6592': {'werkzeug': '2.3.8', 'flask': '2.3.3'},
    'requests_6629': {'werkzeug': '2.3.8', 'flask': '2.3.3'},
}
TASK_PYTHON = {'requests_6757': 'cp312', 'rich_3472': 'cp312'}
ASYNC_SHIM = {'fastapi_15745', 'fastapi_15763', 'fastapi_15785'}
NO_CERT_TIME = {'requests_6757'}

SHIM = Path('/kaggle/working/shims')
(SHIM / 'swe_async_shim-0.1.dist-info').mkdir(parents=True, exist_ok=True)
(SHIM / 'swe_async_shim-0.1.dist-info' / 'METADATA').write_text('Metadata-Version: 2.1\nName: swe-async-shim\nVersion: 0.1\n')
(SHIM / 'swe_async_shim-0.1.dist-info' / 'entry_points.txt').write_text('[pytest11]\nswe_async_shim = swe_async_shim\n')
(SHIM / 'swe_async_shim.py').write_text('''import asyncio, inspect
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {a: pyfuncitem.funcargs[a] for a in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
''')
(SHIM / 'swe_no_cert_time.py').write_text('''import ssl

_new = ssl.SSLContext.__new__


def _new_no_time(cls, *args, **kwargs):
    ctx = _new(cls, *args, **kwargs)
    ctx.verify_flags |= 0x200000
    return ctx


ssl.SSLContext.__new__ = staticmethod(_new_no_time)
''')


def poetry_to_pep440(spec):
    spec = spec if isinstance(spec, str) else spec.get('version', '')
    m = re.fullmatch(r'\^(\d+)(\.\d+)?(\.\d+)?', spec.strip())
    return f'>={spec.strip()[1:]},<{int(m.group(1)) + 1}' if m else ('' if spec.strip() == '*' else spec)


CURRENT = {'id': None}


def setup_env(docker, sandbox_id, repo='', **kwargs):
    tid = CURRENT['id']
    tag = TASK_PYTHON.get(tid, 'cp313')
    site = Path(docker.exec(sandbox_id, 'python -c "import site; print(site.getsitepackages()[0])"').stdout.strip())
    if tag != HOST_TAG:  # rebuild the sandbox venv on the scorer's interpreter
        venv_dir = site.parents[2]
        subprocess.run([str(python_for(tag)), '-m', 'venv', '--clear', '--without-pip', str(venv_dir)], check=True)
        site = next(venv_dir.glob('lib/python3*/site-packages'))
    ws = docker.exec(sandbox_id, 'pwd').stdout.strip()
    base, sel = base_for(repo, tag)
    (site / '00_src.pth').write_text(f'{ws}/src\n')
    (site / '01_scorer_base.pth').write_text(f'{base}\n')
    (site / 'zz_workspace_paths.pth').write_text('\n'.join(str(p) for p in Path(ws).iterdir()
                                                           if p.is_dir() and not p.name.startswith('.')) + '\n')
    if tid in ASYNC_SHIM:
        (site / '02_async_shim.pth').write_text(f'{SHIM}\n')
    if tid in NO_CERT_TIME:
        (site / '03_no_cert_time.pth').write_text(f'import sys; sys.path.insert(0, {str(SHIM)!r}); import swe_no_cert_time\n')
    try:
        data = tomllib.loads(Path(ws, 'pyproject.toml').read_text())
    except Exception:
        data = {}
    reqs = list(data.get('project', {}).get('dependencies', []))
    reqs += [n + poetry_to_pep440(s) for n, s in data.get('tool', {}).get('poetry', {}).get('dependencies', {}).items()
             if n != 'python']
    picks, queue, seen = {}, list(reqs), set()
    while queue:
        try:
            req = Requirement(queue.pop(0))
        except Exception:
            continue
        key = norm(req.name)
        if key in seen or key == OWN.get(repo) or (req.marker and not req.marker.evaluate({'extra': ''})):
            continue
        seen.add(key)
        options = [(v, w) for v, w in WHEELS.get(key, []) if fits(w, tag) and req.specifier.contains(v, prereleases=True)
                   and not (key in ONLY_FOR and repo not in ONLY_FOR[key])]
        if options:
            best = max(options)[1]
            if best != sel.get(key):
                picks[key] = best
            with zipfile.ZipFile(best) as z:
                meta = next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
                queue += [l.split(':', 1)[1].strip() for l in z.read(meta).decode().splitlines()
                          if l.startswith('Requires-Dist:')]
    for name, ver in CALIBRATION.get(tid, {}).items():
        picks[name] = next(w for v, w in WHEELS[name] if str(v) == ver and fits(w, tag))
    if picks:
        subprocess.run([str(python_for(tag)), '-m', 'pip', 'install', '-q', '--no-index', '--no-deps', '--upgrade',
                        '--ignore-requires-python', '--target', str(site), *map(str, picks.values())])


verification.install_test_dependencies = setup_env
agent_runner.install_test_dependencies = setup_env
# ==== end scorer_env.py ====
