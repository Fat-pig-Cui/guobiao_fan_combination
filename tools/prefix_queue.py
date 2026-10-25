"""Create and dynamically consume an exact ``tile_0`` prefix queue.

Tasks are claimed by atomically renaming a directory from ``pending`` to
``running``.  This works on POSIX and Windows without a third-party queue or
shared database.  A worker may be started multiple times on the same queue;
each task is claimed by at most one live worker.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def task_name(prefix):
    return f'tile0-{prefix:02d}'


def init_queue(args):
    root = Path(args.output)
    if root.exists() and any(root.iterdir()):
        raise SystemExit('queue output must be a new or empty directory')
    for name in ('pending', 'running', 'done', 'failed', 'results'):
        (root / name).mkdir(parents=True, exist_ok=True)
    metadata = {
        'schema_version': 1,
        'partition': 'standard.tile_0 exact prefixes 0..33',
        'prefix_count': 34,
        'created_by': 'tools/prefix_queue.py',
    }
    (root / 'queue.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8')
    for prefix in range(34):
        (root / 'pending' / task_name(prefix)).mkdir()
    print(json.dumps({'queue': str(root.resolve()), 'tasks': 34}, ensure_ascii=False))


def claim(root, excluded=()):
    pending = root / 'pending'
    running = root / 'running'
    for source in sorted(pending.iterdir()):
        if not source.is_dir():
            continue
        if source.name in excluded:
            continue
        destination = running / source.name
        try:
            # Directory rename is atomic when source and destination share a
            # filesystem.  A FileExistsError means another worker won.
            source.rename(destination)
            return destination
        except (FileNotFoundError, FileExistsError, PermissionError):
            continue
    return None


def run_worker(args):
    root = Path(args.queue)
    queue_file = root / 'queue.json'
    if not queue_file.exists():
        raise SystemExit('queue.json is missing; run init first')
    (root / 'running').mkdir(exist_ok=True)
    (root / 'done').mkdir(exist_ok=True)
    (root / 'failed').mkdir(exist_ok=True)
    (root / 'results').mkdir(exist_ok=True)
    worker_script = Path(__file__).with_name('band_census_prefix_worker.py')
    deferred = set()
    while True:
        task = claim(root, deferred)
        if task is None:
            return
        prefix = int(task.name.rsplit('-', 1)[1])
        output = root / 'results' / task.name
        command = [sys.executable, str(worker_script), '--prefix', str(prefix),
                   '--output', str(output), '--min-fan', str(args.min_fan),
                   '--policy', args.policy, '--resume']
        if args.max_fan is not None:
            command.extend(['--max-fan', str(args.max_fan)])
        if args.timeout_ms:
            command.extend(['--timeout-ms', str(args.timeout_ms)])
        if args.seconds:
            command.extend(['--seconds', str(args.seconds)])
        if args.no_cache:
            command.append('--no-cache')
        if args.no_z3_tuning:
            command.append('--no-z3-tuning')
        if args.no_compact_blocking:
            command.append('--no-compact-blocking')
        # Keep the queue log beside the task marker.  The prefix worker treats
        # its output directory as an initialized checkpoint and therefore must
        # not see the scheduler log before it creates ``prefix.json``.
        log = task / 'worker.log'
        output.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'event': 'start', 'prefix': prefix,
                                     'time': time.time()}, ensure_ascii=False) + '\n')
            stream.flush()
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
            stream.write(json.dumps({'event': 'exit', 'prefix': prefix,
                                     'returncode': result.returncode,
                                     'time': time.time()}, ensure_ascii=False) + '\n')
        if result.returncode == 0:
            task.rename(root / 'done' / task.name)
        elif result.returncode == 3:
            # Incomplete or time-limited work remains retryable.  Its output
            # checkpoint is retained, so a later worker resumes it.
            task.rename(root / 'pending' / task.name)
            deferred.add(task.name)
            if args.once:
                return
        else:
            task.rename(root / 'failed' / task.name)
            if args.once:
                return


def requeue_running(args):
    root = Path(args.queue)
    running = root / 'running'
    pending = root / 'pending'
    if not running.exists():
        raise SystemExit('queue has no running directory')
    moved = 0
    for task in sorted(running.iterdir()):
        if not task.is_dir():
            continue
        destination = pending / task.name
        if destination.exists():
            raise SystemExit('pending task already exists: ' + task.name)
        task.rename(destination)
        moved += 1
    print(json.dumps({'requeued': moved}, ensure_ascii=False))


def queue_status(args):
    root = Path(args.queue)
    result = {}
    for name in ('pending', 'running', 'done', 'failed'):
        directory = root / name
        result[name] = len([p for p in directory.iterdir() if p.is_dir()]) if directory.exists() else 0
    result['complete_tasks'] = result['done'] == 34
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('init')
    create.add_argument('--output', required=True)
    create.set_defaults(func=init_queue)

    worker = sub.add_parser('worker')
    worker.add_argument('--queue', required=True)
    worker.add_argument('--min-fan', type=int, required=True)
    worker.add_argument('--max-fan', type=int)
    worker.add_argument('--policy', choices=('all_optimal', 'canonical'), default='all_optimal')
    worker.add_argument('--timeout-ms', type=int, default=0)
    worker.add_argument('--seconds', type=int, default=0)
    worker.add_argument('--no-cache', action='store_true')
    worker.add_argument('--no-z3-tuning', action='store_true')
    worker.add_argument('--no-compact-blocking', action='store_true')
    worker.add_argument('--once', action='store_true',
                        help='Stop after the first incomplete or failed task')
    worker.set_defaults(func=run_worker)
    requeue = sub.add_parser('requeue-running',
                             help='Requeue tasks left in running after verifying no worker is alive')
    requeue.add_argument('--queue', required=True)
    requeue.set_defaults(func=requeue_running)
    status = sub.add_parser('status')
    status.add_argument('--queue', required=True)
    status.set_defaults(func=queue_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
