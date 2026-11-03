"""Push the reproduction kernel (scripts/kaggle_repro.py) that recomputes the paper's numbers.

    python scripts/push_repro.py [--public]
    kaggle kernels logs <user>/gemma-agent-paper-repro | grep -E 'PART|RUN|flips|union|^v|^pub'

It mounts our eval kernels' outputs, so for a public copy those kernels must be public too.
CPU only; no GPU quota.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from push_eval import ROOT, kaggle_username

OLD_RUNS = {'v6': ['v6', 'v6b'], 'v7': ['v7'], 'v8': ['v8'], 'v9': ['v9'], 'v10': ['v10'],
            'pub24': ['pub24'], 'v11': ['v11'], 'v11b': ['v11b']}
NEW_RUNS = {'v6s': ['v6s'], 'v11s': ['v11s'], 'v12': ['v12'], 'v12b': ['v12b'], 'v12c': ['v12c'],
            'v13smoke': ['v13smoke'], 'v12b2': ['v12b2'], 'v12c2': ['v12c2'],
            'v15a': ['v15a'], 'v15b': ['v15b'], 'v15t': ['v15t']}
PAIRS = [
    ('v11', 'v11b', 'dev48', 'same agent, two runs (noise)'),
    ('v6', 'v6s', 'dev48', 'same agent, old vs matched agent sandbox'),
    ('v6', 'v11', 'dev48', 'complete-the-fix step'),
    ('v6', 'v7', 'dev48', 'bigger budget'),
    ('v6', 'v10', 'dev48', 'reproduce-then-verify'),
    ('v6', 'pub24', 'dev48', 'public 0.24 agent'),
    ('v6s', 'v11s', 'dev48', 'matched env: v6 vs v11'),
    ('v11s', 'v12', 'dev48', 'split, prompt limit'),
    ('v11s', 'v12b', 'dev48', 'split, enforced limit'),
    ('v11s', 'v12c', 'dev48a', 'split, fixer cannot read (24 tasks)'),
    ('v11s', 'v13smoke', 'dev10', 'edits through run_command (10 tasks)'),
    ('v11s', 'v12b2', 'dev48', 'split, enforced limit (second run)'),
    ('v11s', 'v12c2', 'dev48a', 'split, fixer cannot read (second run, 24 tasks)'),
    ('v11s', 'v15a', 'dev48', 'function-level locator'),
    ('v11s', 'v15b', 'dev48', 'function-level locator (second run)'),
    ('v15a', 'v15b', 'dev48', 'same agent, two runs (noise)'),
    ('v15a', 'v15t', 'dev48', 'sampling T=1.0, top_k 64'),
]


def ids(name):
    return [t for t in (ROOT / 'eval' / name).read_text().split() if t]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--public', action='store_true')
    a = ap.parse_args()
    user = kaggle_username()
    kname = lambda r: f'gemma-eval-{r}'  # noqa: E731
    old = {n: [kname(r) for r in rs] for n, rs in OLD_RUNS.items()}
    new = {n: [kname(r) for r in rs] for n, rs in NEW_RUNS.items()}
    src = (ROOT / 'scripts/kaggle_repro.py').read_text(encoding='utf-8')
    src = src.replace('# __SCORER_ENV__', (ROOT / 'scripts/scorer_env.py').read_text(encoding='utf-8'), 1)
    fill = {'OLD_RUNS: dict[str, list[str]] = {}': f'OLD_RUNS = {old!r}',
            'NEW_RUNS: dict[str, list[str]] = {}': f'NEW_RUNS = {new!r}',
            'GOLD_TASKS: list[str] = []': f'GOLD_TASKS = {sorted(set(ids("dev48.txt")) | set(ids("rich44.txt")))!r}',
            'DEV48: list[str] = []': f'DEV48 = {ids("dev48.txt")!r}',
            'DEV48A: list[str] = []': f'DEV48A = {ids("dev48a.txt")!r}',
            'DEV10: list[str] = []': f'DEV10 = {ids("dev10.txt")!r}',
            'PAIRS: list[tuple] = []': f'PAIRS = {PAIRS!r}'}
    for k, v in fill.items():
        assert k in src, k
        src = src.replace(k, v, 1)
    compile(src, 'repro.py', 'exec')
    runs = [k for ks in [*old.values(), *new.values()] for k in ks]
    meta = {
        'id': f'{user}/gemma-agent-paper-repro', 'title': 'gemma-agent-paper-repro', 'code_file': 'repro.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': not a.public,
        'enable_gpu': False, 'enable_internet': False,
        'competition_sources': ['gemma-4-developer-agent'],
        'dataset_sources': ['metric/gemma-4-developer-agent-wheelhouse',
                            'zbigniewkirchner/gemma-4-agent-local-eval-wheels',
                            'zbigniewkirchner/gemma-4-agent-local-eval-pythons'],
        'kernel_sources': [f'{user}/{k}' for k in runs],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'repro.py').write_text(src)
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        print(meta['id'], 'private' if meta['is_private'] else 'PUBLIC', len(runs), 'kernels')
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
