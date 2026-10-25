"""Projected count-vector enumeration with append-only auditable checkpoints."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from calc_fan import evaluate
from rules import PROFILE, fan_total
from decompose import parse

FAMILIES=('standard','seven_pairs','orphans','unconnected','knitted')
ROOT=Path(__file__).resolve().parent
CORE=('rules.py','decompose.py','reachability.py','calc_fan.py','shape_solver.py','enumerate_combinations.py')

def fingerprint():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in CORE}

def write_json(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def read_records(path):
    if path.exists():
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip(): yield json.loads(line)

def key_tuple(key): return tuple(tuple(x) for x in key)
def key_text(key): return ','.join(f'{i}:{n}' for i,n in key)

def enumerate_run(output,*,families=FAMILIES,limit=0,max_models=0,timeout_ms=0,resume=False,
                  seconds=0,stop_after_partition=False,seed=0,policy='all_optimal'):
    import z3
    from shape_solver import ShapeSolver
    output=Path(output)
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Output exists; use --resume or a new directory')
    output.mkdir(parents=True,exist_ok=True)
    old=json.loads((output/'summary.json').read_text()) if (output/'summary.json').exists() else {}
    fp=fingerprint()
    if old and (old['source_sha256']!=fp or tuple(old['families'])!=tuple(families) or old['policy']!=policy):
        raise ValueError('Cannot resume with changed source or family selection')
    if old.get('complete'): return old
    seen=set(); canonical=set()
    records=list(read_records(output/'combinations.jsonl'))
    for row in records:
        seen.add(key_tuple(row['key']))
        if row['is_canonical']: canonical.add(key_tuple(row['key']))
    for row in read_records(output/'canonical_observations.jsonl'):
        canonical.add(key_tuple(row['key']))
    partitions=dict(old.get('partitions',{}))
    rejected=list(read_records(output/'rejections.jsonl'))
    count=old.get('models',0); started=time.monotonic(); termination='running'
    total_elapsed=old.get('elapsed_seconds',0)
    def snapshot():
        return {'schema_version':1,'profile':PROFILE,'source_sha256':fp,'policy':policy,
            'families':list(families),'all_families':list(FAMILIES),
            'models':count,'combination_count':len(seen),'canonical_count_observed':len(canonical),
            'fan_distribution':dict(sorted(Counter(fan_total(k) for k in seen).items())),
            'partitions':partitions,'termination':termination,
            'complete':set(families)==set(FAMILIES) and all(partitions.get(f)=='unsat' for f in FAMILIES),
            'scope_complete':all(partitions.get(f)=='unsat' for f in families),
            'elapsed_seconds':round(total_elapsed+time.monotonic()-started,3),
            'seed':old.get('seed'),
            'solver_version':z3.get_version_string(),
            'evidence':'finite structural and event-constraint model; no complete replay histories',
            'projection_note':'K only; closed/method labels in stored witnesses are observed, not exhaustive'}
    def checkpoint(): write_json(output/'summary.json',snapshot())
    # Every rejected state is replayed for its own structural partition only.
    with (output/'combinations.jsonl').open('a',encoding='utf-8') as accepted, \
         (output/'rejections.jsonl').open('a',encoding='utf-8') as refusals:
        try:
            for family in families:
                if partitions.get(family)=='unsat': continue
                solver=ShapeSolver(family,timeout_ms,seed,canonical=policy=='canonical')
                for key in seen: solver.block_key(key)
                for row in rejected:
                    if row['partition']==family:
                        solver.block_saved_state(row['state'])
                for row in read_records(output/'wait_lemmas.jsonl'):
                    if row['partition']==family: solver.learn_waits(row['state'],row['unique'])
                partitions[family]='running'; checkpoint()
                while True:
                    if limit and len(seen)>=limit: termination='limit'; break
                    if max_models and count>=max_models: termination='max_models'; break
                    if seconds and time.monotonic()-started>=seconds: termination='time_limit'; break
                    status=solver.solver.check()
                    if status==z3.unsat:
                        partitions[family]='unsat'; break
                    if status==z3.unknown:
                        partitions[family]='unknown: '+solver.solver.reason_unknown()
                        termination='unknown'; break
                    model=solver.solver.model(); data,target=solver.witness(model); count+=1
                    try:
                        result=evaluate(data)
                    except ValueError as exc:
                        # A violation of the structural model is a bug, not a safe
                        # broad rejection; abort and preserve the candidate.
                        write_json(output/'error.json',{'partition':family,'input':data,'error':str(exc)})
                        raise RuntimeError('Invalid solver witness; see error.json') from exc
                    wait_state=solver.wait_values(model)
                    unique=len(parse(result['formal_waits']))==1
                    solver.learn_waits(wait_state,unique)
                    with (output/'wait_lemmas.jsonl').open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps({'partition':family,'state':wait_state,'unique':unique},
                                                ensure_ascii=False)+'\n')
                    can=key_tuple(result['canonical']['key'])
                    all_actual={key_tuple(r['key']):r for r in result['optimal']}
                    actual=all_actual if policy=='all_optimal' else {can:result['canonical']}
                    new=actual.keys()-seen if result['eligible'] else set()
                    for key in sorted(new):
                        row={'key':key,'total':result['total'],'input':data,
                             'interpretation':actual[key],'is_canonical':key==can,
                             'closed':result['closed'],'method':result['method'],
                             'certificate':result['certificate'],'partition':family}
                        accepted.write(json.dumps(row,ensure_ascii=False)+'\n')
                        seen.add(key); solver.block_key(key)
                    if result['eligible']: canonical.add(can)
                    # Save each canonical observation even when the vector was seen
                    # before; otherwise resuming would silently lose this information.
                    if result['eligible']:
                        with (output/'canonical_observations.jsonl').open('a',encoding='utf-8') as stream:
                            stream.write(json.dumps({'key':can,'input':data},ensure_ascii=False)+'\n')
                    if target not in actual or not result['eligible']:
                        row={'partition':family,'input':data,'target':target,'state':solver.state_values(model),
                             'actual':[r['key'] for r in result['optimal']],
                             'reason':'not_a_maximum_eligible_interpretation'}
                        refusals.write(json.dumps(row,ensure_ascii=False)+'\n'); rejected.append(row)
                        solver.block_state(model)
                    accepted.flush(); refusals.flush()
                    if count%20==0:
                        checkpoint()
                        print(json.dumps({'partition':family,'models':count,'combinations':len(seen),
                                          'seconds':round(time.monotonic()-started,1)}),flush=True)
                if termination!='running': break
                if stop_after_partition:
                    termination='partition_limit'; break
            else: termination='unsat'
        except KeyboardInterrupt: termination='interrupted'
        finally:
            if termination=='running': termination='error'
            for f in partitions:
                if partitions[f]=='running': partitions[f]=termination
            checkpoint()
    return snapshot()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--families',nargs='+',choices=FAMILIES,default=list(FAMILIES))
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--max-models',type=int,default=0)
    parser.add_argument('--seconds',type=float,default=0)
    parser.add_argument('--timeout-ms',type=int,default=0)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--policy',choices=('all_optimal','canonical'),default='all_optimal')
    parser.add_argument('--stop-after-partition',action='store_true')
    args=parser.parse_args()
    if min(args.limit,args.max_models,args.seconds,args.timeout_ms)<0: parser.error('Limits must be nonnegative')
    try: summary=enumerate_run(**vars(args))
    except (ValueError,RuntimeError) as exc: parser.exit(2,str(exc)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    parser.exit(0 if summary['complete'] else 3)

if __name__=='__main__': main()
