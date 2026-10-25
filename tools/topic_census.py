"""Independent 8-fan topic search. Does not use a known count as a stop rule."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from shape_solver import ShapeSolver
from rules import FANS
from decompose import parse
from enumerate_combinations import key_tuple,write_json,fingerprint,read_records

def matches(interpretation,topic):
    if interpretation['total']!=8:return False
    key=key_tuple(interpretation['key'])
    if topic=='gold':return all(FANS[f]['value']==1 for f,n in key)
    return (sum(n for f,n in key if FANS[f]['value']==2)==1 and
            sum(n for f,n in key if FANS[f]['value']==1)==6)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--topic',choices=('gold','silver'),required=True)
    p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--timeout-ms',type=int,default=30000)
    p.add_argument('--policy',choices=('all_optimal','canonical'),default='canonical')
    p.add_argument('--seed-directory',help='Explicitly rescore old witnesses; do not inherit completion')
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();out=Path(a.output)
    old=json.loads((out/'summary.json').read_text()) if (out/'summary.json').exists() else {}
    if out.exists() and any(out.iterdir()) and not a.resume:p.error('Use --resume or a new output directory')
    if old and (old['source_sha256']!=fingerprint() or old['policy']!=a.policy or old['topic']!=a.topic):
        p.error('Checkpoint fingerprint/policy/topic mismatch')
    if a.resume and a.seed_directory:p.error('Use seed-directory only for a new search')
    if old.get('complete'):return
    out.mkdir(parents=True,exist_ok=True)
    s=ShapeSolver('standard',timeout_ms=a.timeout_ms,canonical=a.policy=='canonical')
    if a.topic=='gold':
        s.solver.add(*(v==0 for f,v in s.vector.items() if FANS[f]['value']!=1))
        s.solver.add(s.total==8)
    else:
        s.solver.add(*(v==0 for f,v in s.vector.items() if FANS[f]['value'] not in (1,2)))
        s.solver.add(z3.Sum([v for f,v in s.vector.items() if FANS[f]['value']==1])==6,
                     z3.Sum([v for f,v in s.vector.items() if FANS[f]['value']==2])==1)
    seen={key_tuple(row['key']) for row in read_records(out/'combinations.jsonl')}
    for key in seen:s.block_key(key)
    for row in read_records(out/'rejections.jsonl'):s.block_saved_state(row['state'])
    for row in read_records(out/'wait_lemmas.jsonl'):s.learn_waits(row['state'],row['unique'])
    models=old.get('models',0);started=time.monotonic();termination='running'
    with (out/'combinations.jsonl').open('a',encoding='utf-8') as stream, \
         (out/'rejections.jsonl').open('a',encoding='utf-8') as refusals, \
         (out/'wait_lemmas.jsonl').open('a',encoding='utf-8') as lemmas:
        if a.seed_directory:
            for row in read_records(Path(a.seed_directory)/'combinations.jsonl'):
                r=evaluate(row['input'])
                choices=r['optimal'] if a.policy=='all_optimal' else [r['canonical']]
                for interpretation in choices:
                    key=key_tuple(interpretation['key'])
                    if key not in seen and matches(interpretation,a.topic):
                        stream.write(json.dumps({'key':key,'input':row['input'],'interpretation':interpretation,
                                                 'certificate':r['certificate']},ensure_ascii=False)+'\n')
                        seen.add(key);s.block_key(key)
            stream.flush()
        try:
            while True:
                if a.seconds and time.monotonic()-started>=a.seconds:
                    termination='time_limit';break
                status=s.solver.check()
                if status!=z3.sat:
                    termination=str(status);break
                model=s.solver.model();data,target=s.witness(model);r=evaluate(data);models+=1
                state=s.wait_values(model);unique=len(parse(r['formal_waits']))==1
                s.learn_waits(state,unique)
                lemmas.write(json.dumps({'state':state,'unique':unique})+'\n');lemmas.flush()
                candidates=r['optimal'] if a.policy=='all_optimal' else [r['canonical']]
                actual={key_tuple(x['key']):x for x in candidates if matches(x,a.topic)}
                for key in sorted(actual.keys()-seen):
                    stream.write(json.dumps({'key':key,'input':data,'interpretation':actual[key],
                                             'certificate':r['certificate']},ensure_ascii=False)+'\n')
                    seen.add(key);s.block_key(key)
                if target not in actual:
                    refusals.write(json.dumps({'state':s.state_values(model),'input':data,
                                               'target':target},ensure_ascii=False)+'\n');refusals.flush()
                    s.block_state(model)
                stream.flush()
                if models%100==0:
                    print(json.dumps({'topic':a.topic,'models':models,'combinations':len(seen)}),flush=True)
        except KeyboardInterrupt:termination='interrupted'
    result={'topic':a.topic,'policy':a.policy,'complete':termination=='unsat',
            'scope':'standard structures; exactly 8 fan with the specified denominations',
            'termination':termination,'count':len(seen),'models':models,
            'elapsed_seconds':round(old.get('elapsed_seconds',0)+time.monotonic()-started,3),
            'source_sha256':fingerprint(),'seed_directory':a.seed_directory or old.get('seed_directory')}
    write_json(out/'summary.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['complete']:sys.exit(3)

if __name__=='__main__':main()
