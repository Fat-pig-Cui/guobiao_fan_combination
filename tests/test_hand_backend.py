import itertools
import json
from pathlib import Path
import tempfile
import unittest

from calc_fan import evaluate
from hand_solver import iter_inputs
from reachability import validate


class HandBackendTests(unittest.TestCase):
    def test_first_candidates_are_valid_and_scoreable(self):
        for family in ('standard', 'seven_pairs', 'orphans', 'unconnected', 'knitted'):
            candidates = itertools.islice(
                iter_inputs(family, include_melds=False) if family == 'standard'
                else iter_inputs(family), 2)
            for data in candidates:
                validate(data)
                result = evaluate(data)
                self.assertIn('optimal', result)

    def test_python_feature_batch_matches_reference_shape(self):
        from tools.feature_batch import candidate_record, python_classify, RESULT
        data = next(iter_inputs('orphans'))
        record = candidate_record(data, 0)
        features, total, suits, passed = RESULT.unpack(python_classify(record, 0))
        self.assertGreater(total, 0)
        self.assertEqual(passed, 1)
        self.assertNotEqual(features, 0)
        self.assertEqual(suits, 7)

    def test_hand_census_checkpoint_and_resume(self):
        from tools.hand_census import run
        with tempfile.TemporaryDirectory(prefix='hand-backend-') as tmp:
            output = Path(tmp) / 'run'
            first = run(output, families=('orphans',), max_candidates=1,
                        checkpoint_every=1)
            self.assertEqual(first['candidates'], 1)
            second = run(output, families=('orphans',), max_candidates=2,
                         checkpoint_every=1, resume=True)
            self.assertGreaterEqual(second['candidates'], 2)
            rows = [json.loads(line) for line in (output / 'inventories.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), second['candidates'])


if __name__ == '__main__':
    unittest.main()
