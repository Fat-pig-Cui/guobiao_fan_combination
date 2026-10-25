"""Hybrid hand-written census: CPU generation, CPU/CUDA batch screening, exact scoring."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from context_expansion import expand, source_hash as expansion_hash
from enumerate_combinations import FAMILIES, key_tuple, read_records, write_json
from hand_solver import iter_inputs
from rules import PROFILE, fan_total
from tools.feature_batch import candidate_record, python_classify, read_results, write_candidates
from tools.hand_census import physical_key, source_hash


def run(output, *, families, policy='all_optimal', min_fan=8, max_fan=None,
        include_melds=True, prefix=None, batch_size=2048, required_mask=0,
        executable=None, seconds=0, max_candidates=0, checkpoint_every=1,
        resume=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Output exists; use --resume or a new directory')
    output.mkdir(parents=True, exist_ok=True)
    old = json.loads((output / 'summary.json').read_text(encoding='utf-8')) \
        if (output / 'summary.json').exists() else {}
    config = {'families': list(families), 'policy': policy, 'min_fan': min_fan,
              'max_fan': max_fan, 'include_melds': include_melds, 'prefix': prefix,
              'batch_size': batch_size, 'required_mask': required_mask,
              'executable': str(executable) if executable else None}
    if old and (old.get('source_sha256') != source_hash() or old.get('config') != config
                or old.get('expansion_sha256') != expansion_hash()):
        raise ValueError('Hybrid checkpoint fingerprint/config mismatch')
    seen_keys = {key_tuple(row['key']) for row in read_records(output / 'combinations.jsonl')}
    canonical = {key_tuple(row['key']) for row in read_records(output / 'canonical_observations.jsonl')}
    seen_physical = {row['physical_key'] for row in read_records(output / 'inventories.jsonl')}
    candidates = old.get('candidates', 0)
    screened = old.get('screened', 0)
    contexts = old.get('contexts_evaluated', 0)
    stage = old.get('stage_metrics', {})
    for name in ('generate', 'feature_filter', 'expand_evaluate', 'json_flush', 'checkpoint_write'):
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
        return {'schema_version': 1, 'backend': 'hand-written-cuda-hybrid-v1',
                'profile': PROFILE, 'source_sha256': source_hash(),
                'expansion_sha256': expansion_hash(), 'config': config,
                'families': list(families), 'candidates': candidates,
                'screened': screened, 'contexts_evaluated': contexts,
                'combination_count': len(seen_keys),
                'canonical_count_observed': len(canonical),
                'fan_distribution': dict(sorted(Counter(fan_total(k) for k in seen_keys).items())),
                'complete': termination == 'unsat', 'scope_complete': termination == 'unsat',
                'termination': termination, 'elapsed_seconds': round(
                    old.get('elapsed_seconds', 0) + time.monotonic() - start, 3),
                'stage_metrics': stage,
                'evidence': 'CPU finite generator, optional CUDA feature filter, independent exact scoring'}

    def checkpoint():
        finish = timed('checkpoint_write')
        write_json(output / 'summary.json', snapshot())
        finish()

    def exact_batch(batch, accepted, observations, inventories):
        nonlocal screened, contexts
        if not batch:
            return
        with tempfile.TemporaryDirectory(prefix='hand-cuda-batch-', dir=str(output)) as tmp:
            tmp = Path(tmp)
            input_bin, result_bin = tmp / 'candidates.bin', tmp / 'features.bin'
            records = [candidate_record(data, 0) for data in batch]
            write_candidates(records, input_bin)
            finish = timed('feature_filter')
            if executable:
                subprocess.run([str(executable), str(input_bin), str(result_bin),
                                str(required_mask)], check=True)
            else:
                with result_bin.open('wb') as stream:
                    from tools.feature_batch import HEADER
                    stream.write(HEADER.pack(b'MCRF', 1, len(records)))
                    for record in records:
                        stream.write(python_classify(record, required_mask))
            results = read_results(result_bin)
            finish()
        for data, result in zip(batch, results):
            screened += 1
            if not result[3]:
                continue
            finish = timed('expand_evaluate')
            cases = 0
            new_keys = set()
            for expanded, scored in expand(data):
                cases += 1
                contexts += 1
                if not scored['eligible']:
                    continue
                choices = scored['optimal'] if policy == 'all_optimal' else [scored['canonical']]
                can = key_tuple(scored['canonical']['key'])
                canonical.add(can)
                for interpretation in choices:
                    key = key_tuple(interpretation['key'])
                    if scored['total'] < min_fan or (max_fan is not None and scored['total'] > max_fan):
                        continue
                    if key in seen_keys:
                        continue
                    accepted.write(json.dumps({
                        'key': key, 'total': scored['total'], 'input': expanded,
                        'interpretation': interpretation, 'is_canonical': key == can,
                        'closed': scored['closed'], 'method': scored['method'],
                        'certificate': scored['certificate'], 'backend': 'hand-written-cuda-hybrid-v1'},
                        ensure_ascii=False) + '\n')
                    seen_keys.add(key); new_keys.add(key)
                observations.write(json.dumps({'key': can, 'input': expanded},
                                               ensure_ascii=False) + '\n')
            finish()
            inventories.write(json.dumps({'physical_key': physical_key(data), 'input': data,
                                          'contexts_evaluated': cases, 'keys_added': len(new_keys)},
                                         ensure_ascii=False) + '\n')

    with ((output / 'combinations.jsonl').open('a', encoding='utf-8') as accepted,
          (output / 'canonical_observations.jsonl').open('a', encoding='utf-8') as observations,
          (output / 'inventories.jsonl').open('a', encoding='utf-8') as inventories):
        batch = []
        try:
            for family in families:
                if prefix is not None and family != 'standard' and prefix != 0:
                    continue
                generator = iter_inputs(family, include_melds=include_melds, prefix=prefix) \
                    if family == 'standard' else iter_inputs(family)
                for data in generator:
                    if seconds and time.monotonic() - start >= seconds:
                        termination = 'time_limit'; break
                    if max_candidates and candidates >= max_candidates:
                        termination = 'candidate_limit'; break
                    if physical_key(data) in seen_physical:
                        continue
                    seen_physical.add(physical_key(data)); candidates += 1; batch.append(data)
                    if len(batch) < batch_size:
                        continue
                    exact_batch(batch, accepted, observations, inventories); batch = []
                    finish = timed('json_flush')
                    accepted.flush(); observations.flush(); inventories.flush(); finish()
                    if checkpoint_every and candidates % checkpoint_every == 0:
                        checkpoint()
                if batch:
                    exact_batch(batch, accepted, observations, inventories); batch = []
                    finish = timed('json_flush')
                    accepted.flush(); observations.flush(); inventories.flush(); finish()
                if termination != 'running':
                    break
            else:
                termination = 'unsat'
        except KeyboardInterrupt:
            termination = 'interrupted'
        finally:
            if batch:
                exact_batch(batch, accepted, observations, inventories)
            checkpoint()
    return snapshot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--families', nargs='+', choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument('--policy', choices=('all_optimal', 'canonical'), default='all_optimal')
    parser.add_argument('--min-fan', type=int, default=8)
    parser.add_argument('--max-fan', type=int)
    parser.add_argument('--prefix', type=int)
    parser.add_argument('--concealed-only', action='store_true')
    parser.add_argument('--batch-size', type=int, default=2048)
    parser.add_argument('--required-mask', type=int, default=0)
    parser.add_argument('--executable', type=Path,
                        help='mahjong_feature_filter; omitted uses Python reference filter')
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--max-candidates', type=int, default=0)
    parser.add_argument('--checkpoint-every', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.batch_size < 1 or args.required_mask < 0:
        parser.error('batch-size must be positive and required-mask nonnegative')
    if args.prefix is not None and not 0 <= args.prefix < 34:
        parser.error('prefix must be 0..33')
    summary = run(args.output, families=args.families, policy=args.policy,
                  min_fan=args.min_fan, max_fan=args.max_fan,
                  include_melds=not args.concealed_only, prefix=args.prefix,
                  batch_size=args.batch_size, required_mask=args.required_mask,
                  executable=args.executable, seconds=args.seconds,
                  max_candidates=args.max_candidates,
                  checkpoint_every=args.checkpoint_every, resume=args.resume)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary['complete'] else 3)


if __name__ == '__main__':
    main()
