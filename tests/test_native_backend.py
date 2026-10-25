from collections import Counter
import itertools
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from context_expansion import expand
from decompose import Group, KNITTED, compact, parse
from hand_solver import _group_geometries, knitted_inputs, seven_pairs_inputs
from native_backend import build, decode, generate_batch, physical_key, read_batch
from reachability import validate
from tools.direct_shapes import standard_states
from tools.native_census import run


def observations(data, reduced):
    result = set()
    count = 0
    for candidate, scored in expand(data, equivalent_winds=reduced):
        count += 1
        for policy, choices in (('optimal', scored['optimal']), ('canonical', [scored['canonical']])):
            result.update((json.dumps(i['key']), policy, scored['closed'], scored['method'], scored['total'])
                          for i in choices)
    return result, count


class NativeBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executable = build()

    def batch_keys(self, directory, family, tiles=range(34), include_melds=True, batch_size=1000000):
        after = -1
        keys = set()
        ranks = []
        while True:
            path = Path(directory)/'batch.bin'
            info = generate_batch(self.executable, path, family=family, tiles=tiles,
                                  include_melds=include_melds, after=after, max_records=batch_size)
            records = list(read_batch(path))
            self.assertEqual(info['records'], len(records))
            for rank, identity in records:
                data = decode(identity)
                validate(data)
                self.assertEqual(physical_key(data), identity)
                keys.add(identity)
                ranks.append(rank)
            if info['complete']:
                break
            self.assertGreater(info['cursor'], after)
            after = info['cursor']
        self.assertEqual(ranks, sorted(set(ranks)))
        return keys

    def test_standard_matches_independent_full_small_domains(self):
        # Repeated chows, triplet-plus-chow overlap, open declarations and kans.
        for tiles in ((0,1,2,3), (0,1,2,27), (27,28,29,30,31)):
            for opened in (False, True):
                expected = set()
                for hand, win, fixed in standard_states(tiles, open_states=opened):
                    expected.add(physical_key({'hand': compact(hand), 'win': compact((win,)),
                                              'melds': [{'kind': g.kind, 'tiles': compact(g.tiles)}
                                                        for g in fixed]}))
                with tempfile.TemporaryDirectory() as tmp:
                    actual = self.batch_keys(tmp, 'standard', tiles, opened)
                self.assertEqual(actual, expected, (tiles, opened))

    def test_native_resume_inside_a_winning_tile_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = self.batch_keys(tmp, 'standard', (0,1,2,3), True)
            actual = self.batch_keys(tmp, 'standard', (0,1,2,3), True, batch_size=7)
            self.assertEqual(actual, expected)

    def test_special_families_match_independent_generators(self):
        from hand_solver import orphans_inputs, unconnected_inputs
        with tempfile.TemporaryDirectory() as tmp:
            for family, generator in (('orphans', orphans_inputs), ('unconnected', unconnected_inputs)):
                expected = {physical_key(d) for d in generator()}
                self.assertEqual(self.batch_keys(tmp, family), expected)
            # Seven pairs with four identical tiles (two pairs of one kind).
            tiles = (0,1,2,3,27)
            expected = set()
            for choices in itertools.combinations_with_replacement(tiles, 7):
                if max(Counter(choices).values()) > 2:
                    continue
                full = [t for t in choices for _ in range(2)]
                for w in set(choices):
                    hand = list(full); hand.remove(w)
                    expected.add(physical_key({'hand': compact(hand), 'win': compact((w,)), 'melds': []}))
            self.assertTrue(expected)
            self.assertEqual(self.batch_keys(tmp, 'seven_pairs', tiles, batch_size=11), expected)
            self.assertEqual(self.batch_keys(tmp, 'seven_pairs', tiles), expected)
            # A restricted knitted domain still includes wins from its backbone.
            tiles = tuple(sorted(set(KNITTED[0]) | {27,28}))
            allowed = set(tiles)
            expected = {physical_key(d) for d in knitted_inputs()
                        if set(parse(d['hand'])+parse(d['win'])
                               +tuple(t for m in d['melds'] for t in parse(m['tiles']))) <= allowed}
            self.assertEqual(self.batch_keys(tmp, 'knitted', tiles, batch_size=113), expected)

    def test_reference_generator_regressions(self):
        expected = (Group('sequence',0),)*4
        self.assertIn(expected, itertools.islice(_group_geometries(prefix=0), 200000))
        first = next(seven_pairs_inputs())
        self.assertIn(4, Counter(parse(first['hand'])+parse(first['win'])).values())
        first_knitted = list(itertools.islice(knitted_inputs(), 14))
        self.assertTrue(any(parse(d['win'])[0] in KNITTED[0] for d in first_knitted))

    def test_wind_equivalence_preserves_both_policies_and_labels(self):
        samples = [
            {'hand':'111222333z123m5p','win':'5p','melds':[]},
            {'hand':'1112223334445z','win':'5z','melds':[]},
            {'hand':'123m456p789s1z','win':'1z','melds':[{'kind':'ankan','tiles':'2222z'}]},
            {'hand':'123m456p789s1z','win':'1z','melds':[{'kind':'pon','tiles':'222z'}]},
            {'hand':'112233m445566p7z','win':'7z','melds':[]},
        ]
        saved = 0
        for data in samples:
            full, count_full = observations(data, False)
            reduced, count_reduced = observations(data, True)
            self.assertEqual(full, reduced)
            saved += count_full-count_reduced
        self.assertGreater(saved, 0)

    def test_transactional_resume_matches_uninterrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'one', Path(tmp)/'resume'
            opts = dict(families=('orphans',), batch_size=19)
            expected = run(a, **opts)
            partial = run(b, max_candidates=23, **opts)
            self.assertFalse(partial['scope_complete'])
            actual = run(b, resume=True, **opts)
            for field in ('candidates', 'contexts_evaluated', 'combination_count', 'canonical_count',
                          'observation_count', 'fan_distribution', 'partitions'):
                self.assertEqual(actual[field], expected[field], field)
            for table, order in (('physical','identity'), ('observations','key,policy,closed,method')):
                with sqlite3.connect(a/'census.sqlite3') as ca, sqlite3.connect(b/'census.sqlite3') as cb:
                    self.assertEqual(ca.execute(f'SELECT * FROM {table} ORDER BY {order}').fetchall(),
                                     cb.execute(f'SELECT * FROM {table} ORDER BY {order}').fetchall())
            self.assertFalse(actual['complete'])  # one complete family is not all five
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                run(b, resume=True, include_melds=False, **opts)
            with self.assertRaisesRegex(ValueError, 'Output exists'):
                run(b, **opts)

    def test_failed_batch_rolls_back_cursor_physical_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'failure'
            def fail(data, **kwargs):
                raise RuntimeError('simulated scoring failure')
            with patch('tools.native_census.expand', fail):
                with self.assertRaisesRegex(RuntimeError,'simulated'):
                    run(output,families=('orphans',),batch_size=7)
            with sqlite3.connect(output/'census.sqlite3') as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM physical').fetchone()[0],0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0],0)
                self.assertEqual(conn.execute('SELECT cursor,complete FROM progress').fetchone(),(-1,0))
            self.assertEqual(json.loads((output/'summary.json').read_text())['termination'],'error')
            actual = run(output,families=('orphans',),batch_size=31,resume=True)
            self.assertEqual(actual['candidates'],169)
            with patch('tools.native_census.fingerprint',lambda:{'changed':'source'}):
                with self.assertRaisesRegex(ValueError,'mismatch'):
                    run(output,families=('orphans',),resume=True)

    def test_merge_requires_complete_standard_shard_coverage(self):
        from tools.native_merge import merge
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = dict(families=('standard',),tiles=(0,1,2,3),batch_size=256)
            run(root/'left',left_begin=0,left_end=5,**options)
            run(root/'right',left_begin=5,**options)
            single = run(root/'single',**options)
            partial = merge([root/'left'],root/'partial')
            self.assertFalse(partial['families_complete']['standard'])
            united = merge([root/'left',root/'right'],root/'union')
            self.assertTrue(united['families_complete']['standard'])
            self.assertFalse(united['complete'])
            self.assertEqual(united['combination_count'],single['combination_count'])
            with sqlite3.connect(root/'union'/'census.sqlite3') as a, \
                 sqlite3.connect(root/'single'/'census.sqlite3') as b:
                sql = 'SELECT key,policy,closed,method,total FROM observations ORDER BY key,policy,closed,method'
                self.assertEqual(a.execute(sql).fetchall(),b.execute(sql).fetchall())


if __name__ == '__main__':
    unittest.main()
