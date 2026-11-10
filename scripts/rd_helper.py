"""Read helper the agent runs through run_command (installed as .git/rd.py).

    cd /workspace && python3 .git/rd.py path/to/file.py 120 180

Prints the numbered lines START..END (at most 80; the whole file if it has no more than 80).
Each call counts as a reading call, shared with locate.py, lookup.py and read.py (counter in
.git/reads). While no source file is edited, reading calls from NAG_AT on end with a reminder
and are refused after NO_EDIT_CAP; once the diff is non-empty reading is free again. A total
budget in .git/read_cap (0 = off) refuses regardless.
"""
import atexit
import subprocess
import sys
from pathlib import Path

MAX_LINES = 80
NAG_AT = 5       # from this reading call on, remind that nothing is edited yet
NO_EDIT_CAP = 8  # reading calls allowed while the diff is empty (0 = no limit)
GIT = Path(__file__).resolve().parent
SCRATCH = ('repro', 'debug', 'scratch', 'tmp', 'temp', 'test', 'check', 'verify')


def _num(name: str) -> int:
    try:
        return int((GIT / name).read_text().strip())
    except (OSError, ValueError):
        return 0


def edited() -> bool:
    """True once a non-test source file differs from HEAD (what the grader would score)."""
    try:
        out = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=GIT.parent,
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return True
    for line in out.splitlines():
        name = line[3:].split(' -> ')[-1].strip().strip('"')
        base = name.rsplit('/', 1)[-1]
        if base.startswith(('test_', 'conftest')) or base.endswith('_test.py') or '/tests/' in '/' + name:
            continue
        if line.startswith('??') and (not base.endswith('.py') or base.startswith(SCRATCH)):
            continue
        return True
    return False


def reading_call() -> bool:
    """Count one reading call; False when it is refused (total budget used, or too many with no edit)."""
    cap, used = _num('read_cap'), _num('reads')
    if cap and used >= cap:
        print(f'READING BUDGET USED ({used} of {cap} reading calls). Do not read more code. Edit now with '
              f'.git/sr.py using the lines you have already seen, then run check_patch.py and call submit_patch.')
        return False
    if (NAG_AT or NO_EDIT_CAP) and used + 1 >= (NAG_AT or NO_EDIT_CAP) and not edited():
        if NO_EDIT_CAP and used >= NO_EDIT_CAP:
            print(f'REFUSED: {used} reading calls and still no source file edited. An empty diff scores zero. '
                  f'Reading is blocked until you edit: make your best fix NOW with\n'
                  f"cd /workspace && python3 .git/sr.py path/to/file.py <<'EOF'\n<<<<<<< SEARCH\n<current lines>\n"
                  f'=======\n<new lines>\n>>>>>>> REPLACE\nEOF\n'
                  f'using the code you have already seen. After the edit you can read again and refine it.')
            return False
        more = NO_EDIT_CAP - used - 1
        left = '' if not NO_EDIT_CAP else (f' Only {more} more reading call(s) are allowed before an edit.' if more
                                           else ' This was the last reading call allowed before an edit.')
        atexit.register(print, f'\nNOTE: reading call {used + 1} and no source file edited yet. An empty diff scores '
                               f'zero; an imperfect edit often passes. Edit the most likely function now with '
                               f'.git/sr.py; you can refine it afterwards.{left}')
    try:
        (GIT / 'reads').write_text(str(used + 1))
    except OSError:
        pass
    if cap:
        print(f'[reading call {used + 1} of {cap}]')
    return True


def main() -> None:
    if len(sys.argv) not in (2, 3, 4):
        print('usage: python3 .git/rd.py path/to/file.py [START [END]]')
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f'{path}: no such file')
        sys.exit(1)
    if not reading_call():
        sys.exit(1)
    lines = path.read_text(encoding='utf-8', errors='replace').split('\n')
    start = max(1, int(sys.argv[2])) if len(sys.argv) > 2 else 1
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + MAX_LINES - 1
    end = min(len(lines), end, start + MAX_LINES - 1)
    print(f'{path} lines {start}-{end} of {len(lines)}:')
    print('\n'.join(f'{i:5} {lines[i - 1]}' for i in range(start, end + 1)))


if __name__ == '__main__':
    main()
