"""Directed existence searches for closed/open and ron/tsumo classifications."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate,BANS
from enumerate_combinations import FAMILIES,read_records,key_tuple,key_text,write_json,fingerprint
from shape_solver import ShapeSolver

LABELS=('closed','opened','ron','tsumo')

def ruled_out(key,label):
    """Sound negative implications of emitted fans; never fabricate a witness."""
    present={f for f,n in key if n}
    closed_only={8003,8005,8006,8011,8018,8019,8033,8055,8063,8083,8084,8085}
    opened_only={8051,8056,8075,8082}
    tsumo_only={8043,8045,8055,8081,8083}
    ron_only={8044,8046,8051,8063,8084}
    forced={'opened':closed_only,'closed':opened_only,'ron':tsumo_only,'tsumo':ron_only}
    causes=sorted(present&forced[label])
    if causes:return {'status':'no','proof':'emitted fans require the opposite label','fans':causes}
    banned={low for high in present for low in BANS.get(high,())}
    if label=='closed' and not present&closed_only and not (present|banned)&{8055,8063}:
        return {'status':'no','proof':'a closed hand must emit unsuppressed 门前清 or 不求人'}
    if label=='tsumo' and 8081 not in present|banned:
        return {'status':'no','proof':'tsumo must emit unsuppressed 自摸'}
    return None

def label_matches(result,label):
    if label=='closed':return result['closed']
    if label=='opened':return not result['closed']
    return result['method']==label

def search(key,label,solvers,policy,deadline):
    for family in FAMILIES:
        s=solvers[family];s.solver.push()
        s.solver.add(*(v==dict(key).get(f,0) for f,v in s.projection.items()))
        flag=s.closed if label=='closed' else z3.Not(s.closed) if label=='opened' else (
            s.tsumo if label=='tsumo' else z3.Not(s.tsumo))
        s.solver.add(flag)
        try:
            while True:
                if deadline and time.monotonic()>=deadline:return {'status':'unknown','reason':'time_limit'}
                status=s.solver.check()
                if status==z3.unsat:break
                if status==z3.unknown:return {'status':'unknown','reason':s.solver.reason_unknown(),'partition':family}
                model=s.solver.model();data,_=s.witness(model);r=evaluate(data)
                interpretations=r['optimal'] if policy=='all_optimal' else [r['canonical']]
                if r['eligible'] and key in {key_tuple(i['key']) for i in interpretations}:
                    return {'status':'yes','input':data,'certificate':r['certificate']}
                s.learn_waits(s.wait_values(model),len(__import__('decompose').parse(r['formal_waits']))==1)
                s.block_state(model)
        finally:s.solver.pop()
    return {'status':'no','proof':'all five structural partitions unsat under fixed vector and label'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory');p.add_argument('--output',required=True)
    p.add_argument('--timeout-ms',type=int,default=10000)
    p.add_argument('--seconds',type=int,default=0);p.add_argument('--limit-queries',type=int,default=0)
    a=p.parse_args();source=Path(a.directory);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    summary=json.loads((source/'summary.json').read_text())
    if summary['source_sha256']!=fingerprint():p.error('Source fingerprint mismatch; revalidate source first')
    if summary.get('expansion_sha256'):
        from context_expansion import source_hash
        if summary['expansion_sha256']!=source_hash():p.error('Context expansion fingerprint mismatch')
    done={}
    if (out/'summary.json').exists():
        previous=json.loads((out/'summary.json').read_text())
        if previous['source_sha256']!=fingerprint() or previous['policy']!=summary['policy']:
            p.error('Classification checkpoint fingerprint/policy mismatch')
    for row in read_records(out/'classifications.jsonl'):
        if row['result']['status']!='unknown':done[(key_tuple(row['key']),row['label'])]=row['result']
    records=list(read_records(source/'combinations.jsonl'))
    keys={key_tuple(row['key']) for row in records}
    observed={}
    for row in records:
        key=key_tuple(row['key'])
        for label in (('closed' if row['closed'] else 'opened'),row['method']):
            observed[(key,label)]=row['input']
    # Search checkpoints also retain canonical observations for inputs whose
    # primary combination was already known. Reuse those concrete witnesses;
    # never infer impossibility from a missing observed label.
    for row in read_records(source/'canonical_observations.jsonl'):
        r=evaluate(row['input'])
        choices=r['optimal'] if summary['policy']=='all_optimal' else [r['canonical']]
        for interpretation in choices:
            key=key_tuple(interpretation['key'])
            if key not in keys:continue
            for label in (('closed' if r['closed'] else 'opened'),r['method']):
                observed.setdefault((key,label),row['input'])
    solvers={f:ShapeSolver(f,timeout_ms=a.timeout_ms,canonical=summary['policy']=='canonical') for f in FAMILIES}
    start=time.monotonic();deadline=start+a.seconds if a.seconds else None;queries=0;stopped=False
    with (out/'classifications.jsonl').open('a',encoding='utf-8') as stream:
        try:
            for key in sorted(keys):
                for label in LABELS:
                    if (key,label) in done:continue
                    if (a.limit_queries and queries>=a.limit_queries) or (deadline and time.monotonic()>=deadline):
                        stopped=True;break
                    data=observed.get((key,label))
                    negative=ruled_out(key,label)
                    if data is not None:
                        if negative:raise ValueError('Classification implication contradicts a concrete witness')
                        r=evaluate(data)
                        result={'status':'yes','input':data,'certificate':r['certificate']}
                    elif negative is not None:result=negative
                    else:result=search(key,label,solvers,summary['policy'],deadline)
                    row={'key':key,'label':label,'result':result}
                    stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();queries+=1
                    if result['status']!='unknown':done[(key,label)]=result
                if stopped:break
        except KeyboardInterrupt:stopped=True
    complete=len(done)==4*len(keys)
    counts={label:sum(done.get((k,label),{}).get('status')=='yes' for k in keys) for label in LABELS}
    current={'policy':summary['policy'],'source_sha256':fingerprint(),'keys':len(keys),
             'queries_this_run':queries,'resolved':len(done),'classification_complete':complete,
             'global_complete':complete and summary['complete'],'yes_counts':counts,
             'note':'A key may belong to both closed/open and ron/tsumo; categories overlap.'}
    write_json(out/'summary.json',current)
    print(json.dumps(current,ensure_ascii=False,indent=2))
    if not complete:sys.exit(3)

if __name__=='__main__':main()
