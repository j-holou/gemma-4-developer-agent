"""Push an evaluation run of submission/ to Kaggle's 4x L4 GPUs.

    python scripts/push_eval.py --name baseline --tasks eval/dev24.txt
    kaggle kernels status <user>/gemma-eval-baseline
    kaggle kernels output <user>/gemma-eval-baseline -p results/baseline

Embeds every file under submission/ and the task ids into scripts/kaggle_eval.py
and pushes it as a private script kernel. GPU time on these machines counts
double against the weekly quota.
"""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {'.yaml', '.yml', '.md', '.txt', '.py', '.json'}


def kaggle_username() -> str:
    if os.environ.get('KAGGLE_USERNAME'):
        return os.environ['KAGGLE_USERNAME']
    out = subprocess.run(['kaggle', 'config', 'view'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.strip().startswith('- username:'):
            return line.split(':', 1)[1].strip()
    raise SystemExit('set KAGGLE_USERNAME')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='run name, used in the kernel slug')
    ap.add_argument('--tasks', type=Path, default=ROOT / 'eval/dev24.txt')
    ap.add_argument('--submission', type=Path, default=ROOT / 'submission')
    ap.add_argument('--adapter-kernel', help='kernel whose output holds adapters/<name>/ (e.g. user/gemma-lora-train)')
    ap.add_argument('--adapter-name', default='edit_early')
    ap.add_argument('--oracle-hint', action='store_true', help='tell the agent where the reference patch changes code')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    files = {}
    for path in sorted(a.submission.rglob('*')):
        if path.is_file():
            if path.suffix not in TEXT_SUFFIXES:
                raise SystemExit(f'{path}: only text files can be embedded (no adapters yet)')
            files[str(path.relative_to(a.submission))] = path.read_text(encoding='utf-8')
    task_ids = [t for t in a.tasks.read_text().split() if t]
    if a.adapter_kernel:  # the root agent uses the adapter; the files are copied in on Kaggle
        files['agent.yaml'] = files['agent.yaml'].rstrip('\n') + f'\nadapter: {a.adapter_name}\n'

    source = (ROOT / 'scripts/kaggle_eval.py').read_text(encoding='utf-8')
    source = source.replace('SUBMISSION_FILES: dict[str, str] = {}', f'SUBMISSION_FILES: dict[str, str] = {files!r}', 1)
    source = source.replace('TASK_IDS: list[str] = []', f'TASK_IDS: list[str] = {task_ids!r}', 1)
    source = source.replace('# __SCORER_ENV__', (ROOT / 'scripts/scorer_env.py').read_text(encoding='utf-8'), 1)
    source = source.replace("RUN_NAME = ''", f'RUN_NAME = {a.name!r}', 1)
    if a.oracle_hint:
        source = source.replace('ORACLE_HINT = False', 'ORACLE_HINT = True', 1)
    if a.adapter_kernel:
        source = source.replace("ADAPTER = ''", f'ADAPTER = {a.adapter_name!r}', 1)

    slug = f'gemma-eval-{a.name}'
    user = kaggle_username()
    meta = {
        'id': f'{user}/{slug}',
        'title': slug,
        'code_file': 'kaggle_eval.py',
        'language': 'python',
        'kernel_type': 'script',
        'is_private': True,
        'enable_gpu': True,
        'enable_internet': False,
        'machine_shape': 'NvidiaL4',
        # The wheelhouse is built for Python 3.12; the default image is 3.13.
        # This is the image the official "Getting Started" notebook is pinned to.
        'docker_image': 'gcr.io/kaggle-private-byod/python@sha256:'
                        '37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461',
        'docker_image_pinning_type': 'original',
        # The last two hold the scorer-like sandbox's test packages and Python 3.13 (scorer_env.py).
        'dataset_sources': ['metric/gemma-4-developer-agent-wheelhouse',
                            'zbigniewkirchner/gemma-4-agent-local-eval-wheels',
                            'zbigniewkirchner/gemma-4-agent-local-eval-pythons'],
        'competition_sources': ['gemma-4-developer-agent'],
        'kernel_sources': [a.adapter_kernel] if a.adapter_kernel else [],
        'model_sources': ['google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2'],
    }
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'kaggle_eval.py').write_text(source, encoding='utf-8')
        (Path(tmp) / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
        print(f'{meta["id"]}: {len(files)} submission files, {len(task_ids)} tasks')
        if a.dry_run:
            compile(source, 'kaggle_eval.py', 'exec')
            return
        subprocess.run(['kaggle', 'kernels', 'push', '-p', tmp], check=True)


if __name__ == '__main__':
    main()
