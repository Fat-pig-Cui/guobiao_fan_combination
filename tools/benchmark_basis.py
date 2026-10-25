"""Fresh-process basis/Python comparisons on identical bounded physical inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from basis_backend import batch,build
from context_expansion import expand
from decompose import parse
from enumerate_combinations import write_json
from fast_runtime import install
from native_backend import decode,read_batch
from tools.basis_census import fingerprint


def digest(tags):
    return hashlib.sha256('\n'.join(sorted(tags)).encode()).hexdigest()


def tag(key,policy,closed,method,total):
    return json.dumps([key,policy,closed,method,total],sort_keys=True,separators=(',',':'))


def worker(mode,case,input_path,directory):
    build();install()
    began=time.perf_counter()
    if mode=='basis':
        info,rows=batch(directory,tiles=parse(case['tiles']),family=case['family'],
                        left_begin=case.get('left_begin',0),max_bases=case['max_bases'])
        tags={tag(r['key'],r['policy'],r['closed'],r['method'],r['total']) for r in rows}
        result={'bases':info['bases'],'physical':info['physical'],'contexts':info['contexts'],
                'native_seconds':info['seconds']}
    else:
        inputs={p for _,p in read_batch(input_path)}
        tags=set();contexts=0
        for p in sorted(inputs):
            for _,r in expand(decode(p),equivalent_winds=True):
                contexts+=1
                if r['total']<8:continue
                for policy,choices in (('all_optimal',r['optimal']),('canonical',[r['canonical']])):
                    tags.update(tag(i['key'],policy,r['closed'],r['method'],r['total']) for i in choices)
        result={'physical':len(inputs),'contexts':contexts}
    result.update(seconds=time.perf_counter()-began,observation_count=len(tags),sha256=digest(tags))
    return result


def transactional(output):
    """Include fresh CLI startup, SQLite transactions and final summaries."""
    from tools.native_audit import audit
    rows=[]
    with tempfile.TemporaryDirectory(prefix='mcr-basis-sqlite-') as tmp:
        root=Path(tmp)
        for domain in ('1234m','12345z'):
            row={'tiles':domain}
            for mode in ('native','basis'):
                out=root/(domain+'-'+mode)
                script='native_census.py' if mode=='native' else 'basis_census.py'
                command=[sys.executable,str(ROOT/'tools'/script),'--output',str(out),
                         '--tiles',domain,'--no-export']
                command+=['--families','standard'] if mode=='native' else ['--family','standard']
                began=time.perf_counter()
                subprocess.run(command,check=True,capture_output=True,text=True)
                elapsed=time.perf_counter()-began
                summary=json.loads((out/'summary.json').read_text())
                with sqlite3.connect((out/'census.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True) as conn:
                    values=set(conn.execute('SELECT key,policy,closed,method,total FROM observations'))
                row[mode]={'seconds':elapsed,'scope_complete':summary['scope_complete'],
                           'observations':len(values),'sqlite_bytes':(out/'census.sqlite3').stat().st_size}
                if mode=='native':expected=values
                else:row['equal']=values==expected
            row['speedup']=row['native']['seconds']/row['basis']['seconds']
            install();row['witness_audit']=audit(root/(domain+'-basis'))
            rows.append(row);print(json.dumps(row),flush=True)
    report={'passed':all(r['equal'] and r['witness_audit']['passed'] for r in rows),
            'source_sha256':fingerprint(),'cases':rows,
            'boundary':'complete restricted standard domains; fresh CLI, transactional SQLite and summaries; no JSONL export in timing; Python audit afterward'}
    output.parent.mkdir(parents=True,exist_ok=True);write_json(output,report)
    if not report['passed']:raise SystemExit(1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path)
    p.add_argument('--worker',choices=('basis','python'))
    p.add_argument('--case')
    p.add_argument('--input',type=Path)
    p.add_argument('--directory',type=Path)
    p.add_argument('--sqlite',action='store_true',help='Compare transactional CLI runners instead of computation only')
    a=p.parse_args()
    if a.worker:
        print(json.dumps(worker(a.worker,json.loads(a.case),a.input,a.directory)));return
    if a.output is None:p.error('--output is required')
    build()
    if a.sqlite:
        transactional(a.output);return
    cases=[{'name':domain,'family':'standard','tiles':domain,'max_bases':0}
           for domain in ('1234m','12345z')]
    cases += [{'name':'full-domain-left-'+str(left),'family':'standard',
               'tiles':'123456789m123456789p123456789s1234567z','left_begin':left,'max_bases':16}
              for left in (0,48,450,900)]
    results=[]
    with tempfile.TemporaryDirectory(prefix='mcr-basis-benchmark-') as tmp:
        for index,case in enumerate(cases):
            directory=Path(tmp)/str(index);directory.mkdir();trace=directory/'physical.bin'
            generated,_=batch(directory/'trace',tiles=parse(case['tiles']),family=case['family'],
                               left_begin=case.get('left_begin',0),max_bases=case['max_bases'],physical_output=trace)
            row={'case':case,'trace_physical':generated['physical']}
            for mode in ('python','basis'):
                run=subprocess.run([sys.executable,__file__,'--worker',mode,'--case',json.dumps(case),
                                    '--input',str(trace),'--directory',str(directory/mode)],
                                   check=True,capture_output=True,text=True)
                row[mode]=json.loads(run.stdout)
            row['equal']=row['python']['sha256']==row['basis']['sha256']
            row['speedup']=row['python']['seconds']/row['basis']['seconds']
            results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    report={'passed':all(r['equal'] for r in results),'python':sys.version,'platform':platform.platform(),
            'source_sha256':fingerprint(),'cases':results,
            'boundary':'bounded comparisons; fresh processes; native subprocess and decoding included; no SQLite or final audit timing'}
    a.output.parent.mkdir(parents=True,exist_ok=True);write_json(a.output,report)
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
