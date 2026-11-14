"""CPU kernel: one record per task-run saying where the agent looked, what it edited and how that compares
with the reference patch, so wrong and empty patches can be sorted by cause.

    python scripts/probe_causes.py v15a v15b v16a v16b    # pushes janholoubek/gemma-eval-causes
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
tasks = {}
for tp in glob.glob("/kaggle/input/competitions/*/tasks.jsonl") + glob.glob("/kaggle/input/*/tasks.jsonl"):
    for line in open(tp):
        t = json.loads(line); tasks[t["instance_id"]] = t
    break

def hunks(patch):
    """{file: [(start, end, changed_lines)]} using old-file line numbers; skips test files."""
    out, cur = {}, None
    for line in (patch or "").splitlines():
        if line.startswith("diff --git"):
            cur = None
        elif line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
            if cur: out.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                s = int(m.group(1)); n = int(m.group(2) or 1)
                out[cur].append([s, s + max(n, 1) - 1, 0])
        elif cur and out.get(cur) and (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---")):
            out[cur][-1][2] += 1
    return out

def is_test(p):
    b = p.rsplit("/", 1)[-1]
    return b.startswith(("test_", "conftest")) or b.endswith("_test.py") or "/tests/" in "/" + p or p.startswith("tests/")

def sr_outcome(obs):
    o = obs
    if "Applied to" in o: return "applied"
    if "No such file or directory" in o and "sr.py" in o or "can't open file" in o: return "helper_missing"
    if "SEARCH text not found" in o: return "not_found"
    if "occurs" in o and "times" in o or "match at lines" in o: return "ambiguous"
    if "syntax error" in o: return "syntax_refused"
    if "No SEARCH/REPLACE block" in o: return "bad_format"
    if "REFUSED" in o: return "refused"
    if "exceeded" in o.lower() or "budget" in o.lower() and "remaining" not in o.lower(): return "budget"
    return "other:" + re.sub(r"\s+", " ", o)[:90]

for run in RUNS:
    hits = [h for pat in ("/kaggle/input/gemma-eval-{}/results", "/kaggle/input/*/gemma-eval-{}/results", "/kaggle/input/*/*/gemma-eval-{}/results") for h in glob.glob(pat.format(run))]
    if not hits:
        print("MISSING", run); continue
    res = Path(hits[0])
    for line in (res / "task_results.jsonl").read_text().splitlines():
        r = json.loads(line); iid = r["instance_id"]; t = tasks.get(iid, {})
        gold = {f: h for f, h in hunks(t.get("patch")).items() if not is_test(f)}
        pp = res / "patches" / f"{iid}.patch"
        cand = list((res / "patches").glob(f"*{iid}*"))
        ptxt = cand[0].read_text(errors="replace") if cand else ""
        mine_all = hunks(ptxt)
        mine = {f: h for f, h in mine_all.items() if not is_test(f)}
        hit = tot = 0
        for f, hs in gold.items():
            for s, e, _ in hs:
                tot += 1
                if any(s2 - 5 <= e and s <= e2 + 5 for s2, e2, _ in mine.get(f, [])): hit += 1
        rec = {"id": iid, "resolved": r.get("resolved"), "patch_size": r.get("agent_patch_size"), "err": bool(r.get("error")), "calls": r.get("tool_calls"),
               "dur": round(r.get("duration_seconds") or 0), "gold_files": sorted(gold), "gold_hunks": tot, "gold_lines": sum(h[2] for hs in gold.values() for h in hs),
               "my_files": sorted(mine), "my_test_files": sorted(f for f in mine_all if is_test(f)), "my_lines": sum(h[2] for hs in mine.values() for h in hs),
               "gold_hunks_touched": hit, "gold_files_touched": sum(1 for f in gold if f in mine), "extra_files": sum(1 for f in mine if f not in gold)}
        # trace
        tfs = list((res / "traces").glob(f"*{iid}*.json"))
        seq = []; first_gold = first_edit = None; srs = []; reverts = 0; cats = {}
        gold_seen_lines = 0
        if tfs:
            d = json.load(open(tfs[0])); k = 0
            for s in d.get("steps", []):
                obs = str((s.get("observation") or {}).get("content", ""))
                for tc in s.get("tool_calls") or []:
                    k += 1
                    name = tc.get("function_name"); args = json.dumps(tc.get("arguments", {}))
                    cmd = str((tc.get("arguments") or {}).get("command", ""))
                    if first_gold is None and any(g in args or g in obs[:6000] for g in gold): first_gold = k
                    if name == "run_command" and ".git/sr.py" in cmd:
                        c = "edit"; srs.append(sr_outcome(obs))
                        if first_edit is None: first_edit = k
                    elif name == "run_command" and re.search(r"\bsed -i|>\s*(?!/tmp|/dev)[\w./-]+\.py|\.write\(|write_text\(", cmd):
                        c = "edit_other"
                        if first_edit is None: first_edit = k
                    elif name == "run_command" and re.search(r"git (checkout|restore|stash|reset)", cmd):
                        c = "revert"; reverts += 1
                    elif name == "run_command" and re.search(r"pytest|python3? -c|python3? /tmp|python3? -m|cat <<", cmd): c = "run_code"
                    elif name == "run_command": c = "shell_read"
                    elif name == "run_skill_script": c = "skill:" + str((tc.get("arguments") or {}).get("file_path", "")).split("/")[-1].replace(".py", "")
                    else: c = name
                    cats[c] = cats.get(c, 0) + 1
                    seq.append(c[:14])
        rec.update({"first_gold_call": first_gold, "first_edit_call": first_edit, "sr": srs, "reverts": reverts, "cats": cats, "last": seq[-6:], "n_seq": len(seq)})
        if not r.get("resolved") and r.get("agent_patch_size"):
            lg = list((res / "test_outputs").glob(f"*{iid}*"))
            out = lg[0].read_text(errors="replace") if lg else ""
            rec["E"] = [l.strip()[:150] for l in out.splitlines() if l.startswith("E  ")][:3]
            rec["summary"] = [l.strip() for l in out.splitlines() if re.search(r"\d+ (passed|failed|error)", l)][-1:]
        print("REC", run, json.dumps(rec))
'''


def main() -> None:
    runs = sys.argv[1:]
    user = os.environ.get('KAGGLE_USERNAME', 'janholoubek')
    meta = {
        'id': f'{user}/gemma-eval-causes', 'title': 'gemma-eval-causes', 'code_file': 'causes.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_internet': False,
        'kernel_sources': [f'{user}/gemma-eval-{r}' for r in runs],
        'dataset_sources': [], 'competition_sources': ['gemma-4-developer-agent'],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'causes.py').write_text(KERNEL.replace('__RUNS__', repr(runs)))
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
