"""Cross-language comparisons and transaction/coverage tests for basis census."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from basis_backend import batch, build, write_known
from calc_fan import evaluate
from context_expansion import expand
from decompose import KNITTED, compact, parse
from fast_runtime import install
from native_backend import MAGIC, build as old_build, generate_batch, physical_key, read_batch, decode
from tools.basis_census import run
from tools.basis_run import prepare, merge, supervise
from tools.native_census import dump


def tags(rows):
    return {(dump(r['key']),r['policy'],int(r['closed']),r['method'],r['total']) for r in rows}


def reference(physical):
    rows=set()
    for data in physical:
        for _,result in expand(data,equivalent_winds=True):
            if result['total']<8:continue
            for policy,choices in (('all_optimal',result['optimal']),('canonical',[result['canonical']])):
                rows.update((dump(i['key']),policy,int(result['closed']),result['method'],result['total']) for i in choices)
    return rows


def saved(path):
    with sqlite3.connect((Path(path)/'census.sqlite3').resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as conn:
        return set(conn.execute('SELECT key,policy,closed,method,total FROM observations'))


class BasisBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build();install()

    def assert_witnesses(self,rows):
        for row in rows:
            scored=evaluate(row['input'])
            choices=scored['optimal'] if row['policy']=='all_optimal' else [scored['canonical']]
            self.assertEqual(row['total'],scored['total'],row)
            self.assertEqual(row['closed'],scored['closed'],row)
            self.assertIn(row['key'],[i['key'] for i in choices],row)

    def test_full_restricted_standard_sets(self):
        for domain in ('1234m','123m1z','12345z'):
            with self.subTest(domain=domain),tempfile.TemporaryDirectory() as tmp:
                trace=Path(tmp)/'basis-physical.bin'
                info,rows=batch(Path(tmp)/'basis',tiles=parse(domain),max_bases=0,physical_output=trace)
                self.assertTrue(info['complete'])
                self.assertEqual(info['bases'],info['decompositions'])
                path=Path(tmp)/'reference.bin'
                generate_batch(old_build(),path,tiles=parse(domain),max_records=0)
                physical={p for _,p in read_batch(path)}
                self.assertEqual({p for _,p in read_batch(trace)},physical)
                self.assertEqual(tags(rows),reference(decode(p) for p in physical))

    def test_special_families_include_competing_decompositions(self):
        cases=[('orphans',tuple(range(34))),('unconnected',tuple(range(34))),
               ('seven_pairs',parse('1234m1z')),
               ('knitted',tuple(sorted(set(KNITTED[0])|{27,28})))]
        for family,tiles in cases:
            with self.subTest(family=family),tempfile.TemporaryDirectory() as tmp:
                trace=Path(tmp)/'basis-physical.bin'
                info,rows=batch(Path(tmp)/'basis',family=family,tiles=tiles,max_bases=0,physical_output=trace)
                self.assertTrue(info['complete'])
                path=Path(tmp)/'reference.bin'
                generate_batch(old_build(),path,family=family,tiles=tiles,max_records=0)
                physical={p for _,p in read_batch(path)}
                self.assertEqual({p for _,p in read_batch(trace)},physical)
                self.assertEqual(tags(rows),reference(decode(p) for p in physical))

    def test_context_witnesses_and_full_domain_prefix_samples(self):
        # Different suits, honors, many fixed states; all emitted contexts are
        # independently rescored, including maxima across competing families.
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inputs.bin';records=[]
            for family,left in [('standard',v) for v in (0,20,48,160,450,900,1400)]+[('seven_pairs',0),('knitted',0)]:
                part=Path(tmp)/'part.bin'
                generate_batch(old_build(),part,family=family,left_begin=left,
                               left_end=left+1 if family=='standard' else None,max_records=24)
                records.extend(list(read_batch(part)))
            path.write_bytes(MAGIC+b''.join(i.to_bytes(8,'little')+p for i,p in records))
            _,rows=batch(Path(tmp)/'scored',input_path=path)
            self.assertEqual(tags(rows),reference(decode(p) for _,p in records))
            self.assert_witnesses(rows)

    def test_targeted_rule_and_canonical_regressions(self):
        cases=[
            {'hand':'2m','win':'2m','melds':[{'kind':'chi','tiles':t} for t in ('123m','789m','123p','789p')]},
            {'hand':'1112345678999m','win':'5m','melds':[]},
            {'hand':'1123455678999m','win':'1m','melds':[]},
            {'hand':'1122334455667m','win':'7m','melds':[]},
            {'hand':'1111222333444m','win':'2m','melds':[]},
            {'hand':'19m19p19s1234567z','win':'1m','melds':[]},
            {'hand':'1112447m258p369s','win':'3m','melds':[]},
            {'hand':'2z','win':'2z','melds':[{'kind':'ankan','tiles':t} for t in ('1111z','5555z','6666z','7777z')]},
            {'hand':'23m55p','win':'1m','melds':[{'kind':'pon','tiles':'111m'},{'kind':'chi','tiles':'456p'},{'kind':'chi','tiles':'789s'}]},
            {'hand':'23m456p789s55z','win':'1m','melds':[{'kind':'pon','tiles':'111z'}]},
            {'hand':'5p','win':'5p','melds':[{'kind':'chi','tiles':'456m'}]*4},
            {'hand':'45p77s','win':'6p','melds':[{'kind':'ankan','tiles':'1111m'},{'kind':'ankan','tiles':'9999m'},{'kind':'minkan','tiles':'2222p'}]},
        ]
        for data in cases:
            with self.subTest(data=data),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'input.bin';path.write_bytes(MAGIC+bytes(8)+physical_key(data))
                _,rows=batch(Path(tmp)/'scored',input_path=path,all_results=True)
                # Verify every raw-context maximum, also below the eight-fan threshold.
                self.assert_witnesses(rows)
                self.assertEqual(tags(r for r in rows if r['total']>=8),reference([data]))

    def test_all_results_keeps_sub_eight_best_explanations(self):
        # The ordinary editor profile still treats 8 fan as the winning
        # threshold, but the census backend must be able to retain a valid
        # lower best explanation for the separate all-fan run.
        data={'hand':'67s11z','win':'8s',
              'melds':[{'kind':'chi','tiles':t} for t in ('123m','456m','345p')],
              'method':'ron'}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input.bin'
            path.write_bytes(MAGIC+bytes(8)+physical_key(data))
            _,rows=batch(Path(tmp)/'scored',input_path=path,all_results=True)
            self.assertTrue(any(row['total']<8 for row in rows))
            self.assert_witnesses(rows)

    def test_known_observations_skip_without_reducing_work_or_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);info,rows=batch(root/'first',tiles=parse('1234m'),max_bases=0)
            known=root/'known.bin'
            write_known(known,[(r['key'],r['policy'],r['closed'],r['method']) for r in rows])
            again,empty=batch(root/'second',tiles=parse('1234m'),max_bases=0,known=known)
            self.assertEqual(empty,[])
            self.assertEqual(info['physical'],again['physical'])
            self.assertEqual(info['contexts'],again['contexts'])

    def test_resume_and_no_physical_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            full=run(root/'full',tiles=parse('1234m'),batch_bases=3)
            part=run(root/'resumed',tiles=parse('1234m'),max_bases=5,batch_bases=2)
            self.assertFalse(part['scope_complete'])
            done=run(root/'resumed',tiles=parse('1234m'),batch_bases=2,resume=True)
            self.assertTrue(done['scope_complete'])
            self.assertEqual(saved(root/'full'),saved(root/'resumed'))
            self.assertEqual(full['bases'],done['bases'])
            self.assertEqual(full['physical'],done['physical'])
            with sqlite3.connect(root/'resumed/census.sqlite3') as c:
                self.assertNotIn(('physical',),c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
            with self.assertRaisesRegex(ValueError,'mismatch'):
                run(root/'resumed',tiles=parse('123m1z'),resume=True)

    def test_pause_and_failed_transaction_preserve_committed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pause=root/'pause.json';pause.write_text('{}')
            s=run(root/'paused',tiles=parse('1234m'),pause_file=pause)
            self.assertEqual(s['bases'],0)
            self.assertEqual(s['termination'],'interrupted')
            # A deliberate SQLite trigger forces rollback midway through a
            # nonempty batch. No cursor may advance without its observations.
            with sqlite3.connect(root/'paused/census.sqlite3') as c:
                c.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON observations BEGIN SELECT RAISE(ABORT,'injected failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                run(root/'paused',tiles=parse('1234m'),resume=True,batch_bases=1)
            with sqlite3.connect(root/'paused/census.sqlite3') as c:
                self.assertEqual(c.execute('SELECT cursor FROM progress').fetchone()[0],-1)
                self.assertEqual(c.execute('SELECT count(*) FROM observations').fetchone()[0],0)
                c.execute('DROP TRIGGER fail_batch')
            done=run(root/'paused',tiles=parse('1234m'),resume=True)
            self.assertTrue(done['scope_complete'])

    def test_exact_shard_merge_and_missing_coverage_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=prepare(root/'queue',tiles=parse('1234m'),rows_per_task=4)
            for spec in plan['tasks']:
                run(root/'queue/tasks'/spec['id'],family=spec['family'],tiles=parse('1234m'),
                    left_begin=spec['left_begin'],left_end=spec['left_end'])
            result=merge(root/'queue',plan,root/'merged')
            self.assertTrue(result['scope_complete']);self.assertFalse(result['complete'])
            expected=set()
            for family in ('standard','seven_pairs','orphans','unconnected','knitted'):
                directory=root/('single-'+family);run(directory,family=family,tiles=parse('1234m'));expected|=saved(directory)
            self.assertEqual(saved(root/'merged'),expected)
            broken=dict(plan,tasks=plan['tasks'][:-1])
            with self.assertRaisesRegex(ValueError,'tail'):
                merge(root/'queue',broken,root/'invalid')
            from tools.native_audit import audit
            self.assertTrue(audit(root/'merged')['passed'])

    def test_controller_completes_small_domain_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';prepare(root,tiles=parse('1234m'),rows_per_task=4)
            supervise(root,workers=2,slice_seconds=60)
            state=json.loads((root/'RUN_STATUS.json').read_text())
            self.assertEqual(state['state'],'scope_complete')
            self.assertEqual(state['workers'],[])
            audit=json.loads((Path(state['final_directory'])/'witness-audit.json').read_text())
            self.assertTrue(audit['passed'])

    def test_eight_task_slots_and_cooperative_pause(self):
        from tools import basis_run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';prepare(root,tiles=parse('1234m'),rows_per_task=4)
            spawned=[];original_status=basis_run.status
            class Process:
                def __init__(self,command,**kwargs):
                    self.command=command;self.pid=10000+len(spawned);spawned.append(self)
                def poll(self):return 3 if self.pause_file.exists() else None
                def wait(self):return 3
            def observe(output,plan,state,active,workers,*args,**kwargs):
                data=original_status(output,plan,state,active,workers,*args,**kwargs)
                if len(active)==8:(output/'stop.json').write_text('{}')
                return data
            with patch.object(basis_run.subprocess,'Popen',Process),patch.object(basis_run,'status',observe),patch.object(basis_run.time,'sleep',lambda _:None):
                supervise(root,workers=8,slice_seconds=300)
            self.assertEqual(len(spawned),8)
            self.assertEqual(len({p.command[p.command.index('--output')+1] for p in spawned}),8)
            self.assertTrue(all(p.pause_file.exists() for p in spawned))
            state=json.loads((root/'RUN_STATUS.json').read_text())
            self.assertEqual(state['state'],'paused');self.assertEqual(state['workers'],[])


if __name__=='__main__':unittest.main()
