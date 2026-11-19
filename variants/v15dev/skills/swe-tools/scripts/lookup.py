"""Answer several code lookups in one call.

Usage: lookup.py --names "Console.print, soft_wrap, 'some error text'" [--file rich/console.py]

For each comma-separated name prints:
- every definition (def / class / NAME = ...) with its body, numbered, up to 40 lines;
- up to 6 places that use it (file:line: code).
A quoted entry is searched as literal text and shown with 2 lines of context.
Test files are skipped. --file restricts the search to one file or directory.
Output stays under ~4,500 characters so nothing is cut off.
"""
import argparse
import os
import re
from pathlib import Path

SKIP_DIRS = {'.git', 'tests', 'test', 'testing', 'build', 'dist', '__pycache__',
             '.venv', 'venv', 'node_modules', 'examples', 'benchmarks'}
BUDGET = 4500
BODY_LINES = 40
USES = 6


def workspace() -> Path:
    for cand in (Path('/workspace'), Path(os.environ.get('PWD', '.'))):
        if (cand / '.git').exists():
            return cand
    return Path(os.environ.get('PWD', '.'))


def source_files(root: Path, only: str | None):
    base = root / only if only else root
    if base.is_file():
        yield base
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.'))
        for name in sorted(filenames):
            if name.endswith('.py') and not name.startswith(('test_', 'conftest', '.')) \
                    and not name.endswith('_test.py'):
                yield Path(dirpath) / name


