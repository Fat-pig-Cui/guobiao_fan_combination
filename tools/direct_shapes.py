"""Small independent structural generator for bounded coverage comparisons.

Unbounded traversal is intentionally opt-in. This enumerates physical structures,
not a proof that scoring/projection constraints are correct.
"""
from collections import Counter
from itertools import combinations_with_replacement, product
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from decompose import Group, compact, parse
from calc_fan import evaluate
from reachability import contexts

def standard_states(tiles=range(34), *, open_states=True):
    allowed=set(tiles)
    templates=[Group('triplet',t) for t in allowed]
    templates += [Group('sequence',t) for t in allowed if t<27 and t%9<=6 and {t+1,t+2}<=allowed]
    templates.sort()
    for gs in combinations_with_replacement(templates,4):
        base=Counter(t for g in gs for t in g.tiles)
        if any(n>4 for n in base.values()): continue
        for pair in sorted(allowed):
            if base[pair]+2>4:continue
            options=[('sequence','chi') if g.sequence else ('triplet','pon','minkan','ankan') for g in gs]
            if not open_states:options=[(g.kind,) for g in gs]
            for kinds in product(*options):
                groups=[Group(k,g.tile) for k,g in zip(kinds,gs)]
                full=Counter([pair]*2+[t for g in groups for t in g.tiles])
                if any(n>4 for n in full.values()):continue
                fixed=tuple(g for g in groups if g.fixed)
                concealed=tuple(sorted([pair]*2+[t for g in groups if not g.fixed for t in g.tiles]))
                for win in sorted(set(concealed)):
                    hand=list(concealed);hand.remove(win)
                    yield tuple(hand),win,fixed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tiles',required=True);p.add_argument('--limit',type=int,default=100)
    a=p.parse_args();n=0;keys=set()
    for hand,win,fixed in standard_states(parse(a.tiles)):
        for method,ctx in contexts(hand,win,fixed):
            for seat in range(27,31):
                for rnd in range(27,31):
                    data={'hand':compact(hand),'win':compact((win,)),
                          'melds':[{'kind':g.kind,'tiles':compact(g.tiles)} for g in fixed],
                          'method':method,'seat_wind':compact((seat,)),'round_wind':compact((rnd,)),
                          'context':ctx}
                    try:r=evaluate(data)
                    except ValueError:continue
                    if r['eligible']:keys.update(tuple(tuple(x) for x in o['key']) for o in r['optimal'])
                    n+=1
                    if a.limit and n>=a.limit:
                        print(json.dumps({'states':n,'combinations':len(keys),'complete':False}));return
    print(json.dumps({'states':n,'combinations':len(keys),'complete':False,
                      'scope_complete':True,'scope':'restricted tiles; standard structures only'}))

if __name__=='__main__':main()
