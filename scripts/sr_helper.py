"""Search/replace edit helper the agent runs through run_command (installed as .git/sr.py).

    cd /workspace && python3 .git/sr.py path/to/file.py <<'EOF'
    <<<<<<< SEARCH
    exact current lines
    =======
    new lines
    >>>>>>> REPLACE
    EOF

Why: Gemma 4's tool-call format often loses an argument that follows a long code string,
so edit_file(filepath, new_string, old_string) arrives without old_string. run_command has
a single argument and never breaks, so edits go through it.

Several blocks may follow each other. A block whose SEARCH is empty creates the file (or
appends to it). Matching is exact first, then line by line ignoring trailing spaces, then
ignoring indentation (NEW is re-indented by the same offset). A Python file that no longer
compiles is restored and the error is printed. Each applied block prints its new region.
"""
import re
import sys
from pathlib import Path

BLOCK = re.compile(r'<<<<<<< SEARCH\n(.*?)^=======\n(.*?)^>>>>>>> REPLACE\s*$', re.S | re.M)


def find_lines(lines, old, key):
    want = [key(l) for l in old]
    hits = [i for i in range(len(lines) - len(old) + 1) if [key(l) for l in lines[i:i + len(old)]] == want]
    return hits


def indent(s):
    return len(s) - len(s.lstrip(' '))


def apply(text, old, new):
    """Return (new_text, first_line, n_new_lines) or raise ValueError with a reason."""
    if not old.strip():
        start = text.count('\n') + 1
        return text + ('' if text.endswith('\n') or not text else '\n') + new, start, new.count('\n') + 1
    if text.count(old) == 1:
        i = text.index(old)
        return text[:i] + new + text[i + len(old):], text[:i].count('\n') + 1, new.count('\n') + 1
    if text.count(old) > 1:
        raise ValueError(f'SEARCH text occurs {text.count(old)} times; add more surrounding lines to make it unique')
    lines = text.split('\n')
    o = old.rstrip('\n').split('\n')
    n = new.rstrip('\n').split('\n') if new.strip() else []
    for key, shift in ((str.rstrip, False), (str.strip, True)):
        hits = find_lines(lines, o, key)
        if len(hits) == 1:
            i = hits[0]
            if shift:
                d = indent(lines[i]) - indent(next(l for l in o if l.strip()))
                n = [(' ' * d + l) if d > 0 and l.strip() else l[min(-d, indent(l)):] if d < 0 else l for l in n]
            return '\n'.join(lines[:i] + n + lines[i + len(o):]), i + 1, len(n)
        if len(hits) > 1:
            raise ValueError(f'SEARCH lines match at lines {[h + 1 for h in hits][:6]}; add more lines to make it unique')
    first = next((l.strip() for l in o if l.strip()), '')
    near = [str(k + 1) for k, l in enumerate(lines) if first and l.strip() == first][:5]
    raise ValueError('SEARCH text not found' + (f'; its first line is at line(s) {", ".join(near)}' if near else ''))


def main() -> None:
    if len(sys.argv) != 2:
        print('usage: python3 .git/sr.py path/to/file.py <<\'EOF\' ... EOF  (SEARCH/REPLACE blocks on stdin)')
        sys.exit(2)
    path = Path(sys.argv[1])
    spec = sys.stdin.read()
    blocks = BLOCK.findall(spec)
    if not blocks:
        print('No SEARCH/REPLACE block found. Format:\n<<<<<<< SEARCH\n<old lines>\n=======\n<new lines>\n>>>>>>> REPLACE')
        sys.exit(1)
    original = path.read_text() if path.exists() else ''
    text, shown = original, []
    for k, (old, new) in enumerate(blocks, 1):
        try:
            text, start, count = apply(text, old, new)
        except ValueError as e:
            print(f'Block {k} NOT applied: {e}. Nothing was changed.')
            sys.exit(1)
        shown.append((start, count))
    if path.suffix == '.py':
        try:
            compile(text, str(path), 'exec')
        except SyntaxError as e:
            print(f'NOT applied: the result has a syntax error at line {e.lineno}: {e.msg}. Nothing was changed.')
            sys.exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    lines = text.split('\n')
    for start, count in shown:
        a, b = max(1, start - 2), min(len(lines), start + count + 1)
        print(f'Applied to {path}, now lines {a}-{b}:')
        print('\n'.join(f'{i:5} {lines[i - 1]}' for i in range(a, b + 1)))
    print('The diff is no longer empty. Make any other edits the issue needs now, then run check_patch.py '
          'and call submit_patch.')


if __name__ == '__main__':
    main()
