"""Measure sample-union merging/export and independent Python audit throughput."""
import argparse
import json
from pathlib import Path
import random
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from calc_fan import evaluate
from enumerate_combinations import write_json
from fast_runtime import install
from tools.basis_census import connect, fingerprint
from tools.native_census import dump, export


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--audit-samples',type=int,default=8192)
    a=p.parse_args()
    if a.output.exists() or a.audit_samples<1:p.error('Use a new output and positive audit count')
    parent=json.loads((a.input/'estimate.json').read_text())
    if parent['source_sha256']!=fingerprint():raise ValueError('Source mismatch')
    a.output.mkdir(parents=True)
    conn=connect(a.output/'census.sqlite3')
    with conn:conn.execute('INSERT INTO metadata VALUES (?,?)',('sampling_only','true'))
    began=time.perf_counter();growth=[];inputs=0
    for task in parent['rows']:
        path=(a.input/task['id']/'census.sqlite3').resolve()
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,conn:
            inputs+=src.execute('SELECT count(*) FROM observations').fetchone()[0]
            conn.executemany('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',src.execute('SELECT * FROM observations'))
        growth.append({'task':task['id'],'union':conn.execute('SELECT count(*) FROM observations').fetchone()[0]})
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    merging=time.perf_counter()-began
    began=time.perf_counter();export(conn,a.output);exporting=time.perf_counter()-began
    count=growth[-1]['union']
    indices=set(random.Random(20261021).sample(range(count),min(a.audit_samples,count)))
    rows=[row for i,row in enumerate(conn.execute('SELECT * FROM observations')) if i in indices]
    install();errors=[];began=time.perf_counter()
    for key,policy,closed,method,total,evidence in rows:
        data=json.loads(evidence)['input'];result=evaluate(data)
        choices=result['optimal'] if policy=='all_optimal' else [result['canonical']]
        if not (result['eligible'] and result['total']==total and result['closed']==bool(closed)
                and result['method']==method and key in {dump(c['key']) for c in choices}):
            errors.append({'key':key,'policy':policy,'input':data})
    auditing=time.perf_counter()-began
    report={'source_sha256':fingerprint(),'sampling_only':True,'merge_input_rows':inputs,
            'union_observations':count,'merge_seconds':merging,'export_seconds':exporting,
            'audit_samples':len(rows),'audit_seconds':auditing,'audit_rows_per_second':len(rows)/auditing,
            'projected_audit_seconds_at_current_union':count*auditing/len(rows),
            'passed':not errors,'errors':errors,'growth':growth,
            'boundary':'Sparse sample union only; actual full union size is unknown. Audit projection is conditional on union size and sampled witness costs; no exhaustive coverage claim.'}
    write_json(a.output/'estimate.json',report);conn.close()
    print(dump(report),flush=True)
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
