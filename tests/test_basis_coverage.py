"""Deleting archived shards must preserve reporting without inventing checkpoints."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.basis_census import configuration, fingerprint
from tools.basis_coverage import verify_coverage


class RetainedCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        identity = {'backend': 'basis-cpu-v1', 'fingerprint': fingerprint(),
                    'config': configuration('orphans', list(range(34)), True, 0, None)}
        self.plan = {'source_sha256': fingerprint(), 'tiles': list(range(34)), 'include_melds': True,
                     'tasks': [{'id': 'orphans', 'family': 'orphans'}]}
        self.status = {'state': 'complete', 'workers': [], 'completed_tasks': 1, 'task_count': 1,
                       'tasks': {'orphans': {'identity': identity, 'cursor': 42,
                                            'scope_complete': True, 'termination': 'exhausted'}}}
        for name, value in [('tasks.json', self.plan), ('RUN_STATUS.json', self.status)]:
            (self.root / name).write_text(json.dumps(value))
        self.db = self.root / 'tasks' / 'orphans' / 'census.sqlite3'
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE metadata (name TEXT, value TEXT)')
            conn.execute('INSERT INTO metadata VALUES (?,?)', ('identity', json.dumps(identity)))
            conn.execute('CREATE TABLE progress (family TEXT, cursor INTEGER, complete INTEGER)')
            conn.execute('INSERT INTO progress VALUES (?, ?, ?)', ('orphans', 42, 1))

    def freeze_and_archive(self):
        audit = verify_coverage(self.root, self.status, self.plan, require_databases=True)
        (self.root / 'coverage-audit.json').write_text(json.dumps(audit))
        self.db.rename(self.root / 'archived.sqlite3')
        return audit

    def test_archive_independent_reporting_and_manifest_binding(self):
        before = self.freeze_and_archive()
        after = verify_coverage(self.root, self.status, self.plan)
        self.assertEqual(before['tasks'], after['tasks'])
        self.assertEqual(after['verification_mode'], 'retained_checkpoint_metadata')
        self.assertFalse(self.db.exists())
        with self.assertRaises(ValueError):
            verify_coverage(self.root, self.status, self.plan, require_databases=True)
        (self.root / 'tasks.json').write_text('{}')
        with self.assertRaises(AssertionError):
            verify_coverage(self.root, self.status, self.plan)

    def test_missing_audit_or_changed_cursor_is_rejected(self):
        self.freeze_and_archive()
        self.status['tasks']['orphans']['cursor'] += 1
        with self.assertRaises(AssertionError):
            verify_coverage(self.root, self.status, self.plan)
        (self.root / 'coverage-audit.json').unlink()
        with self.assertRaises(ValueError):
            verify_coverage(self.root, self.status, self.plan)

    def test_uncommitted_wal_or_incomplete_database_is_rejected(self):
        wal = Path(str(self.db) + '-wal')
        wal.write_bytes(b'not checkpointed')
        with self.assertRaises(AssertionError):
            verify_coverage(self.root, self.status, self.plan)
        wal.unlink()
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE progress SET complete=0')
        with self.assertRaises(AssertionError):
            verify_coverage(self.root, self.status, self.plan)


if __name__ == '__main__':
    unittest.main()