def block_end(lines: list[str], start: int) -> int:
    """Index after the indented block that starts at lines[start]."""
    indent = len(lines[start]) - len(lines[start].lstrip())
    i = start + 1
    # Skip a multi-line signature: continue until the line ending with ':'.
    while i < len(lines) and not lines[i - 1].rstrip().endswith(':') and i - start < 15:
        i += 1
    while i < len(lines):
        s = lines[i]
        if s.strip() and len(s) - len(s.lstrip()) <= indent and not s.lstrip().startswith((')', ']', '}')):
            break
        i += 1
    return i


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', required=True)
    ap.add_argument('--file')
    a = ap.parse_args()
    root = workspace()
    texts = {}
    for f in source_files(root, a.file):
        try:
            texts[f.relative_to(root)] = f.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            pass

    entries = [e.strip() for e in a.names.split(',') if e.strip()]
    per_entry = max(600, BUDGET // max(1, len(entries)))
    body_lines = BODY_LINES if len(entries) <= 2 else 25
    out = []
    for entry in entries:
        chunk = []
        literal = entry[0] in '\'"`' and entry[-1] == entry[0] and len(entry) > 2
        if literal:
            needle = entry[1:-1]
            chunk.append(f'== text {needle!r}')
            hits = 0
            for path, lines in texts.items():
                for i, line in enumerate(lines):
                    if needle in line:
                        hits += 1
                        if hits <= 5:
                            lo, hi = max(0, i - 2), min(len(lines), i + 3)
                            chunk.append(f'{path}:{i + 1}')
                            chunk += [f'{j + 1:>5} {lines[j]}' for j in range(lo, hi)]
            if hits > 5:
                chunk.append(f'... {hits - 5} more matches')
            if not hits:
                chunk.append('not found')
        else:
            name = entry.split('.')[-1]
            owner = entry.split('.')[-2] if '.' in entry else None
            def_re = re.compile(rf'^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b|^\s*{re.escape(name)}\s*(?::[^=]*)?=[^=].*[^,(]$')
            # Attribute access for Owner.name, else the bare word; prose in comments is skipped.
            use_re = re.compile(rf'\.{re.escape(name)}\b' if owner else rf'\b{re.escape(name)}\b')
            chunk.append(f'== {entry}')
            defs = uses = 0
            use_lines = []
            for path, lines in texts.items():
                for i, line in enumerate(lines):
                    if def_re.search(line):
                        if owner:  # only the definition inside the named class or module
                            if line.startswith((' ', '\t')):
                                cls = next((lines[k] for k in range(i, -1, -1)
                                            if lines[k].startswith('class ')), '')
                                if not re.match(rf'class\s+{re.escape(owner)}\b', cls):
                                    continue
                            elif path.stem != owner:
                                continue
                        defs += 1
                        if defs > 3:
                            continue
                        end = block_end(lines, i) if line.lstrip().startswith(('def', 'class', 'async')) else i + 1
                        shown = min(end, i + body_lines)
                        chunk.append(f'{path}:{i + 1}-{end} (definition)')
                        chunk += [f'{j + 1:>5} {lines[j]}' for j in range(i, shown)]
                        if shown < end:
                            chunk.append(f'      ... {end - shown} more lines (read_file {path} {shown + 1}-{end})')
                    elif use_re.search(line.split('#', 1)[0]) and not line.lstrip().startswith(('"', "'")):
                        uses += 1
                        if len(use_lines) < USES:
                            use_lines.append(f'  {path}:{i + 1}: {line.strip()[:110]}')
            if not defs:
                chunk.append('no definition found')
            if use_lines:  # keep uses near the top so a long body cannot push them out
                chunk[1:1] = [f'used in {uses} places, e.g.:'] + use_lines
        text = '\n'.join(chunk)
        if len(text) > per_entry:
            text = text[:per_entry] + '\n... (cut; narrow with --file or a more specific name)'
        out.append(text)
    print('\n\n'.join(out))






# --- sr.py installer (generated by scripts/build_edit_helper.py) ---
def _install_sr():
    import os as _os
    from pathlib import Path as _P
    _git = None
    for cand in (_P('/workspace'), _P(_os.environ.get('PWD', '.')), _P.cwd()):
        if (cand / '.git').is_dir():
            _git = cand / '.git'
            for _name, _text in {'sr.py': '"""Search/replace edit helper the agent runs through run_command (installed as .git/sr.py).\n\n    cd /workspace && python3 .git/sr.py path/to/file.py <<\'EOF\'\n    <<<<<<< SEARCH\n    exact current lines\n    =======\n    new lines\n    >>>>>>> REPLACE\n    EOF\n\nWhy: Gemma 4\'s tool-call format often loses an argument that follows a long code string,\nso edit_file(filepath, new_string, old_string) arrives without old_string. run_command has\na single argument and never breaks, so edits go through it.\n\nSeveral blocks may follow each other. A block whose SEARCH is empty creates the file (or\nappends to it). Matching is exact first, then line by line ignoring trailing spaces, then\nignoring indentation (NEW is re-indented by the same offset). A Python file that no longer\ncompiles is restored and the error is printed. Each applied block prints its new region.\n"""\nimport re\nimport sys\nfrom pathlib import Path\n\nBLOCK = re.compile(r\'<<<<<<< SEARCH\\n(.*?)^=======\\n(.*?)^>>>>>>> REPLACE\\s*$\', re.S | re.M)\n\n\ndef find_lines(lines, old, key):\n    want = [key(l) for l in old]\n    hits = [i for i in range(len(lines) - len(old) + 1) if [key(l) for l in lines[i:i + len(old)]] == want]\n    return hits\n\n\ndef indent(s):\n    return len(s) - len(s.lstrip(\' \'))\n\n\ndef apply(text, old, new):\n    """Return (new_text, first_line, n_new_lines) or raise ValueError with a reason."""\n    if not old.strip():\n        start = text.count(\'\\n\') + 1\n        return text + (\'\' if text.endswith(\'\\n\') or not text else \'\\n\') + new, start, new.count(\'\\n\') + 1\n    if text.count(old) == 1:\n        i = text.index(old)\n        return text[:i] + new + text[i + len(old):], text[:i].count(\'\\n\') + 1, new.count(\'\\n\') + 1\n    if text.count(old) > 1:\n        raise ValueError(f\'SEARCH text occurs {text.count(old)} times; add more surrounding lines to make it unique\')\n    lines = text.split(\'\\n\')\n    o = old.rstrip(\'\\n\').split(\'\\n\')\n    n = new.rstrip(\'\\n\').split(\'\\n\') if new.strip() else []\n    for key, shift in ((str.rstrip, False), (str.strip, True)):\n        hits = find_lines(lines, o, key)\n        if len(hits) == 1:\n            i = hits[0]\n            if shift:\n                d = indent(lines[i]) - indent(next(l for l in o if l.strip()))\n                n = [(\' \' * d + l) if d > 0 and l.strip() else l[min(-d, indent(l)):] if d < 0 else l for l in n]\n            return \'\\n\'.join(lines[:i] + n + lines[i + len(o):]), i + 1, len(n)\n        if len(hits) > 1:\n            raise ValueError(f\'SEARCH lines match at lines {[h + 1 for h in hits][:6]}; add more lines to make it unique\')\n    first = next((l.strip() for l in o if l.strip()), \'\')\n    near = [str(k + 1) for k, l in enumerate(lines) if first and l.strip() == first][:5]\n    raise ValueError(\'SEARCH text not found\' + (f\'; its first line is at line(s) {", ".join(near)}\' if near else \'\'))\n\n\ndef main() -> None:\n    if len(sys.argv) != 2:\n        print(\'usage: python3 .git/sr.py path/to/file.py <<\\\'EOF\\\' ... EOF  (SEARCH/REPLACE blocks on stdin)\')\n        sys.exit(2)\n    path = Path(sys.argv[1])\n    spec = sys.stdin.read()\n    blocks = BLOCK.findall(spec)\n    if not blocks:\n        print(\'No SEARCH/REPLACE block found. Format:\\n<<<<<<< SEARCH\\n<old lines>\\n=======\\n<new lines>\\n>>>>>>> REPLACE\')\n        sys.exit(1)\n    original = path.read_text() if path.exists() else \'\'\n    text, shown = original, []\n    for k, (old, new) in enumerate(blocks, 1):\n        try:\n            text, start, count = apply(text, old, new)\n        except ValueError as e:\n            print(f\'Block {k} NOT applied: {e}. Nothing was changed.\')\n            sys.exit(1)\n        shown.append((start, count))\n    if path.suffix == \'.py\':\n        try:\n            compile(text, str(path), \'exec\')\n        except SyntaxError as e:\n            print(f\'NOT applied: the result has a syntax error at line {e.lineno}: {e.msg}. Nothing was changed.\')\n            sys.exit(1)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text(text)\n    lines = text.split(\'\\n\')\n    for start, count in shown:\n        a, b = max(1, start - 2), min(len(lines), start + count + 1)\n        print(f\'Applied to {path}, now lines {a}-{b}:\')\n        print(\'\\n\'.join(f\'{i:5} {lines[i - 1]}\' for i in range(a, b + 1)))\n\n\nif __name__ == \'__main__\':\n    main()\n', 'rd.py': '"""Read helper the agent runs through run_command (installed as .git/rd.py).\n\n    cd /workspace && python3 .git/rd.py path/to/file.py 120 180\n\nPrints the numbered lines START..END (at most 80; the whole file if it has no more than 80).\nEach call counts toward the task\'s reading budget, shared with locate.py and lookup.py and\nstored in .git/reads. Once the budget in .git/read_cap is used up it refuses and says to edit.\n"""\nimport sys\nfrom pathlib import Path\n\nMAX_LINES = 80\nGIT = Path(__file__).resolve().parent\n\n\ndef reading_call() -> bool:\n    """Count one reading call; False once the budget is used up."""\n    try:\n        cap = int((GIT / \'read_cap\').read_text().strip())\n    except (OSError, ValueError):\n        cap = 0\n    try:\n        used = int((GIT / \'reads\').read_text().strip())\n    except (OSError, ValueError):\n        used = 0\n    if cap and used >= cap:\n        print(f\'READING BUDGET USED ({used} of {cap} reading calls). Do not read more code. Edit now with \'\n              f\'.git/sr.py using the lines you have already seen, then run check_patch.py and call submit_patch.\')\n        return False\n    (GIT / \'reads\').write_text(str(used + 1))\n    if cap:\n        print(f\'[reading call {used + 1} of {cap}]\')\n    return True\n\n\ndef main() -> None:\n    if len(sys.argv) not in (2, 3, 4):\n        print(\'usage: python3 .git/rd.py path/to/file.py [START [END]]\')\n        sys.exit(2)\n    path = Path(sys.argv[1])\n    if not path.is_file():\n        print(f\'{path}: no such file\')\n        sys.exit(1)\n    if not reading_call():\n        sys.exit(1)\n    lines = path.read_text(encoding=\'utf-8\', errors=\'replace\').split(\'\\n\')\n    start = max(1, int(sys.argv[2])) if len(sys.argv) > 2 else 1\n    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + MAX_LINES - 1\n    end = min(len(lines), end, start + MAX_LINES - 1)\n    print(f\'{path} lines {start}-{end} of {len(lines)}:\')\n    print(\'\\n\'.join(f\'{i:5} {lines[i - 1]}\' for i in range(start, end + 1)))\n\n\nif __name__ == \'__main__\':\n    main()\n', 'read_cap': '0'}.items():
                try:
                    if _name != 'read_cap' or not (_git / _name).exists():
                        (_git / _name).write_text(_text)
                except OSError:
                    pass
            break


_install_sr()
# --- end sr.py installer ---


if __name__ == '__main__':
    main()
