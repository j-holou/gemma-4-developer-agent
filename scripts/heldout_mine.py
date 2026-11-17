"""Mine candidate tasks for a held-out dev set from cloned repositories (no GitHub API needed).

    python scripts/heldout_mine.py REPOS_DIR OUT.jsonl [--since 2025-06-01]

A candidate is a non-merge commit on the default branch that changes 1-3 non-test .py files
(2-80 changed lines) and at least one test .py file. The commit message is the problem
statement (the competition uses PR title + body; a squash-merge message is the closest we
have offline). patch = non-test part of the diff, test_patch = test part, base = parent.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

TEST = re.compile(r'(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$')
SKIP_MSG = re.compile(r'pre-commit|dependabot|bump |release |^\[?(chore|ci|docs?|build)\b|typo|changelog|version', re.I)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True).stdout


def main():
    repos_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    since = sys.argv[sys.argv.index('--since') + 1] if '--since' in sys.argv else '2025-06-01'
    rows = []
    for repo in sorted(p for p in repos_dir.iterdir() if (p / '.git').exists()):
        url = git(repo, 'remote', 'get-url', 'origin').strip()
        slug = re.sub(r'^https://github.com/|\.git$', '', url)
        for line in git(repo, 'log', '--no-merges', f'--since={since}', '--format=%H %P %aI').splitlines():
            parts = line.split()
            if len(parts) != 3:
                continue
            sha, parent, date = parts
            msg = git(repo, 'log', '-1', '--format=%B', sha).strip()
            if SKIP_MSG.search(msg.split('\n', 1)[0]) or len(msg) < 25:
                continue
            stat = [l.split('\t') for l in git(repo, 'diff', '--numstat', parent, sha).splitlines()]
            files = [(f, int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0) for a, d, f in stat]
            src = [f for f in files if f[0].endswith('.py') and not TEST.search(f[0])
                   and not f[0].startswith(('docs/', 'doc/', 'examples/', 'scripts/', 'benchmarks/'))]
            tests = [f for f in files if TEST.search(f[0]) and f[0].endswith('.py')]
            other = [f for f in files if f not in src and f not in tests]
            changed = sum(a + d for _, a, d in src)
            if not (1 <= len(src) <= 3 and tests and 2 <= changed <= 80):
                continue
            if any(o[0].endswith('.py') for o in other):
                continue
            patch = git(repo, 'diff', parent, sha, '--', *[f for f, _, _ in src])
            test_patch = git(repo, 'diff', parent, sha, '--', *[f for f, _, _ in tests])
            name = slug.split('/')[1].replace('-', '_').lower()
            rows.append({'instance_id': f'{name}_{sha[:8]}', 'repo': slug, 'base_commit': parent,
                         'problem_statement': msg, 'hints_text': '', 'created_at': date,
                         'patch': patch, 'test_patch': test_patch, 'gold_lines': changed, 'gold_files': len(src)})
    out.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    import collections
    print(len(rows), collections.Counter(r['repo'] for r in rows))


if __name__ == '__main__':
    main()
