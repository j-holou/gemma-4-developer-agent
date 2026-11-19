"""Rank the functions most likely to need the fix, and the files that hold them.

Usage: locate.py --query "<issue text or key terms>" [--top 6]

Splits every non-test Python file into definitions (functions, methods, class headers)
and scores each with BM25 over identifier sub-words from the query (snake_case and
CamelCase are split), plus bonuses for exact identifiers, dotted names, quoted strings
and file names the query mentions. Prints the best files, each with its best
definitions and their line ranges, ready for reading.
"""
import argparse
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

STOP = set('''
a an and are as at be but by can could do does for from has have how i if in into is it its
may not of on or should so than that the then there these this to use used using was we when
where which while will with would you your error issue bug fix fixes fixed expected actual
behavior behaviour version python true false none self return raise class def import value
values type types default example code test tests case get set new also like just only one
same file line add adds added support make makes work works now see https http www com github
issue issues pull pr thanks please cls args kwargs str int bool list dict any optional
'''.split())
SKIP_DIRS = {'.git', 'tests', 'test', 'testing', 'docs', 'build', 'dist', '__pycache__', '.venv',
             'venv', 'node_modules', 'scripts', 'benchmarks', 'examples', 'site-packages'}
DEF_RE = re.compile(r'^(\s*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)')
WORD_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def workspace() -> Path:
    for cand in (Path('/workspace'), Path(os.environ.get('PWD', '.'))):
        if (cand / '.git').exists():
            return cand
    return Path(os.environ.get('PWD', '.'))


def stem(w: str) -> str:
    for suf in ('ing', 'ed', 'es', 's'):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def subwords(ident: str):
    out = []
    for part in ident.split('_'):
        out += re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+', part)
    return [stem(w.lower()) for w in out if len(w) > 1]


def clean_query(query: str) -> str:
    """Drop URLs and PR-template boilerplate (checklists, instructions)."""
    query = re.sub(r'https?://\S+', ' ', query)
    keep = []
    for line in query.splitlines():
        if re.match(r'\s*[-*] \[[ xX]\]', line) or 'Please describe your changes' in line:
            continue
        if re.match(r'\s*#+\s*(Type of changes|Checklist|Description)\s*$', line):
            continue
        keep.append(line)
    return '\n'.join(keep)


def query_terms(query: str):
    query = clean_query(query)
    words = Counter()
    idents = Counter()
    for ident in WORD_RE.findall(query):
        code_like = '_' in ident or any(c.isupper() for c in ident[1:])
        if code_like and len(ident) > 3:
            idents[ident] += 1
        for w in subwords(ident):
            if w not in STOP and len(w) > 2:
                words[w] += 2 if code_like else 1
    plain = {stem(w.lower()) for w in WORD_RE.findall(query) if len(w) > 3 and w.lower() not in STOP}
    quoted = [q.strip() for q in re.findall(r'["\'`]([^"\'`\n]{3,80})["\'`]', query)]
    paths = [Path(p).stem for p in re.findall(r'[\w/]+\.py\b', query)]
    return words, idents, quoted, paths, plain


def chunks(text):
    """[(start, end, name, kind)] 1-based inclusive; a class keeps only its header lines."""
    lines = text.split('\n')
    defs = []
    for i, l in enumerate(lines):
        m = DEF_RE.match(l)
        if m:
            defs.append((i, len(m.group(1).expandtabs()), m.group(3), m.group(2)))
    out = []
    for k, (i, ind, name, kind) in enumerate(defs):
        end = len(lines)
        for j, ind2, _, _ in defs[k + 1:]:
            if ind2 <= ind or kind == 'class':
                end = j
                break
        out.append((i + 1, end, name, kind))
    if not defs or defs[0][0] > 0:
        out.append((1, defs[0][0] if defs else len(lines), '<module>', 'module'))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--query', required=True)
    ap.add_argument('--top', type=int, default=6)
    a = ap.parse_args()
    root = workspace()
    words, idents, quoted, paths, plain = query_terms(a.query)
    if not words and not quoted:
        print('No searchable terms in query.')
        return
    docs = []  # (file, start, end, name, Counter of sub-words, raw text)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            if not fn.endswith('.py') or fn.startswith(('test_', 'conftest', '.')):
                continue
            f = Path(dirpath) / fn
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            lines = text.split('\n')
            for s, e, name, kind in chunks(text):
                body = '\n'.join(lines[s - 1:e])
                tf = Counter(w for ident in WORD_RE.findall(body) for w in subwords(ident))
                docs.append((f, s, e, name, tf, body))
    if not docs:
        print('No Python files found.')
        return
    n = len(docs)
    df = Counter()
    for d in docs:
        for w in words:
            if d[4][w]:
                df[w] += 1
    avg = sum(sum(d[4].values()) for d in docs) / n
    scored = []
    for f, s, e, name, tf, body in docs:
        length = sum(tf.values()) or 1
        sc = 0.0
        for w, qw in words.items():
            c = tf[w]
            if not c:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            sc += qw * idf * c * 2.2 / (c + 1.2 * (0.25 + 0.75 * length / avg))
        for ident in idents:
            if ident == name:
                sc += 6
            elif ident in body:
                sc += 1.5
        if stem(name.lower()) in plain and not any(ident == name for ident in idents):
            sc += 4
        for q in quoted:
            if q in body:
                sc += 4
        rel = str(f.relative_to(root))
        if any(p.lower() == f.stem.lower() for p in paths):
            sc += 4
        elif stem(f.stem.lower().strip('_')) in plain:
            sc += 2
        if rel.startswith('docs_src/'):
            sc *= 0.6
        if sc > 0:
            scored.append((sc, rel, s, e, name))
    scored.sort(reverse=True)
    by_file = defaultdict(list)
    for sc, rel, s, e, name in scored:
        by_file[rel].append((sc, s, e, name))
    # file score: best definition plus a share of the next ones
    fscore = {rel: v[0][0] + 0.3 * sum(x[0] for x in v[1:4]) for rel, v in by_file.items()}
    ranked = sorted(fscore, key=fscore.get, reverse=True)[: a.top]
    if not ranked:
        print('No matches. Try different terms (symbol names, error text).')
        return
    for rel in ranked:
        print(f'{rel}  (score {fscore[rel]:.1f})')
        for sc, s, e, name in sorted(by_file[rel][:4], key=lambda x: x[1]):
            print(f'    {s}: {name}  (lines {s}-{e})')
    print('\nRead the listed line ranges with read_file before editing; scores are lexical, not certain.')


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
