"""Measure complete sampled left rows with the actual transactional runner."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import json
from math import sqrt
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from basis_backend import build
from enumerate_combinations import write_json
from tools.basis_census import fingerprint
from tools.native_census import dump


def worker(root, spec):
    directory = root/spec['id']
    cmd = [sys.executable,str(ROOT/'tools/basis_census.py'),'--output',str(directory),
           '--family',spec['family'],'--no-export']
    if spec['family']=='standard':
        cmd += ['--left-begin',str(spec['left_begin']),'--left-end',str(spec['left_begin']+1)]
    if spec.get('max_bases'):
        cmd += ['--max-bases',str(spec['max_bases'])]
    started = time.perf_counter()
    with (root/(spec['id']+'.log')).open('wb') as stream:
        run = subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if run.returncode != (3 if spec.get('max_bases') else 0):
        raise RuntimeError('Sampling worker failed: '+spec['id'])
    summary = json.loads((directory/'summary.json').read_text())
    if spec['family']=='standard' and summary['bases']!=spec['row_population']:
        raise RuntimeError('Row population mismatch')
    return dict(spec,summary=summary,wall_seconds=time.perf_counter()-started)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--bins',type=int,default=8)
    p.add_argument('--per-bin',type=int,default=2)
    p.add_argument('--seed',type=int,default=20261021)
    a=p.parse_args()
    if a.output.exists() or a.workers<1 or a.bins<1 or a.per_bin<2:
        p.error('Use a new output, positive workers/bins and at least two draws per bin')
    build();source=fingerprint()
    inventory=json.loads(a.inventory.read_text())
    P=inventory['pair_rows']
    rows=[r for r in inventory['strata'] if r['family']=='standard']
    assert sum(r['population'] for r in rows)==11580567
    assert all(r['left_end']==r['left_begin']+1 for r in rows)
    rng=random.Random(a.seed)
    tasks=[]
    for j in range(a.bins):
        group=[r for r in rows if P*j//a.bins<=r['left_begin']<P*(j+1)//a.bins]
        total=sum(r['population'] for r in group)
        for k,row in enumerate(rng.choices(group,weights=[r['population'] for r in group],k=a.per_bin)):
            tasks.append({'id':f'bin-{j}-draw-{k}-row-{row["left_begin"]}',
                          'family':'standard','bin':j,'left_begin':row['left_begin'],
                          'bin_population':total,'row_population':row['population']})
    tasks += [{'id':family,'family':family} for family in ('orphans','unconnected','knitted')]
    tasks.append({'id':'seven_pairs-prefix','family':'seven_pairs','max_bases':100000})
    a.output.mkdir(parents=True)
    write_json(a.output/'plan.json',{'source_sha256':source,'seed':a.seed,'workers':a.workers,
                                   'tasks':tasks,'scheme':'independent PPS draws with replacement within disjoint left-row strata'})
    started=time.perf_counter();results=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending={pool.submit(worker,a.output,t):t for t in tasks}
        while pending:
            done,_=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in done:
                row=future.result();del pending[future];results.append(row)
                print(dump({'done':len(results),'tasks':len(tasks),'id':row['id'],
                            'bases':row['summary']['bases'],'wall_seconds':row['wall_seconds'],
                            'native_seconds':row['summary']['native_seconds']}),flush=True)
            write_json(a.output/'progress.json',{'wall_seconds':time.perf_counter()-started,
                       'done':len(results),'total':len(tasks),'completed':results,
                       'pending':[t['id'] for t in pending.values()]})
    if fingerprint()!=source:
        raise RuntimeError('Production source changed during sampling')
    work=native=variance=0.
    for j in range(a.bins):
        group=[r for r in results if r.get('bin')==j]
        total=group[0]['bin_population']
        costs=[r['wall_seconds']/r['row_population'] for r in group]
        work+=total*statistics.mean(costs)
        native+=total*statistics.mean(r['summary']['native_seconds']/r['row_population'] for r in group)
        variance+=total**2*statistics.variance(costs)/len(costs)
    report={'created_at':datetime.now().astimezone().isoformat(),'source_sha256':source,
            'workers':a.workers,'seed':a.seed,'wall_seconds':time.perf_counter()-started,
            'sampled_bases':sum(r['summary']['bases'] for r in results),
            'sampled_contexts':sum(r['summary']['contexts'] for r in results),
            'standard_work_seconds':work,'standard_native_work_seconds':native,
            'standard_hours_at_workers':work/a.workers/3600,
            'standard_95_halfwidth_hours':1.96*sqrt(variance)/a.workers/3600,
            'rows':results,
            'boundary':'Complete standard left rows, sampled PPS with replacement; actual default batch/SQLite runner, no JSONL export. Sparse row union is not full enumeration. Seven-pairs prefix is for pipeline calibration only and is not an unbiased full-family estimate. Merge/audit not included.'}
    write_json(a.output/'estimate.json',report)
    print(dump({k:v for k,v in report.items() if k not in ('rows','source_sha256')}),flush=True)


if __name__=='__main__':
    main()
