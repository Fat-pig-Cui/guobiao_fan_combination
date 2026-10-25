"""Stratified local runtime experiment, not an exhaustive run or checkpoint."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from math import comb, sqrt
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from basis_backend import build, read_observations, write_rules
from enumerate_combinations import write_json
from tools.basis_census import fingerprint, connect
from tools.native_census import dump


def sampler():
    build()
    exe = ROOT/'build-basis'/'mcr_basis_sampler'
    source = ROOT/'native/basis_sampler.cpp'
    digest = hashlib.sha256((dump(fingerprint())+source.read_text()).encode()).hexdigest()
    stamp = exe.with_suffix('.sha256')
    if not exe.exists() or not stamp.exists() or stamp.read_text().strip() != digest:
        cc = shutil.which('clang++') or shutil.which('g++')
        if not cc:
            raise RuntimeError('The local sampling experiment requires clang++ or g++')
        # Generated build artifact: only rename the CLI main; keep the scoring
        # Engine and all its includes byte-for-byte identical to production.
        engine = (ROOT/'native/basis_census.cpp').read_text()
        assert engine.count('\nint main(')==1
        (exe.parent/'basis_sampler_engine.hpp').write_text(
            engine.replace('\nint main(', '\nint production_basis_main('))
        subprocess.run([cc,'-O3','-std=c++17','-I',str(exe.parent),
                        '-I',str(ROOT/'native'),str(source),'-o',str(exe)],check=True)
        stamp.write_text(digest+'\n')
    return exe


def sample(exe, root, rules, stratum, compute_only=False):
    directory = root/stratum['id']
    directory.mkdir()
    began = time.perf_counter()
    command = [str(exe),'--rules',str(rules),'--output',str(directory/'observations.bin'),
               '--family',stratum['family'],'--ranks',' '.join(map(str,stratum['ranks']))]
    result = subprocess.run(command,check=True,capture_output=True,text=True)
    native = json.loads(result.stdout)
    if compute_only:
        native.update(stratum,elapsed_seconds=time.perf_counter()-began,
                      observation_count=((directory/'observations.bin').stat().st_size-8)//139,
                      sqlite_bytes=0)
        write_json(directory/'sample.json',native)
        return native
    rows = list(read_observations(directory/'observations.bin'))
    conn = connect(directory/'census.sqlite3')
    with conn:
        conn.execute('INSERT INTO metadata VALUES (?,?)',('sampling_only','true'))
        for row in rows:
            conn.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                         (dump(row['key']),row['policy'],int(row['closed']),row['method'],
                          row['total'],dump({'input':row['input'],'sampling_only':True})))
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    native.update(stratum,elapsed_seconds=time.perf_counter()-began,
                  observation_count=len(rows),sqlite_bytes=(directory/'census.sqlite3').stat().st_size)
    write_json(directory/'sample.json',native)
    return native


def estimate(rows, workers):
    work = 0.
    native_work = 0.
    variance = 0.
    for row in rows:
        n, total = row['bases'], row['population']
        work += total*row['elapsed_seconds']/n
        native_work += total*row['seconds']/n
        values = row['per_base_seconds']
        if len(values)>1:
            variance += total**2*(1-n/total)*statistics.variance(values)/n
    return {'native_work_seconds':native_work,'sample_pipeline_work_seconds':work,
            'native_hours_at_workers':native_work/workers/3600,
            'sample_pipeline_hours_at_workers':work/workers/3600,
            'sampling_95_halfwidth_hours':1.96*sqrt(variance)/workers/3600,
            'note':'wall-time work divided by configured workers; compute-only skips decoding/SQLite. Small cold batch pipeline projection is diagnostic, not a full-run ETA; statistical interval excludes sustained hardware and database effects'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--samples',type=int,default=64)
    p.add_argument('--seed',type=int,default=20261021)
    p.add_argument('--rows',type=int,default=16)
    p.add_argument('--inventory-only',action='store_true')
    p.add_argument('--compute-only',action='store_true',help='Skip Python witness decoding/SQLite; estimate native work separately')
    p.add_argument('--only',help='comma-separated stratum IDs, for pilot or protocol validation')
    a = p.parse_args()
    if a.workers<1 or a.samples<2 or a.rows<1:
        p.error('workers/rows must be positive and samples >=2')
    if a.output.exists():
        p.error('use a new sampling output directory')
    exe = sampler()
    a.output.mkdir(parents=True)
    source = fingerprint()
    began = time.perf_counter()
    run = subprocess.run([str(exe),'--inventory','1','--samples',str(a.samples),
                          '--seed',str(a.seed),'--rows',str(a.rows)],check=True,capture_output=True,text=True)
    inventory = json.loads(run.stdout)
    totals = {}
    for row in inventory['strata']:
        totals[row['family']] = totals.get(row['family'],0)+row['population']
    assert totals['standard']==11580567, totals
    assert totals['seven_pairs']==sum(comb(34,d)*comb(34-d,7-2*d) for d in range(4)), totals
    assert totals['unconnected']==720 and totals['orphans']==13, totals
    write_json(a.output/'inventory.json',inventory)
    print(dump({'inventory_seconds':time.perf_counter()-began,'population':totals}),flush=True)
    if a.inventory_only:
        return
    rules = a.output/'rules.txt'
    write_rules(rules)
    jobs = inventory['strata']
    if a.only:
        keep=set(a.only.split(','));jobs=[r for r in jobs if r['id'] in keep]
        assert len(jobs)==len(keep)
    random.Random(a.seed+1).shuffle(jobs)
    experiment = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending = {pool.submit(sample,exe,a.output,rules,row,a.compute_only):row for row in jobs}
        for future in as_completed(pending):
            row = future.result();results.append(row)
            print(dump({'done':len(results),'tasks':len(jobs),'id':row['id'],
                        'bases':row['bases'],'seconds':round(row['elapsed_seconds'],3)}),flush=True)
            write_json(a.output/'progress.json',{'done':len(results),'total':len(jobs),
                       'wall_seconds':time.perf_counter()-experiment,'samples':results})
    wall = time.perf_counter()-experiment
    if fingerprint()!=source:
        raise RuntimeError('Production source changed during sampling')
    report = {'created_at':datetime.now().astimezone().isoformat(),'python':sys.version,
              'platform':platform.platform(),'logical_cpus':os.cpu_count(),'workers':a.workers,
              'source_sha256':source,'sampler_sha256':hashlib.sha256((ROOT/'native/basis_sampler.cpp').read_bytes()).hexdigest(),
              'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'seed':a.seed,'samples_per_stratum':a.samples,'population':totals,'compute_only':a.compute_only,
              'complete_stratum_coverage':len(jobs)==len(inventory['strata']),
              'wall_seconds':wall,'active_worker_equivalent':sum(r['elapsed_seconds'] for r in results)/wall,
              'sampled_bases':sum(r['bases'] for r in results),
              'sampled_contexts':sum(r['contexts'] for r in results),'strata':results,
              'estimate':estimate(results,a.workers),
              'boundary':'Exact finite populations, uniform reservoir samples without replacement within each stratum; unchanged production scoring engine. Sparse samples cannot resume production or prove full coverage. Merge/export/final Python audit not timed.'}
    write_json(a.output/'estimate.json',report)
    print(dump({k:v for k,v in report.items() if k not in ('strata','source_sha256')}),flush=True)


if __name__=='__main__':
    main()
