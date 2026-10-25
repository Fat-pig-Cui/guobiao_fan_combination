"""Explicitly rescore an old snapshot into a new directory after source changes.

Never inherit old unsat claims or rejection/lemma constraints: regenerate them
under the new model. Accepted witnesses alone seed the new projection search.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from enumerate_combinations import read_records,key_tuple,fingerprint,write_json,FAMILIES
from rules import fan_total
from collections import Counter

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('output');a=p.parse_args()
    old=Path(a.source);out=Path(a.output)
    if out.exists() and any(out.iterdir()):p.error('Destination must be empty')
    out.mkdir(parents=True,exist_ok=True)
    summary=json.loads((old/'summary.json').read_text())
    keys=set();canonical=set();checked=0
    with (out/'combinations.jsonl').open('w',encoding='utf-8') as stream, \
         (out/'canonical_observations.jsonl').open('w',encoding='utf-8') as observations:
        for row in read_records(old/'combinations.jsonl'):
            r=evaluate(row['input']);checked+=1
            if not r['eligible']:continue
            candidates=r['optimal'] if summary['policy']=='all_optimal' else [r['canonical']]
            can=key_tuple(r['canonical']['key']);canonical.add(can)
            observations.write(json.dumps({'key':can,'input':row['input']},ensure_ascii=False)+'\n')
            for interpretation in candidates:
                key=key_tuple(interpretation['key'])
                if key in keys:continue
                keys.add(key)
                current={'key':key,'input':row['input'],'interpretation':interpretation,
                         'total':r['total'],'is_canonical':key==can,'closed':r['closed'],
                         'method':r['method'],'certificate':r['certificate'],'partition':row['partition']}
                stream.write(json.dumps(current,ensure_ascii=False)+'\n')
    fresh=dict(summary)
    fresh.update(source_sha256=fingerprint(),models=0,combination_count=len(keys),
        canonical_count_observed=len(canonical),partitions={},complete=False,scope_complete=False,
        elapsed_seconds=0,termination='revalidated_seed',solver_version=z3.get_version_string(),
        fan_distribution=dict(sorted(Counter(fan_total(k) for k in keys).items())),
        seed={'source_directory':str(old.resolve()),'source_fingerprint':summary['source_sha256'],
              'witnesses_recomputed':checked,'old_completion_not_inherited':True})
    write_json(out/'summary.json',fresh)
    print(json.dumps({'checked':checked,'retained':len(keys),'complete':False}))

if __name__=='__main__':main()
