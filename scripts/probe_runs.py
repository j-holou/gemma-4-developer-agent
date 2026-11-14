"""One-off CPU kernel: why patched tasks fail, what non-tool model replies are, compaction and token use.

    python scripts/probe_runs.py v15a v15b v16a v16b     # pushes janholoubek/gemma-eval-probe
    kaggle kernels logs janholoubek/gemma-eval-probe
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KERNEL = r'''
import glob, json, os, re, collections
from pathlib import Path
RUNS = __RUNS__
tasks = {}
for tp in glob.glob("/kaggle/input/competitions/*/tasks.jsonl") + glob.glob("/kaggle/input/*/tasks.jsonl"):  # no recursive glob: the snapshots tree is huge
    for line in open(tp):
        t = json.loads(line); tasks[t.get("instance_id")] = t
    print("TASKS", tp, len(tasks), sorted(t.keys())[:40]); break
shown_trace = 0
for run in RUNS:
    hits = [h for pat in ("/kaggle/input/gemma-eval-{}/results", "/kaggle/input/*/gemma-eval-{}/results", "/kaggle/input/*/*/gemma-eval-{}/results")
            for h in glob.glob(pat.format(run))]
    if not hits:
        print("MISSING", run, os.listdir("/kaggle/input")); continue
    res = Path(hits[0])
    print(f"##### RUN {run} files={sorted(p.name for p in res.iterdir())}")
    rows = [json.loads(l) for l in (res / "task_results.jsonl").read_text().splitlines()]
    print("KEYS", sorted(rows[0].keys()))
    to = res / "test_outputs"
    names = sorted(p.name for p in to.iterdir())
    print("TEST_OUTPUT_FILES", len(names), names[:6])
    for r in rows:
        if r.get("resolved") or not r.get("agent_patch_size"):
            continue
        iid = r["instance_id"]
        out = "".join(p.read_text(errors="replace") for p in sorted(to.glob(f"*{iid}*")) if p.is_file())
        tp = tasks.get(iid, {}).get("test_patch") or ""
        new_tests, cur_file, touched = set(), "", set()
        for line in tp.splitlines():
            if line.startswith("+++ "):
                cur_file = line[6:]
            m = re.match(r"^\+\s*(?:async\s+)?def (test\w*)", line)
            if m: new_tests.add(m.group(1))
            m = re.match(r"^@@.*@@\s*(?:async\s+)?def (test\w*)", line)
            if m: touched.add(m.group(1))
        failed = re.findall(r"^(FAILED|ERROR) (\S+)", out, flags=re.M)
        fn = [f.split("::")[-1].split("[")[0] for _, f in failed]
        n_new = sum(1 for f in fn if f in new_tests or f in touched)
        summary = [l.strip() for l in out.splitlines() if re.search(r"\d+ (passed|failed|error)", l)][-1:]
        print("FAIL", run, json.dumps({"id": iid, "exit": r.get("test_exit_code"), "err": str(r.get("error") or "")[:60],
              "n_new_tests": len(new_tests), "n_touched": len(touched), "n_failed": len(failed), "failed_new": n_new, "failed_other": len(failed) - n_new,
              "n_error_lines": sum(1 for k, _ in failed if k == "ERROR"), "failed": [f for _, f in failed][:5], "summary": summary, "out_len": len(out),
              "tail": out[-700:] if not failed else "", "first_E": [l.strip()[:160] for l in out.splitlines() if l.startswith("E  ")][:3]}))
    for tf in sorted((res / "traces").glob("*.json")):
        d = json.load(open(tf))
        tid = tf.stem.replace("trace_", "")
        kinds = collections.Counter(); comp = 0; ctoks = []; rtoks = []; ptoks = []
        for s in d.get("steps", []):
            src = s.get("source"); has_tc = bool(s.get("tool_calls")); msg = str(s.get("message") or "")
            kinds[f"{src}|tc={int(has_tc)}|msg={int(bool(msg.strip()))}"] += 1
            blob = json.dumps(s)[:20000].lower()
            if "compact" in blob or "summary of" in blob[:400]:
                comp += 1
            m = s.get("metrics") or {}
            if m.get("completion_tokens") is not None:
                ctoks.append(m.get("completion_tokens")); ptoks.append(m.get("prompt_tokens") or 0)
                rtoks.append((m.get("extra") or {}).get("reasoning_tokens") or m.get("reasoning_tokens") or 0)
        print("TR", run, json.dumps({"id": tid, "kinds": kinds, "compact_steps": comp, "n_llm": len(ctoks), "ctok_sum": sum(ctoks), "ctok_max": max(ctoks or [0]),
              "rtok_sum": sum(rtoks), "ptok_max": max(ptoks or [0]), "ptok_drops": sum(1 for a, b in zip(ptoks, ptoks[1:]) if b < a * 0.7)}))
        if shown_trace < 0:
            shown_trace += 1
            print("TOPKEYS", sorted(d.keys()))
            for i, s in enumerate(d.get("steps", [])[:45]):
                e = {k: (str(v)[:260] if k not in ("tool_calls",) else [tc.get("function_name") for tc in v]) for k, v in s.items()}
                print("   STEP", i, json.dumps(e)[:900])
'''


def main() -> None:
    runs = sys.argv[1:]
    user = os.environ.get('KAGGLE_USERNAME', 'janholoubek')
    meta = {
        'id': f'{user}/gemma-eval-probe', 'title': 'gemma-eval-probe', 'code_file': 'probe.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_internet': False,
        'kernel_sources': [f'{user}/gemma-eval-{r}' for r in runs],
        'dataset_sources': [], 'competition_sources': ['gemma-4-developer-agent'],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'probe.py').write_text(KERNEL.replace('__RUNS__', repr(runs)))
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
