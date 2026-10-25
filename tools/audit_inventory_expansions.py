"""Recompute every completed physical-input expansion against a merged result."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_expansion import expand, source_hash
from enumerate_combinations import fingerprint, key_tuple, read_records, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('directories', nargs='+')
    a = p.parse_args()
    source = Path(a.source)
    summary = json.loads((source/'summary.json').read_text())
    if summary['source_sha256'] != fingerprint() or summary.get('expansion_sha256') != source_hash():
        p.error('Source fingerprint mismatch')
    keys = {key_tuple(row['key']) for row in read_records(source/'combinations.jsonl')}
    done = {}
    cases = missing_count = 0
    missing = []
    records = 0
    for directory in map(Path, a.directories):
        state = json.loads((directory/'summary.json').read_text())
        if (state['source_sha256'] != fingerprint() or state.get('expansion_sha256') != source_hash()
                or state['policy'] != summary['policy']):
            p.error('Interval fingerprint/policy mismatch')
        for row in read_records(directory/'inventories.jsonl'):
            records += 1
            data = row['input']
            token = json.dumps({name: data[name] for name in ('hand', 'win', 'melds')}, sort_keys=True)
            if token in done:
                if done[token] != row['contexts_evaluated']:
                    raise ValueError('Expansion-case count mismatch')
                continue
            count = 0
            for expanded, result in expand(data):
                count += 1
                if not result['eligible']:
                    continue
                choices = result['optimal'] if summary['policy'] == 'all_optimal' else [result['canonical']]
                for interpretation in choices:
                    key = key_tuple(interpretation['key'])
                    if key not in keys:
                        missing_count += 1
                        if len(missing) < 20:
                            missing.append({'key': key, 'input': expanded})
            if count != row['contexts_evaluated']:
                raise ValueError('Expansion-case count mismatch')
            done[token] = count
            cases += count
    report = {'passed': missing_count == 0, 'inventory_records': records,
              'unique_physical_inputs': len(done), 'contexts_recomputed': cases,
              'missing': missing, 'missing_count': missing_count,
              'global_search_complete': summary['complete'],
              'source_sha256': fingerprint(), 'expansion_sha256': source_hash(),
              'scope': 'checks every stored inventory exclusion; coverage of event projections is separately specified'}
    write_json(Path(a.output), report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','missing')}, indent=2))
    if not report['passed']:
        sys.exit(1)


if __name__ == '__main__':
    main()
