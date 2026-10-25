"""Compare a read-only local JS reference with independently scored witnesses."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import random
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calc_fan import evaluate
from enumerate_combinations import read_records, write_json, key_tuple
from rules import FANS, project

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core',required=True);p.add_argument('--records',required=True)
    p.add_argument('--output',required=True);p.add_argument('--limit',type=int,default=200)
    p.add_argument('--sample-seed',type=int)
    a=p.parse_args()
    rows=[]
    for row in read_records(Path(a.records)):
        rows.append(row['input'])
        if a.sample_seed is None and a.limit and len(rows)>=a.limit:break
    if a.sample_seed is not None and a.limit and len(rows)>a.limit:
        rows=random.Random(a.sample_seed).sample(rows,a.limit)
    with tempfile.TemporaryDirectory(prefix='guobiao-reference-') as tmp:
        cases=Path(tmp)/'cases.json';cases.write_text(json.dumps(rows),encoding='utf-8')
        reference=json.loads(subprocess.check_output(['node',str(Path(__file__).with_name('reference_runner.mjs')),
                                                     a.core,str(cases)],text=True))
    mismatches=[];matching=0
    for data,other in zip(rows,reference):
        python=evaluate(data)
        if 'error' in other:
            mismatches.append({'input':data,'reference_error':other['error']});continue
        raw={}
        for f in other['result']['fans']:
            count=f['val']//FANS[f['id']]['value']
            raw[f['id']]=raw.get(f['id'],0)+count
        key=project(raw);total=sum(f['val'] for f in other['result']['fans'])
        if total!=python['total'] or key not in {key_tuple(r['key']) for r in python['optimal']}:
            mismatches.append({'input':data,'reference':other['result'],'python':python})
        else:matching+=1
    report={'cases':len(rows),'matching_maximum_and_vector':matching,'differences':mismatches,
            'reference_sha256':{n:hashlib.sha256((Path(a.core)/n).read_bytes()).hexdigest()
                                for n in ('calcFan.js','utils.js','exportedUtils.js','constants.js')},
            'note':'Differences need rule review; reference agreement alone is not proof of correctness.'}
    write_json(Path(a.output),report)
    print(json.dumps({'cases':len(rows),'matching':matching,'differences':len(mismatches)}))

if __name__=='__main__':main()
