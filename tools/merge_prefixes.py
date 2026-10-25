"""Merge complete exact ``tile_0`` prefix checkpoints."""
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
    expected_runner = hashlib.sha256((Path(__file__).with_name('band_census.py')).read_bytes()).hexdigest()
    sources = []
    prefixes = set()
    modes = set()
    blocking = set()
    for name in args.directories:
        directory = Path(name)
        summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
        proof = json.loads((directory / 'prefix.json').read_text(encoding='utf-8'))
        if proof.get('partition') != 'standard.tile_0 exact prefix' or proof.get('nonstandard_families') != 'prefix_zero_only':
            parser.error('Invalid prefix proof: ' + str(directory))
        prefix = proof.get('prefix')
        if not isinstance(prefix, int) or not 0 <= prefix < 34 or prefix in prefixes:
            parser.error('Invalid or duplicate prefix: ' + str(directory))
        prefixes.add(prefix)
        modes.add(proof.get('z3_arith_solver'))
        blocking.add(proof.get('blocking_encoding'))
        if (summary.get('source_sha256') != expected_sources
                or summary.get('runner_sha256') != expected_runner
                or summary.get('expansion_sha256') != expansion_hash()
                or set(summary.get('families', [])) != set(FAMILIES)
                or not summary.get('domain_complete')
                or summary.get('termination') != 'unsat'):
            parser.error('Incomplete or incompatible prefix: ' + str(directory))
        sources.append((directory, summary, proof))
    if prefixes != set(range(34)):
        parser.error('Need exactly one complete directory for every tile_0 prefix 0..33')
    if len(modes) != 1 or len(blocking) != 1:
        parser.error('All prefixes must use the same solver and blocking settings')
    domains = {json.dumps(s['domain'], sort_keys=True) for _, s, _ in sources}
    policies = {s['policy'] for _, s, _ in sources}
    if len(domains) != 1 or len(policies) != 1:
        parser.error('Prefixes must have identical domain and policy')
    sources.sort(key=lambda item: item[2]['prefix'])
    out.mkdir(parents=True, exist_ok=True)
    seen, canonical = set(), set()
    with ((out / 'combinations.jsonl').open('w', encoding='utf-8') as accepted,
          (out / 'canonical_observations.jsonl').open('w', encoding='utf-8') as observations):
        for directory, _, _ in sources:
            for row in read_records(directory / 'combinations.jsonl'):
                key = key_tuple(row['key'])
                if key not in seen:
                    seen.add(key)
                    accepted.write(json.dumps(row, ensure_ascii=False) + '\n')
            for row in read_records(directory / 'canonical_observations.jsonl'):
                key = key_tuple(row['key'])
                if key not in canonical:
                    canonical.add(key)
                    observations.write(json.dumps(row, ensure_ascii=False) + '\n')
    first = sources[0][1]
    summary = {
        'schema_version': 1, 'profile': PROFILE,
        'source_sha256': expected_sources, 'runner_sha256': expected_runner,
        'expansion_sha256': expansion_hash(), 'policy': first['policy'],
        'domain': first['domain'], 'families': list(FAMILIES),
        'models': sum(s['models'] for _, s, _ in sources),
        'combination_count': len(seen), 'canonical_count_observed': len(canonical),
        'fan_distribution': dict(sorted(Counter(fan_total(k) for k in seen).items())),
        'partitions': {f: 'unsat' for f in FAMILIES},
        'domain_complete': True, 'complete': True, 'scope_complete': True,
        'termination': 'unsat',
        'elapsed_seconds': sum(s.get('elapsed_seconds', 0) for _, s, _ in sources),
        'solver_version': first['solver_version'],
        'evidence': 'exact standard-family tile_0 prefix union; non-standard families in prefix zero',
        'z3_arith_solver': next(iter(modes)),
        'blocking_encoding': next(iter(blocking)),
        'prefix_proofs': [
            {'directory': str(directory.resolve()), 'prefix': proof['prefix'],
             'summary_sha256': hashlib.sha256((directory / 'summary.json').read_bytes()).hexdigest()}
            for directory, _, proof in sources],
    }
    write_json(out / 'summary.json', summary)
    print(json.dumps({'count': len(seen), 'complete': True, 'prefixes': 34,
                      'policy': first['policy']}))


if __name__ == '__main__':
    main()
