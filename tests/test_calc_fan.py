import unittest
from itertools import permutations
from calc_fan import evaluate, small_plans
from decompose import Group, parse, shapes, waits, compact, KNITTED
from reachability import validate
from rules import FANS

def case(hand,win,ms=(),method='ron',**kwargs):
    return dict(hand=hand,win=win,melds=[dict(kind=k,tiles=t) for k,t in ms],method=method,**kwargs)

def scored(data):
    r=evaluate(data)
    return r,dict(r['canonical']['key'])

class EvaluatorTests(unittest.TestCase):
    def test_catalogue(self):
        self.assertEqual(len(FANS),86)
        self.assertEqual(len({8058 if f in (8059,8060) else f for f in FANS}),84)

    def test_silver_examples(self):
        examples=[
            case('22p778899m89p','7p',[('minkan','5555z')],'tsumo'),
            case('22p778899m89p','7p',[('minkan','1111z')],'tsumo'),
            case('22p778899m89p','7p',[('minkan','2222z')],'tsumo'),
            case('11122m44556689p','7p'),
            case('22789m89p','7p',[('chi','789m'),('chi','789p')],'tsumo'),
            case('123p45m22p','6m',[('chi','123p'),('minkan','9999m')],'tsumo'),
            case('44556p88m','6p',[('minkan','1111m'),('pon','111p')]),
            case('11122999m45p','6p',[('minkan','8888p')],'tsumo'),
            case('22m45789p','6p',[('ankan','1111m'),('chi','456p')],'tsumo'),
            case('223344m24p88p','3p',[('minkan','6666p')],'tsumo')]
        for data in examples:
            with self.subTest(data=data):
                r,k=scored(data)
                self.assertEqual(r['total'],8)
                self.assertEqual(sum(n for f,n in k.items() if FANS[f]['value']==2),1)
                self.assertEqual(sum(n for f,n in k.items() if FANS[f]['value']==1),6)

    def test_gold_examples(self):
        hands=['22m44556689p','22m11223389p','22778899m89p','22456789m89p',
               '22789m12389p','22999m78899p','22999m45689p','22999m12389p','22678999m68p']
        for hand in hands:
            r,k=scored(case(hand,'7p',[('minkan','1111m')],'tsumo'))
            self.assertEqual(r['total'],8)
            self.assertTrue(all(FANS[f]['value']==1 for f in k))

    def test_double_wind_does_not_double_subtract(self):
        d=case('999p23m55s','1m',[('pon','111z'),('pon','111p')],
               seat_wind='1z',round_wind='1z')
        r,k=scored(d)
        self.assertEqual(k[8061],1); self.assertEqual(k[8062],1)
        self.assertEqual(k[8074],2)

    def test_two_double_pungs(self):
        r,k=scored(case('5s','5s',[('pon','111m'),('pon','111p'),('pon','999m'),('pon','999p')]))
        self.assertEqual(k[8066],2)

    def test_all_equal_small_fan_explanations(self):
        r=evaluate(case('2m','2m',[('chi','123m'),('chi','789m'),('chi','123p'),('chi','789p')]))
        self.assertEqual(len(r['optimal']),2)
        self.assertEqual(dict(r['canonical']['key'])[8071],2)

    def test_small_forest(self):
        groups=tuple(Group('chi',t) for t in (0,6,9,15))
        plans=small_plans(groups)
        best=[dict(p) for p in plans if sum(dict(p).values())==3]
        self.assertIn({8071:2,8073:1},best)
        self.assertIn({8071:1,8073:2},best)
        self.assertLessEqual(max(sum(dict(p).values()) for p in plans),3)

    def test_high_chow_support(self):
        groups=tuple(Group('chi',t) for t in (0,3,6,9))
        plans=small_plans(groups,(0,1,2),(8072,8073))
        self.assertEqual(max(sum(dict(p).values()) for p in plans),1)

    def test_four_identical_chows(self):
        r,k=scored(case('5p','5p',[('chi','456m')]*4,'tsumo'))
        self.assertIn(8013,k); self.assertNotIn(8065,k); self.assertNotIn(8070,k)

    def test_dragon_partial_terminal_exclusion(self):
        r,k=scored(case('1p','1p',[('pon','555z'),('pon','666z'),('pon','777z'),('pon','999m')]))
        self.assertIn(8001,k); self.assertNotIn(8058,k)
        # Mixed terminals globally excludes terminal pungs in this exact hand.
        self.assertIn(8017,k); self.assertNotIn(8074,k)
        r,k=scored(case('2p','2p',[('pon','555z'),('pon','666z'),('pon','777z'),('pon','999m')]))
        self.assertEqual(k[8074],1)

    def test_three_kans_three_concealed(self):
        r,k=scored(case('45p77s','6p',[('ankan','1111m'),('ankan','9999m'),('ankan','2222p')]))
        self.assertIn(8016,k); self.assertIn(8032,k)
        r,k=scored(case('45p77s','6p',[('ankan','1111m'),('ankan','9999m'),('minkan','2222p')]))
        self.assertIn(8016,k);self.assertNotIn(8052,k);self.assertIn(8067,k)
        r,k=scored(case('5s','5s',[('ankan','1111m'),('ankan','9999m'),('minkan','2222p'),('minkan','8888p')]))
        self.assertIn(8004,k);self.assertNotIn(8052,k);self.assertIn(8067,k)

    def test_four_concealed_kan_high_fan_witness(self):
        r,k=scored(case('2z','2z',[("ankan",t) for t in ('1111z','5555z','6666z','7777z')],
                        'tsumo',seat_wind='1z',round_wind='1z',
                        context={'draw_source':'kan_replacement','wall_empty':True}))
        self.assertEqual(r['total'],324)
        self.assertEqual(set(k),{8001,8004,8010,8011,8043,8045,8061,8062})

    def test_ron_triplet_not_concealed(self):
        r,k=scored(case('111999m222p33p44s','3p'))
        self.assertIn(8032,k); self.assertNotIn(8011,k)
        r,k=scored(case('111999m222p33p44s','3p',method='tsumo'))
        self.assertIn(8011,k)

    def test_pair_quad_and_family_competition(self):
        r,k=scored(case('111122p334455m6s','6s'))
        self.assertIn(8018,k); self.assertEqual(k[8065],1)
        r=evaluate(case('1122334455667m','7m'))
        self.assertTrue(r['eligible']); self.assertGreaterEqual(r['total'],88)

    def test_knitted_all_permutations(self):
        for bone in KNITTED:
            full=tuple(sorted(bone+parse('111z22p')))
            d=case(compact(full[:-1]),compact(full[-1:]))
            r,k=scored(d)
            self.assertIn(8034,k)
        bone=KNITTED[0]
        r,k=scored(case(compact(bone+parse('2p')), '2p',[('chi','456m')]))
        self.assertIn(8034,k); self.assertIn(8064,k)

    def test_knitted_wait_uses_its_remaining_meld(self):
        r,k=scored(case('1112447m258p369s','3m',seat_wind='1z',round_wind='1z',
                        context={'wall_empty':True,'visible_before_win':'333m'}))
        self.assertIn(8034,k)
        self.assertIn(8079,k)
        self.assertNotIn(8078,k)

    def test_unconnected_and_orphans(self):
        r,k=scored(case('147m258p369s1234z','5z'))
        self.assertIn(8033,k); self.assertIn(8034,k)
        r,k=scored(case('147m258p3s123456z','7z'))
        self.assertIn(8019,k); self.assertNotIn(8033,k)
        r,k=scored(case('19m19p19s1234567z','1m'))
        self.assertIn(8006,k); self.assertNotIn(8063,k)

    def test_nine_gates_strict_before_win(self):
        r,k=scored(case('1112345678999m','5m'))
        self.assertIn(8003,k)
        r,k=scored(case('1123455678999m','1m'))
        self.assertNotIn(8003,k)

    def test_full_formal_waits(self):
        hand=parse('1111222333444m')
        formal=waits(tuple(sorted(hand)),(),True)
        physical=waits(tuple(sorted(hand)),())
        self.assertIn(0,formal); self.assertNotIn(0,physical)
        r,k=scored(case('22p12345m','3m',[('pon','111s'),('pon','999p')]))
        self.assertNotIn(8078,k)

    def test_last_tile_and_kan_can_coexist(self):
        r,k=scored(case('22m44556689p','7p',[('minkan','1111m')],'tsumo',
                        context={'draw_source':'kan_replacement','wall_empty':True}))
        self.assertIn(8043,k); self.assertIn(8045,k); self.assertNotIn(8081,k)

    def test_public_own_pon_last_copy(self):
        r,k=scored(case('23m55p','1m',[('pon','111m'),('chi','456p'),('chi','789s')]))
        self.assertIn(8057,k)

    def test_rob_kan_inventory_and_exclusion(self):
        d=case('23m456p789s55z','1m',[('pon','111z')],
               context={'draw_source':'kakan_ron','visible_before_win':'111m'})
        r,k=scored(d)
        self.assertIn(8046,k); self.assertNotIn(8057,k)
        d['context']['visible_before_win']='11m'
        with self.assertRaises(ValueError): evaluate(d)

    def test_opening_events(self):
        for opening,seat,method,fan in [('heaven','1z','tsumo',8083),('earth','2z','ron',8084),('human','3z','ron',8085)]:
            r,k=scored(case('1112345678999m','5m',method=method,seat_wind=seat,context={'opening':opening}))
            self.assertIn(fan,k)
            self.assertNotIn(8063,k)

    def test_low_fan_not_replaced_by_chicken(self):
        r,k=scored(case('23m456p678s11z','4m',[('pon','555z')]))
        self.assertEqual(r['total'],8); self.assertNotIn(8042,k)
        r,k=scored(case('23m456p678s11z','4m',[('pon','222m')]))
        self.assertFalse(r['eligible']); self.assertNotIn(8042,k)
        r,k=scored(case('67s11z','8s',[('chi','123m'),('chi','456m'),('chi','345p')]))
        self.assertEqual(r['total'],1)
        self.assertEqual(k,{8072:1})

    def test_invalid_input(self):
        for d in [case('1111222233334m','1m'),case('123m','4m'),case('123456789m111p1z','2z',context={'draw_source':'kan_replacement'})]:
            with self.assertRaises(ValueError): evaluate(d)
        with self.assertRaises(ValueError): parse('0m')
        with self.assertRaises(ValueError): parse('8z')

if __name__=='__main__': unittest.main()
