"""Check that solver constraints can represent independently confirmed witnesses.

This is a regression check, not a proof that the model covers all possible hands.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import random
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import z3
from decompose import parse, Group
from shape_solver import ShapeSolver
from calc_fan import evaluate
from enumerate_combinations import read_records,write_json,fingerprint

def constraints(s,data,result,interpretation):
    key=dict(interpretation['key']);sh=interpretation
    gs=sorted((Group(g['kind'],min(parse(g['tiles']))) for g in sh['groups']),
              key=lambda g:(g.tile,('sequence','chi','triplet','pon','minkan','ankan').index(g.kind)))
    out=[]
    for i,g in enumerate(gs):
        out.extend((s.tile[i]==g.tile,s.typ[i]==('sequence','chi','triplet','pon','minkan','ankan').index(g.kind)))
    if sh['pair']:out.append(s.pair==parse(sh['pair'])[0])
    full=Counter(parse(data['hand'])+parse(data['win']))
    full.update(t for m in data['melds'] for t in parse(m['tiles']))
    if sh['family']=='seven_pairs':
        pairs=sorted(t for t,c in full.items() for _ in range(c//2))
        out.extend(v==t for v,t in zip(s.pairs,pairs))
    if sh['family']=='orphans':out.append(s.pair==next(t for t,c in full.items() if c==2))
    if sh['family']=='unconnected':out.extend(v==(t in full) for t,v in enumerate(s.unique))
    if sh['family'] in ('knitted','unconnected'):
        from decompose import KNITTED
        out.append(s.bone==KNITTED.index(tuple(sorted(parse(sh['backbone'])))))
    ctx=data.get('context',{})
    out.extend((s.win==parse(data['win'])[0],s.seat==parse(data.get('seat_wind','2z'))[0],
                s.round==parse(data.get('round_wind','1z'))[0],s.tsumo==(data['method']=='tsumo'),
                s.source==('normal','kan_replacement','kakan_ron').index(ctx.get('draw_source','normal')),
                s.opening==('none','heaven','earth','human').index(ctx.get('opening','none')),
                s.wall==ctx.get('wall_empty',False),
                s.last==(result['certificate']['last_copy'] and ctx.get('draw_source')!='kakan_ron')))
    out.extend(v==key.get(f,0) for f,v in s.projection.items())
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('records');p.add_argument('--limit',type=int,default=200);p.add_argument('--output',required=True)
    p.add_argument('--sample-seed',type=int)
    a=p.parse_args();solvers={};count=0;failures=[]
    rows=read_records(Path(a.records))
    if a.sample_seed is not None:
        rows=list(rows)
        if a.limit and len(rows)>a.limit:rows=random.Random(a.sample_seed).sample(rows,a.limit)
    for row in rows:
        data=row['input'];r=evaluate(data)
        for sh in r['optimal']:
            family=sh['family'];s=solvers.setdefault(family,None)
            if s is None:s=solvers[family]=ShapeSolver(family,timeout_ms=10000)
            s.solver.push();s.solver.add(*constraints(s,data,r,sh));status=s.solver.check();s.solver.pop()
            if status!=z3.sat:failures.append({'input':data,'interpretation':sh,'status':str(status)})
            count+=1
        if a.limit and count>=a.limit:break
    write_json(Path(a.output),{'cases':count,'failures':failures,'source_sha256':fingerprint()})
    print(json.dumps({'cases':count,'failures':len(failures)}))
    if failures:sys.exit(1)

if __name__=='__main__':main()
