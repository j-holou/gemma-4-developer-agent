---
name: swe-tools
description: Fast helpers for fixing an issue in /workspace. locate.py ranks the source files to edit, lookup.py shows definitions and uses of several names in one call, install_edit.py installs the .git/sr.py search/replace edit helper, find_tests.py finds existing tests, check_patch.py reviews the diff before submit_patch.
---

# swe-tools

Run each script with `run_skill_script(skill_name="swe-tools", file_path="scripts/<name>.py", args={...})`.
They read the repository in /workspace and print a short plain-text report.

## scripts/locate.py
Ranks the non-test source files and functions most likely to need the fix.
- `args={"query": "<issue title + key names, error text, quoted strings>"}`
- optional `"top": 6`
Prints each file with its score and, under it, its best-matching functions with line ranges
(`120: parse_header  (lines 120-158)`). Read those ranges next.

## scripts/lookup.py
One call instead of many greps. For each comma-separated name prints its definitions with
numbered code, and where it is used.
- `args={"names": "Console.print, soft_wrap, 'exact error text'"}`
- `Class.method` finds the method inside that class; a quoted entry is searched as literal text.
- optional `"file": "rich/console.py"` limits the search to one file or directory.

## scripts/install_edit.py
Writes the edit helper to /workspace/.git/sr.py. Every other script here installs it too, so
this is only needed if `python3 .git/sr.py` reports that the file is missing.
- `args={}`

## scripts/find_tests.py
Finds existing tests that exercise a file or symbol and prints a ready pytest command.
- `args={"target": "rich/table.py"}` or `args={"target": "SymbolName"}`

## scripts/check_patch.py
Run before every submit_patch. Shows the diff and flags: syntax errors, edits to test or
config files (the grader discards them), stray untracked files, and an empty patch.
- `args={"clean": "true"}` also deletes scratch files (repro.py, debug_*.py, ...) left in the repo.
Prints `OK: ready for submit_patch` when nothing is wrong.
