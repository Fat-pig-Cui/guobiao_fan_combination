import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.native_census import run
from tools.native_parallel import controller_lock, split_standard
from tools.native_census import fingerprint
from tools.native_local_run import _supervise

ROOT = Path(__file__).resolve().parents[1]


def table(path, name):
    with sqlite3.connect(path/'census.sqlite3') as conn:
        return set(conn.execute('SELECT * FROM '+name))


class NativeParallelTests(unittest.TestCase):
    def test_controller_lock_excludes_a_second_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'controller.lock'
            with controller_lock(path):
                with self.assertRaises(OSError):
                    with controller_lock(path):
                        self.fail('Concurrent lock acquired')
            with controller_lock(path):
                pass

    def test_split_preserves_existing_work_and_exhaustive_union(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = dict(families=('standard',),tiles=(0,1,2,3),batch_size=64)
            run(root/'standard',max_candidates=23,**opts)
            before = table(root/'standard','physical')
            original_metadata = table(root/'standard','metadata')
            plan = split_standard(root,rows_per_task=4)
            self.assertEqual(plan['cursor_row'],0)
            specs = [s for s in plan['tasks'] if s['family'] == 'standard']
            self.assertGreater(len(specs),1)
            self.assertEqual(table(root/specs[0]['directory'],'physical'),before)
            self.assertEqual(table(root/'standard','metadata'),original_metadata)
            physical,observations = set(),set()
            intervals = []
            for spec in specs:
                destination = root/spec['directory']
                result = run(destination,left_begin=spec['left_begin'],left_end=spec['left_end'],
                             resume=(destination/'census.sqlite3').exists(),**opts)
                self.assertTrue(result['scope_complete'])
                physical.update(table(destination,'physical'))
                with sqlite3.connect(destination/'census.sqlite3') as conn:
                    observations.update(conn.execute('SELECT key,policy,closed,method,total FROM observations'))
                intervals.append((spec['left_begin'],spec['left_end']))
            self.assertEqual(intervals[0][0],0)
            self.assertEqual(intervals[-1][1],plan['pair_rows'])
            self.assertTrue(all(a[1] == b[0] for a,b in zip(intervals,intervals[1:])))
            run(root/'reference',**opts)
            self.assertEqual(physical,table(root/'reference','physical'))
            with sqlite3.connect(root/'reference'/'census.sqlite3') as conn:
                expected = set(conn.execute('SELECT key,policy,closed,method,total FROM observations'))
            self.assertEqual(observations,expected)
            self.assertEqual(table(root/'standard','physical'),before)
            self.assertEqual(split_standard(root),plan)  # idempotent; no recopy/restart

    def test_pause_file_worker_can_resume_without_console_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root/'worker'
            request = root/'pause.json'
            command = [sys.executable,str(ROOT/'tools/native_worker.py'),'--pause-file',str(request),'--',
                       '--families','standard','--tiles','1234m','--batch-size','16','--output',str(output)]
            with (root/'log').open('w') as log:
                process = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic()+10
                    while not (output/'summary.json').exists() and process.poll() is None:
                        if time.monotonic() > deadline:
                            self.fail('Worker did not commit a checkpoint')
                        time.sleep(0.01)
                    request.write_text('{}',encoding='utf-8')
                    self.assertEqual(process.wait(timeout=10),3)
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
            partial = json.loads((output/'summary.json').read_text())
            self.assertFalse(partial['scope_complete'])
            self.assertEqual(partial['termination'],'interrupted')
            result = subprocess.run([sys.executable,str(ROOT/'tools/native_worker.py'),
                                     '--pause-file',str(root/'new-pause.json'),'--',
                                     *command[command.index('--')+1:],'--resume'],
                                    capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            final = json.loads((output/'summary.json').read_text())
            self.assertTrue(final['scope_complete'])
            self.assertEqual(final['candidates'],870)

    def test_scheduler_fills_eight_distinct_slots_and_cooperatively_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(root/'standard',families=('standard',),tiles=(0,1,2,3),max_candidates=7)
            split_standard(root,rows_per_task=2)
            (root/'run.json').write_text(json.dumps({'source_sha256':fingerprint()}))
            launched = []
            class Process:
                def __init__(self,command,**kwargs):
                    self.command = command
                    self.pid = 10000+len(launched)
                    launched.append(self)
                def poll(self):
                    return 3 if getattr(self,'pause_file',root/'absent').exists() else None
                def wait(self):
                    return 3
            states = []
            def status(output,state,active,reason=None,**extra):
                states.append((state,len(active)))
                if len(active) == 8:
                    (root/'stop.json').write_text('{}')
            with patch('tools.native_local_run.subprocess.Popen',Process), \
                 patch('tools.native_local_run.save_status',status), \
                 patch('tools.native_local_run.time.sleep',lambda _:None):
                _supervise(root,workers=8,slice_seconds=10)
            self.assertEqual(len(launched),8)
            outputs = [p.command[p.command.index('--output')+1] for p in launched]
            self.assertEqual(len(set(outputs)),8)
            self.assertTrue(all('native_worker.py' in ' '.join(p.command) for p in launched))
            self.assertTrue(all(p.pause_file.exists() for p in launched))
            self.assertEqual(states[-1],('paused',0))


if __name__ == '__main__':
    unittest.main()
