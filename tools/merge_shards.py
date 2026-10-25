"""Merge complete exact shards belonging to one fan interval."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_expansion import source_hash as expansion_hash
from enumerate_combinations import FAMILIES, fingerprint, key_tuple, read_records, write_json
from rules import PROFILE, fan_total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new output directory')

    expected_sources = fingerprint()
    expected_runner = hashlib.sha256(
        (Path(__file__).with_name('band_census.py')).read_bytes()).hexdigest()
    sources = []
    seen_indices = set()
    shard_count = None
    z3_modes = set()
    blocking_modes = set()
    for directory_name in args.directories:
        directory = Path(directory_name)
        summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
        proof = json.loads((directory / 'shard.json').read_text(encoding='utf-8'))
        if proof['schema_version'] != 1:
            parser.error('Unsupported shard proof: ' + str(directory))
        if (proof.get('partition') != 'standard.tile_0 modulo shard_count'
                or proof.get('nonstandard_families') != 'shard_zero_only'
                or proof.get('shard_count', 0) < 1):
            parser.error('Invalid shard partition proof: ' + str(directory))
        z3_modes.add(proof.get('z3_arith_solver'))
        blocking_modes.add(proof.get('blocking_encoding'))
        if shard_count is None:
            shard_count = proof['shard_count']
        if proof['shard_count'] != shard_count or proof['shard_index'] in seen_indices:
            parser.error('Shard count/index mismatch or duplicate shard: ' + str(directory))
        seen_indices.add(proof['shard_index'])
        if (summary['source_sha256'] != expected_sources
                or summary['runner_sha256'] != expected_runner
                or summary.get('expansion_sha256') != expansion_hash()):
            parser.error('Source fingerprint mismatch: ' + str(directory))
        if set(summary['families']) != set(FAMILIES):
            parser.error('Missing structural families: ' + str(directory))
        if not summary.get('domain_complete') or summary.get('termination') != 'unsat':
            parser.error('Shard is not complete: ' + str(directory))
        sources.append((directory, summary, proof))
    if shard_count is None or seen_indices != set(range(shard_count)):
        parser.error('Need exactly one complete directory for every shard index')
    if len(z3_modes) != 1:
        parser.error('All shards must use the same Z3 tuning')
    if len(blocking_modes) != 1:
        parser.error('All shards must use the same blocking encoding')
    domains = {json.dumps(s['domain'], sort_keys=True) for _, s, _ in sources}
    policies = {s['policy'] for _, s, _ in sources}
    if len(domains) != 1 or len(policies) != 1:
        parser.error('Shards must have identical domain and policy')

    sources.sort(key=lambda item: item[2]['shard_index'])
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    canonical = set()
    with ((out / 'combinations.jsonl').open('w', encoding='utf-8') as accepted,
          (out / 'canonical_observations.jsonl').open('w', encoding='utf-8') as observations):
        for directory, _, _ in sources:
            for row in read_records(directory / 'combinations.jsonl'):
                key = key_tuple(row['key'])
                if key in seen:
                    continue
                seen.add(key)
                accepted.write(json.dumps(row, ensure_ascii=False) + '\n')
            for row in read_records(directory / 'canonical_observations.jsonl'):
                key = key_tuple(row['key'])
                if key in canonical:
                    continue
                canonical.add(key)
                observations.write(json.dumps(row, ensure_ascii=False) + '\n')

    first = sources[0][1]
    summary = {
        'schema_version': 1,
        'profile': PROFILE,
        'source_sha256': expected_sources,
        'runner_sha256': expected_runner,
        'expansion_sha256': expansion_hash(),
        'policy': first['policy'],
        'domain': first['domain'],
        'families': list(FAMILIES),
        'models': sum(s['models'] for _, s, _ in sources),
        'combination_count': len(seen),
        'canonical_count_observed': len(canonical),
        'fan_distribution': dict(sorted(Counter(fan_total(k) for k in seen).items())),
        'partitions': {f: 'unsat' for f in FAMILIES},
        'domain_complete': True,
        'complete': True,
        'scope_complete': True,
        'termination': 'unsat',
        'elapsed_seconds': sum(s.get('elapsed_seconds', 0) for _, s, _ in sources),
        'solver_version': first['solver_version'],
        'evidence': 'exact standard-family tile_0 modulo shards; non-standard families in shard zero',
        'z3_arith_solver': next(iter(z3_modes)),
        'blocking_encoding': next(iter(blocking_modes)),
        'shard_proofs': [
            {'directory': str(directory.resolve()), 'index': proof['shard_index'],
             'count': proof['shard_count'],
             'summary_sha256': hashlib.sha256((directory / 'summary.json').read_bytes()).hexdigest()}
            for directory, _, proof in sources
        ],
    }
    write_json(out / 'summary.json', summary)
    print(json.dumps({'count': len(seen), 'complete': True,
                      'shards': shard_count, 'policy': first['policy']}))


if __name__ == '__main__':
    main()
