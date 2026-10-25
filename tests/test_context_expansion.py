import unittest
import json
from pathlib import Path
import subprocess
import sys
import tempfile
try:
    import z3
except ImportError:
    z3 = None

from calc_fan import evaluate
from context_expansion import expand
from enumerate_combinations import key_tuple


class ContextExpansionTests(unittest.TestCase):
    def test_inventory_audit_detects_an_omitted_valid_vector(self):
        from context_expansion import source_hash
        from enumerate_combinations import fingerprint,write_json
        data={'hand':'2m','win':'2m','method':'ron','melds':[
            {'kind':'chi','tiles':t} for t in ('123m','789m','123p','789p')]}
        expanded=list(expand(data))
        for policy in ('all_optimal','canonical'):
            keys=set()
            for candidate,r in expanded:
                if r['eligible']:
                    choices=r['optimal'] if policy=='all_optimal' else [r['canonical']]
                    keys.update(key_tuple(i['key']) for i in choices)
            with tempfile.TemporaryDirectory(prefix='mcr-inventory-audit-') as tmp:
                root=Path(tmp);source=root/'source';band=root/'band'
                source.mkdir();band.mkdir()
                summary={'source_sha256':fingerprint(),'expansion_sha256':source_hash(),
                         'policy':policy,'complete':False}
                write_json(source/'summary.json',summary);write_json(band/'summary.json',summary)
                (band/'inventories.jsonl').write_text(json.dumps(
                    {'input':data,'contexts_evaluated':len(expanded)})+'\n')
                command=[sys.executable,str(Path(__file__).resolve().parents[1]/'tools/audit_inventory_expansions.py'),
                         '--source',str(source),'--output',str(root/'audit.json'),str(band)]
                for omit in (False,True):
                    selected=sorted(keys)[1:] if omit else sorted(keys)
                    (source/'combinations.jsonl').write_text(''.join(json.dumps({'key':k})+'\n' for k in selected))
                    result=subprocess.run(command,capture_output=True,text=True)
                    self.assertEqual(result.returncode,1 if omit else 0,result.stderr)
                    audit=json.loads((root/'audit.json').read_text())
                    self.assertEqual(audit['passed'],not omit)

    def test_all_sources_use_real_inventory(self):
        data={'hand':'23m456p789s55z','win':'1m','method':'ron',
              'melds':[{'kind':'pon','tiles':'111z'}],
              'context':{'draw_source':'kakan_ron','visible_before_win':'111m'}}
        cases=list(expand(data))
        self.assertEqual({d['method'] for d,r in cases},{'ron','tsumo'})
        self.assertEqual({d['context']['draw_source'] for d,r in cases},{'normal','kakan_ron'})
        self.assertTrue(all(d['context']['opening']=='none' for d,r in cases))
        expected=key_tuple(evaluate(data)['canonical']['key'])
        self.assertIn(expected,{key_tuple(r['canonical']['key']) for d,r in cases})

    @unittest.skipIf(z3 is None,'Install requirements.txt for solver coverage')
    def test_model_event_projections_are_in_expansion(self):
        from shape_solver import ShapeSolver
        for family in ('standard','seven_pairs','orphans','unconnected','knitted'):
            s=ShapeSolver(family)
            for _ in range(5):
                self.assertEqual(s.solver.check(),z3.sat)
                model=s.solver.model();data,_=s.witness(model);actual=evaluate(data)
                cases=list(expand(data))
                all_keys={key_tuple(i['key']) for d,r in cases for i in r['optimal']}
                canonical={key_tuple(r['canonical']['key']) for d,r in cases}
                self.assertTrue({key_tuple(i['key']) for i in actual['optimal']}<=all_keys)
                self.assertIn(key_tuple(actual['canonical']['key']),canonical)
                s.block_state(model)

    @unittest.skipIf(z3 is None,'Install requirements.txt for inventory blocking')
    def test_inventory_block_covers_decompositions_but_preserves_other_exposure_and_win(self):
        from collections import Counter
        from decompose import parse
        from shape_solver import ShapeSolver
        from context_expansion import block_inventory
        data={'hand':'111222333m5p','win':'5p','melds':[{'kind':'chi','tiles':'123m'}]}
        full=Counter(parse('111122223333m55p'))
        s=ShapeSolver('standard')
        s.solver.add(*(count==full[t] for t,count in enumerate(s.counts)))
        block_inventory(s,data)
        fixed=z3.Sum([z3.If(z3.Or(t==1,t==3,t==4,t==5),1,0) for t in s.typ])
        s.solver.push();s.solver.add(fixed==1,s.win==parse('5p')[0],
            z3.Or([z3.And(typ==1,tile==0) for typ,tile in zip(s.typ,s.tile)]))
        self.assertEqual(s.solver.check(),z3.unsat);s.solver.pop()
        s.solver.push();s.solver.add(fixed==0,s.win==parse('5p')[0])
        self.assertEqual(s.solver.check(),z3.sat);s.solver.pop()
        s.solver.push();s.solver.add(fixed==1,s.win==parse('1m')[0])
        self.assertEqual(s.solver.check(),z3.sat);s.solver.pop()


if __name__=='__main__':unittest.main()
