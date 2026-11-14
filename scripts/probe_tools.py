"""CPU kernel: how often each tool call fails because its arguments arrive malformed.

    python scripts/probe_tools.py v15a v15b v16a v16b    # pushes janholoubek/gemma-eval-tools
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KERNEL = r'''
import glob, json, re, collections
from pathlib import Path
RUNS = __RUNS__
shown = collections.Counter()
for run in RUNS:
    hits = [h for pat in ("/kaggle/input/gemma-eval-{}/results", "/kaggle/input/*/gemma-eval-{}/results", "/kaggle/input/*/*/gemma-eval-{}/results") for h in glob.glob(pat.format(run))]
    if not hits:
        print("MISSING", run); continue
    res = Path(hits[0])
    rows = {json.loads(l)["instance_id"]: json.loads(l) for l in (res / "task_results.jsonl").read_text().splitlines()}
    stat = collections.Counter(); budget_cmp = []
    for tf in sorted((res / "traces").glob("*.json")):
        d = json.load(open(tf)); iid = tf.stem.replace("trace_", "")
        n_steps = 0; n_bad = 0; pos_bad = []
        for s in d.get("steps", []):
            obs = str((s.get("observation") or {}).get("content", ""))
            for tc in s.get("tool_calls") or []:
                n_steps += 1
                name = tc.get("function_name"); a = tc.get("arguments") or {}
                key = name
                if name == "run_skill_script":
                    fp = str(a.get("file_path", ""))
                    m = re.match(r"^scripts/(\w+)\.py", fp)
                    key = "skill:" + (m.group(1) if m else "?")
                    argkind = "noargs" if not a.get("args") else ("list" if isinstance(a.get("args"), list) else ("int" if any(isinstance(v, (int, float)) for v in a["args"].values()) else "str"))
                else:
                    argkind = ""
                head = obs[:400]
                if "BudgetExceeded" in head or "budget exhausted" in head.lower(): out = "over_budget"
                elif '"error_code": "SKILL_NOT_FOUND"' in head: out = "bad:skill_name_garbled"
                elif '"error_code": "INVALID_ARGUMENTS"' in head: out = "bad:arg_missing"
                elif '"error_code"' in head: out = "bad:" + (re.search(r'"error_code": "(\w+)"', head) or [0, "?"])[1]
                elif name != "run_skill_script" and re.search(r"missing|required|unexpected keyword|validation error|not a valid", head, re.I) and '"status": "error"' in head: out = "bad:args"
                elif '"status": "error"' in head: out = "tool_error"
                else: out = "ok"
                stat[(key, argkind, out)] += 1
                if out.startswith("bad"):
                    n_bad += 1; pos_bad.append(n_steps)
                    if shown[out] < 6:
                        shown[out] += 1
                        print("EX", run, iid, out, json.dumps(a)[:500], "| OBS", head[:200], "| MSGTAIL", repr(str(s.get("message") or "")[-200:]))
        r = rows.get(iid, {})
        budget_cmp.append((r.get("tool_calls"), n_steps, n_bad))
    print("STAT", run, json.dumps(sorted([list(k) + [v] for k, v in stat.items()])))
    print("BUDGET", run, json.dumps(budget_cmp))
'''


def main() -> None:
    runs = sys.argv[1:]
    user = os.environ.get('KAGGLE_USERNAME', 'janholoubek')
    meta = {
        'id': f'{user}/gemma-eval-tools', 'title': 'gemma-eval-tools', 'code_file': 'tools.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_internet': False,
        'kernel_sources': [f'{user}/gemma-eval-{r}' for r in runs],
        'dataset_sources': [], 'competition_sources': [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'tools.py').write_text(KERNEL.replace('__RUNS__', repr(runs)))
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
