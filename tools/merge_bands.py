"""Merge fan-interval projections, checking gap-free coverage before completion."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enumerate_combinations import FAMILIES, fingerprint, key_tuple, read_records, write_json
from rules import fan_total, PROFILE
from context_expansion import source_hash as expansion_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directories', nargs='+')
    p.add_argument('--output', required=True)
    p.add_argument('--allow-partial', action='store_true')
    a = p.parse_args()
    out = Path(a.output)
    if out.exists() and any(out.iterdir()):
        p.error('Use a new output directory')
    fp = fingerprint()
    runner = hashlib.sha256(Path(__file__).with_name('band_census.py').read_bytes()).hexdigest()
    sources = []
    for directory in map(Path, a.directories):
        summary = json.loads((directory/'summary.json').read_text())
        if (summary['source_sha256'] != fp or summary['runner_sha256'] != runner
                or summary.get('expansion_sha256')!=expansion_hash()):
            p.error('Source fingerprint mismatch: '+str(directory))
        if set(summary['families']) != set(FAMILIES):
            p.error('Missing structural families: '+str(directory))
        sources.append((directory, summary))
    policies = {s['policy'] for _, s in sources}
    if len(policies) != 1:
        p.error('Cannot merge different policies')
    sources.sort(key=lambda pair: pair[1]['domain']['min_fan'])
    expected = 8
    for _, summary in sources:
        domain = summary['domain']
        if expected is None or domain['min_fan'] != expected:
            p.error('Intervals overlap or leave a gap')
        expected = None if domain['max_fan'] is None else domain['max_fan']+1
    if expected is not None:
        p.error('The last interval must be unbounded above')
    partitions = {f: ('unsat' if all(s['partitions'].get(f) == 'unsat' for _, s in sources)
                      else 'incomplete') for f in FAMILIES}
    complete = all(s['domain_complete'] for _, s in sources) and all(v == 'unsat' for v in partitions.values())
    if not complete and not a.allow_partial:
        p.error('Some intervals are incomplete; use --allow-partial only for a labelled snapshot')
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    canonical = set()
    with (out/'combinations.jsonl').open('w', encoding='utf-8') as accepted, \
         (out/'canonical_observations.jsonl').open('w', encoding='utf-8') as observations:
        for directory, _ in sources:
            for row in read_records(directory/'combinations.jsonl'):
                key = key_tuple(row['key'])
                if key in seen:
                    continue
                seen.add(key)
                accepted.write(json.dumps(row, ensure_ascii=False)+'\n')
            for row in read_records(directory/'canonical_observations.jsonl'):
                key = key_tuple(row['key'])
                if key in canonical:
                    continue
                canonical.add(key)
                observations.write(json.dumps(row, ensure_ascii=False)+'\n')
    summary = {'schema_version': 1, 'profile': PROFILE, 'source_sha256': fp,
               'policy': next(iter(policies)), 'families': list(FAMILIES), 'all_families': list(FAMILIES),
               'models': sum(s['models'] for _, s in sources), 'combination_count': len(seen),
               'canonical_count_observed': len(canonical), 'partitions': partitions,
               'termination': 'unsat' if complete else 'incomplete_intervals',
               'complete': complete, 'scope_complete': complete,
               'fan_distribution': dict(sorted(Counter(fan_total(k) for k in seen).items())),
               'total_worker_seconds': sum(s['elapsed_seconds'] for _, s in sources),
               'solver_version': sources[0][1]['solver_version'],
               'evidence': 'gap-free intervals on generated total fan; all five structural families per interval',
               'expansion_sha256':expansion_hash(),
               'interval_proofs': [{'directory': str(d.resolve()), 'domain': s['domain'],
                                    'domain_complete': s['domain_complete'], 'runner_sha256': runner,
                                    'summary_sha256': hashlib.sha256((d/'summary.json').read_bytes()).hexdigest()}
                                   for d, s in sources]}
    write_json(out/'summary.json', summary)
    print(json.dumps({'count': len(seen), 'complete': complete, 'policy': summary['policy']}))
    if not complete:
        sys.exit(3)


if __name__ == '__main__':
    main()
