"""Share independently rescored witnesses between stopped interval searches.

Adds proven projection keys only. Never copies rejected-state constraints,
changes policy, or derives canonical completeness from all-optimal witnesses.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calc_fan import evaluate
from enumerate_combinations import fingerprint, key_tuple, read_records, write_json
from rules import fan_total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+')
    args = parser.parse_args()
    sources = []
    cases = {}
    for directory in map(Path, args.directories):
        summary = json.loads((directory/'summary.json').read_text())
        if summary['source_sha256'] != fingerprint():
            parser.error('Source fingerprint mismatch')
        if summary['termination'] == 'running' or 'running' in summary['partitions'].values():
            parser.error('Stop every worker cleanly before synchronization')
        sources.append((directory, summary))
        for row in read_records(directory/'combinations.jsonl'):
            cases.setdefault(key_tuple(row['key']), row['input'])
        # A different physical input may make a previously noncanonical key
        # canonical, so keep a canonical observation separately from its first
        # all-optimal witness.
        for row in read_records(directory/'canonical_observations.jsonl'):
            cases.setdefault(('canonical', key_tuple(row['key'])), row['input'])
    known_example = Path(__file__).resolve().parents[1]/'examples/high_fan_four_ankan.json'
    if known_example.exists():
        cases['high_fan_example'] = json.loads(known_example.read_text())
    rescored = {}
    for data in cases.values():
        token = json.dumps(data, sort_keys=True)
        if token not in rescored:
            rescored[token] = (data, evaluate(data))
    changes = []
    for directory, summary in sources:
        seen = {key_tuple(row['key']) for row in read_records(directory/'combinations.jsonl')}
        canonical = {key_tuple(row['key']) for row in read_records(directory/'canonical_observations.jsonl')}
        before, before_can = len(seen), len(canonical)
        lower, upper = summary['domain']['min_fan'], summary['domain']['max_fan']
        with (directory/'combinations.jsonl').open('a', encoding='utf-8') as accepted, \
             (directory/'canonical_observations.jsonl').open('a', encoding='utf-8') as observations:
            for data, r in rescored.values():
                if not r['eligible'] or r['total'] < lower or (upper is not None and r['total'] > upper):
                    continue
                can = key_tuple(r['canonical']['key'])
                if can not in canonical:
                    observations.write(json.dumps({'key': can, 'input': data}, ensure_ascii=False)+'\n')
                    canonical.add(can)
                choices = r['optimal'] if summary['policy'] == 'all_optimal' else [r['canonical']]
                for interpretation in choices:
                    key = key_tuple(interpretation['key'])
                    if key in seen:
                        continue
                    row = {'key': key, 'total': r['total'], 'input': data, 'interpretation': interpretation,
                           'is_canonical': key == can, 'closed': r['closed'], 'method': r['method'],
                           'certificate': r['certificate'], 'partition': interpretation['family']}
                    accepted.write(json.dumps(row, ensure_ascii=False)+'\n')
                    seen.add(key)
        summary['combination_count'] = len(seen)
        summary['canonical_count_observed'] = len(canonical)
        write_json(directory/'summary.json', summary)
        entry = {'source_sha256': fingerprint(), 'inputs_recomputed': len(rescored),
                 'combinations_before': before, 'combinations_after': len(seen),
                 'canonical_observations_before': before_can, 'canonical_observations_after': len(canonical)}
        with (directory/'seed_shares.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(entry)+'\n')
        changes.append({'directory': str(directory), 'added': len(seen)-before})
    print(json.dumps({'inputs_recomputed': len(rescored), 'changes': changes}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
