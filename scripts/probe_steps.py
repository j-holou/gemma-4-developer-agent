"""CPU kernel: one compact line per tool call (time, command kind, error, output head) for eval runs.

    python scripts/probe_steps.py v18a v18b    # pushes janholoubek/gemma-eval-steps

Used to find where v18 still loses calls and time: failing shell commands, slow steps,
and whether check_patch's review questions were followed by another edit.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KERNEL = r'''
import glob, json, re
from pathlib import Path
RUNS = __RUNS__

def kind(cmd):
    c = cmd.replace("cd /workspace && ", "").strip()
    for k in ("t/read.py", "t/lookup.py", "t/locate.py", "t/find_tests.py", "t/check_patch.py", "sr.py"):
        if k in c: return k.replace("t/", "")
    if "pytest" in c: return "pytest"
    if re.match(r"python3? -c", c): return "py-c"
    if "/tmp/" in c and "python" in c: return "py-file"
    if c.startswith(("cat <<", "cat >")): return "write-file"
    if c.startswith(("grep", "rg ")) or " grep " in c[:40]: return "grep"
    if c.startswith(("cat ", "sed -n", "head", "tail", "nl ")): return "cat"
    if c.startswith(("ls", "find")): return "ls"
    if c.startswith("git"): return "git"
    return "other:" + c.split()[0][:15] if c else "empty"

for run in RUNS:
    hits = [h for pat in ("/kaggle/input/gemma-eval-{}/results", "/kaggle/input/*/gemma-eval-{}/results", "/kaggle/input/*/*/gemma-eval-{}/results") for h in glob.glob(pat.format(run))]
    if not hits:
        print("MISSING", run); continue
    res = Path(hits[0])
    rows = {json.loads(l)["instance_id"]: json.loads(l) for l in (res / "task_results.jsonl").read_text().splitlines()}
    for tf in sorted((res / "traces").glob("*.json")):
        d = json.load(open(tf)); iid = tf.stem.replace("trace_", "")
        r = rows.get(iid, {})
        print("TASK", run, iid, json.dumps({k: r.get(k) for k in ("resolved", "agent_patch_size", "duration_seconds", "tool_calls")}))
        prev = 0.0
        for s in d.get("steps", []):
            obs = str((s.get("observation") or {}).get("content", ""))
            for tc in s.get("tool_calls") or []:
                t = tc.get("extra", {}).get("elapsed_s", 0) or 0
                name = tc.get("function_name"); a = tc.get("arguments") or {}
                if name == "run_command":
                    cmd = str(a.get("command", "")); k = kind(cmd)
                else:
                    cmd = json.dumps(a)[:120]; k = name
                err = '"status": "error"' in obs[:400] or "Traceback" in obs or "NOT applied" in obs
                rv = "REVIEW" if "Review before submitting" in obs else ""
                print("S", run, iid, f"{t:.0f}", f"{t - prev:.0f}", k, int(err), rv,
                      json.dumps(cmd[:160]), json.dumps(obs[:260]), json.dumps(obs[-160:]) if len(obs) > 260 else '""')
                prev = t
'''


def main() -> None:
    runs = sys.argv[1:]
    user = os.environ.get('KAGGLE_USERNAME', 'janholoubek')
    meta = {
        'id': f'{user}/gemma-eval-steps', 'title': 'gemma-eval-steps', 'code_file': 'steps.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_internet': False,
        'kernel_sources': [f'{user}/gemma-eval-{r}' for r in runs],
        'dataset_sources': [], 'competition_sources': [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'steps.py').write_text(KERNEL.replace('__RUNS__', repr(runs)))
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
