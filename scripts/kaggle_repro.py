"""Kaggle CPU kernel: reproduce the paper's evaluation numbers from our eval kernels' outputs.

Pushed by scripts/push_repro.py, which fills in the run lists and task ids. Four parts:
  1. (not rerun) the notebook grader's verdicts, read from each old run's task_results.jsonl
  2. gold patches, and every saved patch of the old runs, graded in a scorer-like
     sandbox (scorer_env.py; setup follows zbigniewkirchner's public notebook)
  3. old runs: in-kernel grade vs scorer-like regrade, task by task (the "flips")
  4. paired comparisons between runs: exact McNemar test and 95% bootstrap interval

Runs in NEW_RUNS already graded inside the scorer-like sandbox, so their own
task_results.jsonl is read as is. CPU only; no GPU quota.
"""
import asyncio
import glob
import importlib
import json
import logging
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from math import comb
from pathlib import Path

OLD_RUNS: dict[str, list[str]] = {}  # paper name -> eval kernels (a run split over kernels is merged)
NEW_RUNS: dict[str, list[str]] = {}
GOLD_TASKS: list[str] = []
DEV48: list[str] = []
DEV48A: list[str] = []
DEV10: list[str] = []
PAIRS: list[tuple] = []  # (a, b, 'dev48' | 'dev48a' | 'dev10', note)
PART = 'all'  # 'regrade': grade gold (if DO_GOLD) and OLD_RUNS, save repro_part.json and stop
DO_GOLD = True  # 'summary': read the regrade parts' repro_part.json, then the new runs and pairs
PRIOR: list[str] = []  # kernels whose repro_part.json the summary part merges

COMP = Path(glob.glob('/kaggle/input/**/tasks.jsonl', recursive=True)[0]).parent
WHEELHOUSE = Path(glob.glob('/kaggle/input/**/adk_submission-*.whl', recursive=True)[0]).parent
print(COMP, WHEELHOUSE, sys.version, sep='\n', flush=True)


def fits(w, tag='cp313'):
    py, abi, plat = w.name[:-4].split('-')[-3:]
    if plat != 'any' and 'linux' not in plat:
        return False
    if abi == 'abi3':
        return int(py.split('.')[0][2:]) <= int(tag[2:])
    return any(t.startswith('py3') for t in py.split('.')) or tag in py.split('.')


tmp = Path('/tmp/wheelhouse')
tmp.mkdir(exist_ok=True)
for w in WHEELHOUSE.glob('*.whl'):  # Kaggle strips '+cu128' from wheel names
    name = w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name
    if not (tmp / name).exists():
        os.symlink(w, tmp / name)
small = [str(w) for w in tmp.glob('*.whl')
         if w.stat().st_size < 50 * 1024**2 and 'cutlass' not in w.name.lower() and fits(w)]
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', *small])
importlib.invalidate_caches()

from adk_eval_core.tracing import SessionTrace  # noqa: E402
from swegemma.config import EvalConfig  # noqa: E402
from swegemma.evaluate import Evaluator  # noqa: E402
from swegemma.models import load_tasks  # noqa: E402
from swegemma.sandbox.subprocess import SubprocessManager  # noqa: E402

logging.getLogger().setLevel(logging.ERROR)
tasks = {t.instance_id: t for t in load_tasks(COMP / 'tasks.jsonl')}
PATCH = {'text': ''}


class PatchEvaluator(Evaluator):
    async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kwargs):
        return PATCH['text'], None, SessionTrace()


def make_evaluator(scorer_like):
    cfg = EvalConfig(tasks_path=COMP / 'tasks.jsonl', snapshots_dir=COMP / 'snapshots',
                     results_dir=Path('/kaggle/working/regrade'), submission_dir=Path('/kaggle/working'),
                     models=None, sandbox='subprocess', wheels_dir=COMP / 'wheels', graph_dir=str(COMP / 'graphs'),
                     embeddings_dir=str(COMP / 'embeddings'), timeout_seconds=300,
                     verification_timeout_seconds=300, display_mode='quiet')
    ev = PatchEvaluator(cfg)
    if scorer_like:
        ev.sandbox = ev.docker = SubprocessManager(timeout_seconds=300, system_site_packages=False)
    return ev


pool = ThreadPoolExecutor(max_workers=1)
CURRENT = {'id': None}


def grade(ev, tid, patch):
    if not patch.strip():
        return False
    CURRENT['id'], PATCH['text'] = tid, patch
    try:
        return bool(pool.submit(asyncio.run, ev.evaluate_task(task=tasks[tid])).result().resolved)
    except Exception as e:
        print('  grading error', tid, repr(e)[:120], flush=True)
        return False


def kernel_results(kernel):
    hits = glob.glob(f'/kaggle/input/**/{kernel}/results', recursive=True)
    if not hits:
        print(f'NO OUTPUT for {kernel}', flush=True)
        return {}, {}
    res = Path(hits[0])
    rows = {}
    for line in (res / 'task_results.jsonl').read_text().splitlines():
        r = json.loads(line)
        rows[r['instance_id']] = bool(r.get('resolved'))
    patches = {p.stem: p.read_text() for p in (res / 'patches').glob('*.patch')}
    return rows, patches


