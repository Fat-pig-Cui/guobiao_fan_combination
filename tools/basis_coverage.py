"""Verify task coverage, retaining a bound metadata audit before archiving shards.

The saved audit records a historical verification of committed checkpoints. It
cannot resume tasks or replace independent scoring of the merged witnesses.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from enumerate_combinations import write_json
from tools.basis_census import configuration, fingerprint


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_coverage(root, status, plan, *, require_databases=False):
    root = Path(root)
    saved = None
    rows = {}
    used_saved = False
    source = fingerprint()
    assert status['state'] == 'complete' and not status['workers']
    assert status['completed_tasks'] == status['task_count'] == len(plan['tasks'])
    assert plan['source_sha256'] == source
    for task in plan['tasks']:
        task_id = task['id']
        state = status['tasks'][task_id]
        assert state['scope_complete'] and state['termination'] == 'exhausted'
        expected = {'backend': 'basis-cpu-v1', 'fingerprint': source,
                    'config': configuration(task['family'], plan['tiles'], plan['include_melds'],
                                            task.get('left_begin', 0), task.get('left_end'),
                                            plan.get('min_fan', 8), plan.get('max_fan'))}
        assert state['identity'] == expected
        path = root / 'tasks' / task_id / 'census.sqlite3'
        if path.exists():
            # An uncheckpointed WAL must not be silently ignored by immutable reads.
            wal = Path(str(path) + '-wal')
            assert not wal.exists() or wal.stat().st_size == 0, path
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as conn:
                identity = json.loads(conn.execute("SELECT value FROM metadata WHERE name='identity'").fetchone()[0])
                progress = [list(row) for row in conn.execute('SELECT family,cursor,complete FROM progress')]
            row = {'identity': identity, 'progress': progress, 'database_bytes': path.stat().st_size}
        else:
            if require_databases:
                raise ValueError('Original checkpoint required: ' + str(path))
            if saved is None:
                audit_path = root / 'coverage-audit.json'
                if not audit_path.exists():
                    raise ValueError('Missing task database and retained coverage audit: ' + str(path))
                saved = json.loads(audit_path.read_text(encoding='utf-8'))
                assert saved['schema'] == 'basis-coverage-audit-v1' and saved['passed']
                assert saved['source_sha256'] == source
                assert saved['manifest_sha256'] == sha256(root / 'tasks.json')
                assert saved['status_sha256'] == sha256(root / 'RUN_STATUS.json')
                assert set(saved['tasks']) == {t['id'] for t in plan['tasks']}
            row = saved['tasks'][task_id]
            used_saved = True
        assert row['identity'] == state['identity']
        assert row['progress'] == [[task['family'], state['cursor'], 1]]
        rows[task_id] = row
    return {'schema': 'basis-coverage-audit-v1', 'passed': True,
            'verified_at': datetime.now(timezone.utc).isoformat(),
            'verification_mode': 'retained_checkpoint_metadata' if used_saved else 'original_databases',
            'source_sha256': source, 'manifest_sha256': sha256(root / 'tasks.json'),
            'status_sha256': sha256(root / 'RUN_STATUS.json'), 'tasks': rows,
            'boundary': 'Committed task metadata verified before archiving; not a resumable checkpoint or a fresh witness audit'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    root = args.run.resolve()
    destination = root / 'coverage-audit.json'
    if destination.exists():
        raise ValueError('Coverage audit already exists; preserve the original verification record')
    result = verify_coverage(root, json.loads((root / 'RUN_STATUS.json').read_text()),
                             json.loads((root / 'tasks.json').read_text()), require_databases=True)
    write_json(destination, result)
    print(json.dumps({'passed': result['passed'], 'tasks': len(result['tasks']), 'audit': str(destination)}))


if __name__ == '__main__':
    main()
