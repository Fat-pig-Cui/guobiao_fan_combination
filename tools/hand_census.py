"""Enumerate finite hand-written candidates and score them exactly in Python.

This is an independent CPU backend.  It does not use Z3; every retained
context is still checked by ``context_expansion.expand`` and
``calc_fan.evaluate``.  The backend is intentionally checkpointed and
partitionable so it can later feed the CUDA batch filter.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calc_fan import evaluate
from context_expansion import expand, source_hash as expansion_hash
from enumerate_combinations import FAMILIES, key_tuple, read_records, write_json
from hand_solver import iter_inputs
from rules import PROFILE, fan_total


def source_hash():
    digest = hashlib.sha256()
    for name in ('hand_solver.py', 'calc_fan.py', 'decompose.py', 'reachability.py', 'rules.py'):
        digest.update(name.encode('utf-8'))
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def physical_key(data):
    return json.dumps({'hand': data['hand'], 'win': data['win'],
                       'melds': data.get('melds', [])},
                      ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def run(output, *, families, policy='all_optimal', min_fan=8, max_fan=None,
        include_melds=True, prefix=None, seconds=0, max_candidates=0,
        checkpoint_every=50, resume=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Output exists; use --resume or a new directory')
    output.mkdir(parents=True, exist_ok=True)
    old = json.loads((output / 'summary.json').read_text(encoding='utf-8')) \
        if (output / 'summary.json').exists() else {}
    config = {'families': list(families), 'policy': policy, 'min_fan': min_fan,
              'max_fan': max_fan, 'include_melds': include_melds, 'prefix': prefix}
    fp = source_hash()
    if old and (old.get('source_sha256') != fp or old.get('config') != config
                or old.get('expansion_sha256') != expansion_hash()):
        raise ValueError('Hand-solver checkpoint fingerprint/config mismatch')
    seen_keys = {key_tuple(row['key']) for row in read_records(output / 'combinations.jsonl')}
    canonical = {key_tuple(row['key']) for row in read_records(output / 'canonical_observations.jsonl')}
    seen_physical = {row['physical_key'] for row in read_records(output / 'inventories.jsonl')}
    processed = old.get('candidates', 0)
    contexts = old.get('contexts_evaluated', 0)
    stage = old.get('stage_metrics', {})
    for name in ('generate', 'expand_evaluate', 'json_flush', 'checkpoint_write'):
        stage.setdefault(name, {'seconds': 0.0, 'calls': 0})
    start = time.monotonic()
    termination = 'running'

    def timed(name):
        began = time.perf_counter()
        def done():
            entry = stage[name]
            entry['seconds'] = round(entry['seconds'] + time.perf_counter() - began, 6)
            entry['calls'] += 1
        return done

    def snapshot():
        return {
            'schema_version': 1, 'backend': 'hand-written-cpu-v1',
            'profile': PROFILE, 'source_sha256': fp,
            'expansion_sha256': expansion_hash(), 'config': config,
            'families': list(families), 'candidates': processed,
            'contexts_evaluated': contexts, 'combination_count': len(seen_keys),
            'canonical_count_observed': len(canonical),
            'fan_distribution': dict(sorted(Counter(fan_total(k) for k in seen_keys).items())),
            'complete': termination == 'unsat', 'scope_complete': termination == 'unsat',
            'termination': termination, 'elapsed_seconds': round(
                old.get('elapsed_seconds', 0) + time.monotonic() - start, 3),
            'stage_metrics': stage,
            'evidence': 'finite hand-written physical generator plus independent exact context scoring',
        }

    def checkpoint():
        finish = timed('checkpoint_write')
        write_json(output / 'summary.json', snapshot())
        finish()

    with ((output / 'combinations.jsonl').open('a', encoding='utf-8') as accepted,
          (output / 'canonical_observations.jsonl').open('a', encoding='utf-8') as observations,
          (output / 'inventories.jsonl').open('a', encoding='utf-8') as inventories):
        try:
            for family in families:
                if prefix is not None and family != 'standard' and prefix != 0:
                    continue
                generator = iter_inputs(family, include_melds=include_melds, prefix=prefix) \
                    if family == 'standard' else iter_inputs(family)
                for data in generator:
                    if seconds and time.monotonic() - start >= seconds:
                        termination = 'time_limit'
                        break
                    if max_candidates and processed >= max_candidates:
                        termination = 'candidate_limit'
                        break
                    physical = physical_key(data)
                    if physical in seen_physical:
                        continue
                    seen_physical.add(physical)
                    processed += 1
                    finish = timed('generate')
                    finish()
                    cases = 0
                    new_keys = set()
                    finish = timed('expand_evaluate')
                    for expanded, result in expand(data):
                        cases += 1
                        contexts += 1
                        if not result['eligible']:
                            continue
                        choices = result['optimal'] if policy == 'all_optimal' else [result['canonical']]
                        can = key_tuple(result['canonical']['key'])
                        canonical.add(can)
                        for interpretation in choices:
                            key = key_tuple(interpretation['key'])
                            total = result['total']
                            if total < min_fan or (max_fan is not None and total > max_fan):
                                continue
                            if key in seen_keys:
                                continue
                            row = {'key': key, 'total': total, 'input': expanded,
                                   'interpretation': interpretation,
                                   'is_canonical': key == can, 'closed': result['closed'],
                                   'method': result['method'], 'certificate': result['certificate'],
                                   'partition': family, 'backend': 'hand-written-cpu-v1'}
                            accepted.write(json.dumps(row, ensure_ascii=False) + '\n')
                            seen_keys.add(key)
                            new_keys.add(key)
                        observations.write(json.dumps({'key': can, 'input': expanded,
                                                       'partition': family}, ensure_ascii=False) + '\n')
                    finish()
                    inventories.write(json.dumps({'physical_key': physical, 'input': data,
                                                  'contexts_evaluated': cases,
                                                  'keys_added': len(new_keys),
                                                  'partition': family}, ensure_ascii=False) + '\n')
                    finish = timed('json_flush')
                    accepted.flush(); observations.flush(); inventories.flush()
                    finish()
                    if checkpoint_every and processed % checkpoint_every == 0:
                        checkpoint()
                        print(json.dumps({'family': family, 'candidates': processed,
                                          'contexts': contexts, 'combinations': len(seen_keys),
                                          'seconds': round(time.monotonic() - start, 1)}), flush=True)
                if termination != 'running':
                    break
            else:
                termination = 'unsat'
        except KeyboardInterrupt:
            termination = 'interrupted'
        finally:
            checkpoint()
    return snapshot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--families', nargs='+', choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument('--policy', choices=('all_optimal', 'canonical'), default='all_optimal')
    parser.add_argument('--min-fan', type=int, default=8)
    parser.add_argument('--max-fan', type=int)
    parser.add_argument('--prefix', type=int, help='standard-family tile_0 prefix 0..33')
    parser.add_argument('--concealed-only', action='store_true',
                        help='Do not enumerate chi/pon/kan declarations')
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--max-candidates', type=int, default=0)
    parser.add_argument('--checkpoint-every', type=int, default=50)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.prefix is not None and not 0 <= args.prefix < 34:
        parser.error('--prefix must be in 0..33')
    if args.min_fan < 0 or (args.max_fan is not None and args.max_fan < args.min_fan):
        parser.error('Invalid fan interval')
    summary = run(args.output, families=args.families, policy=args.policy,
                  min_fan=args.min_fan, max_fan=args.max_fan,
                  include_melds=not args.concealed_only, prefix=args.prefix,
                  seconds=args.seconds, max_candidates=args.max_candidates,
                  checkpoint_every=args.checkpoint_every, resume=args.resume)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary['complete'] else 3)


if __name__ == '__main__':
    main()
