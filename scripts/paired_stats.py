"""Paired per-task statistics between dev48 runs, from saved regrade and digest files.

    python scripts/paired_stats.py

For each pair of runs on the same tasks it prints solved counts, the tasks only one
side solved, an exact two-sided McNemar (sign) test on those discordant tasks, and a
95% bootstrap interval for the difference in solved tasks (resampling tasks).
Runs whose patches were empty or missing count as unsolved on every task they cover.
"""
import json
import random
import re
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / 'results'
DEV48 = [l.strip() for l in (ROOT / 'eval/dev48.txt').read_text().splitlines() if l.strip()]
DEV48A = [l.strip() for l in (ROOT / 'eval/dev48a.txt').read_text().splitlines() if l.strip()]


def from_regrade(*runs):
    """Solved set from REGRADE lines; several run names are merged (a run split over kernels)."""
    solved = set()
    for f in (RES / 'regrade').glob('*.txt'):
        for line in f.read_text().splitlines():
            p = line.split()
            if len(p) >= 4 and p[0] == 'REGRADE' and p[1] in runs and p[3] == 'True':
                solved.add(p[2])
    return solved


def from_digest(path, run):
    solved = set()
    for line in (RES / 'digest' / path).read_text().splitlines():
        if line.startswith(f'RESULT {run} '):
            r = json.loads(line.split(' ', 2)[2])
            if r['resolved']:
                solved.add(r['instance_id'])
    return solved


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def boot_ci(a, b, tasks, n=10000, seed=0):
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        s = [rng.choice(tasks) for _ in tasks]
        diffs.append(sum((t in b) - (t in a) for t in s))
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]


RUNS = {
    'v6': from_regrade('v6', 'v6b'),
    'v7': from_regrade('v7'), 'v8': from_regrade('v8'), 'v9': from_regrade('v9'), 'v10': from_regrade('v10'),
    'v11': from_regrade('v11'), 'v11b': from_regrade('v11b'), 'pub24': from_regrade('pub24'),
    'v6s': from_digest('digest_v6s_v11s_plain.txt', 'v6s'),
    'v11s': from_digest('digest_v6s_v11s_plain.txt', 'v11s'),
    'v12': from_digest('digest_v12_obs.txt', 'v12'),
    'v12b': from_digest('digest_v12b_obs.txt', 'v12b'),
    'v12c': from_digest('digest_v12c_obs.txt', 'v12c'),
    'v15a': from_digest('digest_v15a_v15t_obs.txt', 'v15a'),
    'v15t': from_digest('digest_v15a_v15t_obs.txt', 'v15t'),
    'v15b': from_digest('digest_v15b_obs.txt', 'v15b'),
    'v12b2': from_digest('digest_v12b2_v12c2_obs.txt', 'v12b2'),
    'v12c2': from_digest('digest_v12b2_v12c2_obs.txt', 'v12c2'),
    'v15o': from_digest('digest_v15o_obs.txt', 'v15o'),
}

PAIRS = [
    ('v11', 'v11b', DEV48, 'same agent, two runs (noise)'),
    ('v6', 'v6s', DEV48, 'same agent, old vs matched agent sandbox'),
    ('v6', 'v11', DEV48, 'complete-the-fix step'),
    ('v6', 'v7', DEV48, 'bigger budget'),
    ('v6', 'v10', DEV48, 'reproduce-then-verify'),
    ('v6', 'pub24', DEV48, 'public 0.24 agent'),
    ('v6s', 'v11s', DEV48, 'matched env: v6 vs v11'),
    ('v11s', 'v12', DEV48, 'split, prompt limit'),
    ('v11s', 'v12b', DEV48, 'split, enforced limit'),
    ('v11s', 'v12c', DEV48A, 'split, fixer cannot read (24 tasks)'),
    ('v11s', 'v15a', DEV48, 'better locating'),
    ('v6s', 'v15a', DEV48, 'better locating'),
    ('v15a', 'v15t', DEV48, 'temperature 1.0, top_k 64'),
    ('v11s', 'v15t', DEV48, 'better locating + T=1.0'),
    ('v15a', 'v15b', DEV48, 'same agent, two runs (noise)'),
    ('v11s', 'v15b', DEV48, 'better locating, run 2'),
    ('v6s', 'v15b', DEV48, 'better locating, run 2'),
    ('v12b', 'v12b2', DEV48, 'split, enforced limit, two runs'),
    ('v11s', 'v12b2', DEV48, 'split, enforced limit, run 2'),
    ('v12c', 'v12c2', DEV48A, 'split, fixer cannot read, two runs'),
    ('v11s', 'v12c2', DEV48A, 'split, fixer cannot read, run 2'),
    ('v15a', 'v15o', DEV48, 'told where the fix goes (oracle locations)'),
    ('v15b', 'v15o', DEV48, 'told where the fix goes, vs run 2'),
]

if __name__ == '__main__':
    print(f"{'A':6} {'B':6} {'tasks':>5} {'A':>3} {'B':>3} {'only A':>6} {'only B':>6} {'B-A':>4} {'95% CI':>10} {'p':>6}  note")
    for a, b, tasks, note in PAIRS:
        sa, sb = RUNS[a] & set(tasks), RUNS[b] & set(tasks)
        oa, ob = len(sa - sb), len(sb - sa)
        lo, hi = boot_ci(sa, sb, tasks)
        print(f'{a:6} {b:6} {len(tasks):5} {len(sa):3} {len(sb):3} {oa:6} {ob:6} {len(sb) - len(sa):+4} '
              f'{f"[{lo:+d},{hi:+d}]":>10} {mcnemar_p(oa, ob):6.2f}  {note}')
    union = set().union(*(RUNS[r] & set(DEV48) for r in RUNS if r not in ('v12c', 'v12c2')))
    print(f'union of all dev48 runs: {len(union)} tasks; solved by every full run: '
          f'{len(set.intersection(*(RUNS[r] & set(DEV48) for r in RUNS if r not in ("v12c", "v12c2"))))}')
