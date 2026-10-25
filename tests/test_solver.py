import tempfile
from pathlib import Path
import unittest
try: import z3
except ImportError: z3=None
from calc_fan import evaluate
from enumerate_combinations import enumerate_run, key_tuple
from audit_results import audit

@unittest.skipIf(z3 is None,'Install requirements.txt to test the solver')
class SolverTests(unittest.TestCase):
    def test_models_are_valid_inputs(self):
        from shape_solver import ShapeSolver
        for family in ('standard','seven_pairs','orphans','unconnected','knitted'):
            solver=ShapeSolver(family,timeout_ms=10000)
            for _ in range(5):
                status=solver.solver.check()
                self.assertEqual(status,z3.sat)
                model=solver.solver.model();data,key=solver.witness(model)
                result=evaluate(data)
                self.assertTrue(result['optimal'])
                solver.block_state(model)

    def test_resume_and_source_protection(self):
        with tempfile.TemporaryDirectory(prefix='mcr-test-') as tmp:
            output=Path(tmp)/'run'
            first=enumerate_run(output,families=('orphans',),max_models=3)
            self.assertFalse(first['complete'])
            self.assertEqual(audit(output)['witnesses'],first['combination_count'])
            with self.assertRaises(ValueError):enumerate_run(output,families=('orphans',),max_models=5)
            second=enumerate_run(output,families=('orphans',),max_models=6,resume=True)
            self.assertGreaterEqual(second['combination_count'],first['combination_count'])
            self.assertEqual(audit(output)['witnesses'],second['combination_count'])

    def test_canonical_search_is_separate(self):
        with tempfile.TemporaryDirectory(prefix='mcr-test-') as tmp:
            result=enumerate_run(Path(tmp)/'canonical',families=('orphans',),policy='canonical',max_models=3)
            self.assertEqual(result['policy'],'canonical')
            self.assertTrue(audit(Path(tmp)/'canonical')['passed'])

    def test_windless_rejections_ignore_only_irrelevant_winds(self):
        from shape_solver import ShapeSolver
        s=ShapeSolver('standard')
        s.solver.add(*(t<27 for t in s.tile),s.pair<27,s.opening==0)
        self.assertEqual(s.solver.check(),z3.sat)
        m=s.solver.model();values=s.state_values(m);data,_=s.witness(m)
        expected={key_tuple(i['key']) for i in evaluate(data)['optimal']}
        for seat in range(1,5):
            for wind in range(1,5):
                changed=dict(data,seat_wind=str(seat)+'z',round_wind=str(wind)+'z')
                self.assertEqual({key_tuple(i['key']) for i in evaluate(changed)['optimal']},expected)
        s.block_saved_state(values)
        s.solver.add(*(v==values[str(v)] for v in s.state_vars if str(v) not in ('seat','round')))
        self.assertEqual(s.solver.check(),z3.unsat)

    def test_local_ties_are_preserved_only_in_all_optimal(self):
        from shape_solver import ShapeSolver
        from tools.check_model_coverage import constraints
        data={'hand':'2m','win':'2m','method':'ron','melds':[
            {'kind':'chi','tiles':tiles} for tiles in ('123m','789m','123p','789p')]}
        result=evaluate(data)
        self.assertEqual(len(result['optimal']),2)
        for canonical in (False,True):
            s=ShapeSolver('standard',canonical=canonical)
            for interpretation in result['optimal']:
                s.solver.push();s.solver.add(*constraints(s,data,result,interpretation))
                status=s.solver.check();s.solver.pop()
                expected=(not canonical or interpretation['key']==result['canonical']['key'])
                self.assertEqual(status,z3.sat if expected else z3.unsat)

if __name__=='__main__':unittest.main()
