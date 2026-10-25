"""Save bounded production-path runs and independent witness audits for five families."""
import argparse
import contextlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from enumerate_combinations import write_json
from tools.native_census import run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    rows = []
    for family,limit in (('orphans',0),('unconnected',0),('knitted',512),
                         ('seven_pairs',512),('standard',1024)):
        destination = a.output/family
        with (a.output/(family+'.log')).open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
            summary = run(destination,families=(family,),max_candidates=limit,batch_size=256)
        audit_result = subprocess.run([sys.executable,str(ROOT/'tools/native_audit.py'),str(destination)],
                                      check=True,capture_output=True,text=True)
        audit = json.loads(audit_result.stdout)
        row = {k:summary[k] for k in ('candidates','generated','contexts_evaluated','combination_count',
                                      'canonical_count','observation_count','scope_complete','complete',
                                      'elapsed_seconds','termination')}
        row.update(family=family,audit=audit)
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    write_json(a.output/'validation.json',{'passed':all(r['audit']['passed'] for r in rows),
                                         'runs':rows,'boundary':'two complete special families; other families bounded'})


if __name__ == '__main__':
    main()