t0 = time.time()
# 1. The notebook grader is not rerun here: offline it retries pip installs for every task and
#    runs for hours. Its verdicts come from each old run's own task_results.jsonl (part 3), and
#    its gold-patch pass rate (52 of 129) from zbigniewkirchner's public notebook.

# __SCORER_ENV__

# ---------------------------------------------------------------- 2. scorer-like grader
SOLVED, OLD_GRADE = {}, {}
flips = {'fail->pass': 0, 'pass->fail': 0}
if PART != 'summary':
    ev_sc = make_evaluator(scorer_like=True)
if PART != 'summary' and DO_GOLD:
    gold_sc = {tid: grade(ev_sc, tid, tasks[tid].patch) for tid in GOLD_TASKS}
    print(f'PART2 gold patches passing, scorer-like grader: {sum(gold_sc.values())} of {len(GOLD_TASKS)} '
          f'({time.time() - t0:.0f}s)', flush=True)

for name, kernels in (OLD_RUNS.items() if PART != 'summary' else []):
    old, new = set(), set()
    for k in kernels:
        rows, patches = kernel_results(k)
        for tid, ok in rows.items():
            if tid not in DEV48:
                continue
            old |= {tid} if ok else set()
            if grade(ev_sc, tid, patches.get(tid, '')):
                new.add(tid)
    OLD_GRADE[name], SOLVED[name] = old, new
    flips['fail->pass'] += len(new - old)
    flips['pass->fail'] += len(old - new)
    print(f'RUN {name}: notebook grader {len(old)}, scorer-like {len(new)} '
          f'({time.time() - t0:.0f}s)', flush=True)
if PART == 'regrade':
    Path('/kaggle/working/repro_part.json').write_text(json.dumps(
        {'solved': {k: sorted(v) for k, v in SOLVED.items()},
         'old_grade': {k: sorted(v) for k, v in OLD_GRADE.items()}, 'flips': flips}))
    print(f'saved repro_part.json ({time.time() - t0:.0f}s)')
    sys.exit(0)
for k in PRIOR:
    hits = glob.glob(f'/kaggle/input/**/{k}/repro_part.json', recursive=True)
    if not hits:
        print(f'NO PART OUTPUT for {k}', flush=True)
        continue
    d = json.loads(Path(hits[0]).read_text())
    SOLVED.update({n: set(v) for n, v in d['solved'].items()})
    OLD_GRADE.update({n: set(v) for n, v in d['old_grade'].items()})
    for f in flips:
        flips[f] += d['flips'][f]
    for n in d['solved']:
        print(f"RUN {n}: notebook grader {len(d['old_grade'][n])}, scorer-like {len(d['solved'][n])} (from {k})")
for name, kernels in NEW_RUNS.items():
    s = set()
    for k in kernels:
        rows, _ = kernel_results(k)
        s |= {t for t, ok in rows.items() if ok}
    SOLVED[name] = s

# ---------------------------------------------------------------- 3. summary table
print('\n== PART3 solved tasks per run ==')
print(f"{'run':8} {'tasks':>5} {'notebook':>9} {'scorer-like':>11}")
for name in [*OLD_GRADE, *NEW_RUNS]:
    n_tasks = {'v12c': len(DEV48A), 'v12c2': len(DEV48A), 'v13smoke': len(DEV10)}.get(name, len(DEV48))
    print(f"{name:8} {n_tasks:>5} {len(OLD_GRADE[name]) if name in OLD_GRADE else '-':>9} {len(SOLVED[name]):>11}")
print(f"flips across old runs: {flips['fail->pass']} fail->pass, {flips['pass->fail']} pass->fail")


# ---------------------------------------------------------------- 4. paired comparisons
def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def boot_ci(a, b, ts, n=10000, seed=0):
    rng = random.Random(seed)
    d = sorted(sum((t in b) - (t in a) for t in (rng.choice(ts) for _ in ts)) for _ in range(n))
    return d[int(0.025 * n)], d[int(0.975 * n)]


print('\n== PART4 paired comparisons ==')
print(f"{'A':6} {'B':6} {'tasks':>5} {'A':>3} {'B':>3} {'only A':>6} {'only B':>6} {'B-A':>4} {'95% CI':>10} {'p':>6}  note")
for a, b, which, note in PAIRS:
    ts = {'dev48': DEV48, 'dev48a': DEV48A, 'dev10': DEV10}[which]
    sa, sb = SOLVED[a] & set(ts), SOLVED[b] & set(ts)
    oa, ob = len(sa - sb), len(sb - sa)
    lo, hi = boot_ci(sa, sb, ts)
    print(f'{a:6} {b:6} {len(ts):5} {len(sa):3} {len(sb):3} {oa:6} {ob:6} {len(sb) - len(sa):+4} '
          f'{f"[{lo:+d},{hi:+d}]":>10} {mcnemar_p(oa, ob):6.2f}  {note}')
full = [r for r in SOLVED if r not in ('v12c', 'v12c2', 'v13smoke')]
union = set().union(*(SOLVED[r] & set(DEV48) for r in full))
print(f'union of dev48 runs: {len(union)} tasks; solved by every full run: '
      f'{len(set.intersection(*(SOLVED[r] & set(DEV48) for r in full)))}')
print(f'done in {time.time() - t0:.0f}s')
