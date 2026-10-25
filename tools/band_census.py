"""Checkpointed projection search restricted to a disjoint total-fan interval.

Bounds apply to the generated scoring interpretation, not its independent
rescore. All independently confirmed maxima are retained, including outside
the interval. Completing every interval therefore covers every true maximum.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from decompose import parse
from enumerate_combinations import FAMILIES, fingerprint, key_tuple, read_records, write_json
from rules import PROFILE, fan_total
from shape_solver import ShapeSolver
from context_expansion import expand,block_inventory,source_hash as expansion_hash

LEGACY_RUNNER='e1ededfca1e2d292c8bc2efc3d443e4cba464723b5530b09bcc49aa0fedb3573'
# ``fe479...`` is the runner identity used by the paused checkpoints that
# predate stage metrics.  It remains an explicit upgrade source so adding
# observability does not strand a resumable checkpoint.
COMPATIBLE_RUNNERS={LEGACY_RUNNER,
                    'fe47947381eee3f42f469b136244674d219ebf99fe006cb15bc7b9049b8a2149'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--min-fan', type=int, required=True)
    p.add_argument('--max-fan', type=int, help='Inclusive upper bound; omitted means unbounded')
    p.add_argument('--policy', choices=('all_optimal', 'canonical'), default='all_optimal')
    p.add_argument('--output', required=True)
    p.add_argument('--seed', nargs='*', default=[])
    p.add_argument('--resume', action='store_true')
    p.add_argument('--timeout-ms', type=int, default=0)
    p.add_argument('--seconds', type=int, default=0)
    p.add_argument('--upgrade-runner', action='store_true',
                   help='Upgrade the recorded legacy runner; rule/model sources must be identical')
    a = p.parse_args()
    if a.min_fan < 8 or (a.max_fan is not None and a.max_fan < a.min_fan):
        p.error('Require 8 <= min-fan <= max-fan')
    out = Path(a.output)
    old = json.loads((out/'summary.json').read_text()) if (out/'summary.json').exists() else {}
    if out.exists() and any(out.iterdir()) and not a.resume:
        p.error('Use --resume or a new directory')
    fp = fingerprint()
    runner = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    domain = {'min_fan': a.min_fan, 'max_fan': a.max_fan}
    legacy=old and old['runner_sha256'] in COMPATIBLE_RUNNERS and a.upgrade_runner
    if old and (old['source_sha256'] != fp or old['domain'] != domain or old['policy'] != a.policy
                or (old['runner_sha256'] != runner and not legacy)
                or (not legacy and old.get('expansion_sha256')!=expansion_hash())):
        p.error('Checkpoint fingerprint/policy/domain mismatch')
    if old.get('domain_complete'):
        return
    out.mkdir(parents=True, exist_ok=True)
    if legacy:
        with (out/'runner_upgrades.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps({'before':old['runner_sha256'],'after':runner,
                                  'source_sha256':fp,'change':'stage metrics and resumable runner compatibility'})+'\n')
    seen = {key_tuple(row['key']) for row in read_records(out/'combinations.jsonl')}
    canonical = {key_tuple(row['key']) for row in read_records(out/'canonical_observations.jsonl')}
    rejections = list(read_records(out/'rejections.jsonl'))
    lemmas = list(read_records(out/'wait_lemmas.jsonl'))
    inventories = list(read_records(out/'inventories.jsonl'))
    partitions = old.get('partitions', {})
    models = old.get('models', 0)
    stage = old.get('stage_metrics', {})
    for name in ('solver_check', 'model_witness', 'expand_evaluate',
                 'block_inventory', 'json_flush', 'checkpoint_write'):
        stage.setdefault(name, {'seconds': 0.0, 'calls': 0})
    stage.setdefault('contexts_evaluated', 0)
    stage.setdefault('keys_added', 0)
    stage.setdefault('block_constraints', 0)
    stage.setdefault('inventory_rows', 0)
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
        return {'profile': PROFILE, 'policy': a.policy, 'source_sha256': fp,
                'runner_sha256': runner, 'expansion_sha256':expansion_hash(), 'domain': domain,
                'families': list(FAMILIES), 'partitions': partitions,
                'domain_complete': all(partitions.get(f) == 'unsat' for f in FAMILIES),
                'complete': False, 'scope_complete': False, 'termination': termination,
                'combination_count': len(seen), 'canonical_count_observed': len(canonical),
                'models': models, 'seed_directories': a.seed or old.get('seed_directories', []),
                'stage_metrics': stage,
                'elapsed_seconds': round(old.get('elapsed_seconds', 0)+time.monotonic()-start, 3),
                'solver_version': z3.get_version_string()}

    with (out/'combinations.jsonl').open('a', encoding='utf-8') as accepted, \
         (out/'canonical_observations.jsonl').open('a', encoding='utf-8') as observations, \
         (out/'rejections.jsonl').open('a', encoding='utf-8') as refused, \
         (out/'wait_lemmas.jsonl').open('a', encoding='utf-8') as learned, \
         (out/'inventories.jsonl').open('a',encoding='utf-8') as explored:
        def retain(data, result):
            if not result['eligible']:
                return set()
            can = key_tuple(result['canonical']['key'])
            choices = result['optimal'] if a.policy == 'all_optimal' else [result['canonical']]
            actual = {key_tuple(i['key']): i for i in choices}
            if can not in canonical:
                canonical.add(can)
                observations.write(json.dumps({'key': can, 'input': data}, ensure_ascii=False)+'\n')
            for key in actual.keys()-seen:
                interpretation = actual[key]
                row = {'key': key, 'total': result['total'], 'input': data,
                       'interpretation': interpretation, 'is_canonical': key == can,
                       'closed': result['closed'], 'method': result['method'],
                       'certificate': result['certificate'], 'partition': interpretation['family']}
                accepted.write(json.dumps(row, ensure_ascii=False)+'\n')
                seen.add(key)
            return set(actual)

        if not old:
            for directory in a.seed:
                for row in read_records(Path(directory)/'combinations.jsonl'):
                    total = fan_total(key_tuple(row['key']))
                    if total < a.min_fan or (a.max_fan is not None and total > a.max_fan):
                        continue
                    retain(row['input'], evaluate(row['input']))
            accepted.flush(); observations.flush()
            stage['json_flush']['calls'] += 1
        try:
            for family in ('orphans', 'unconnected', 'seven_pairs', 'knitted', 'standard'):
                if partitions.get(family) == 'unsat':
                    continue
                s = ShapeSolver(family, timeout_ms=a.timeout_ms, canonical=a.policy == 'canonical')
                s.solver.add(s.total >= a.min_fan)
                if a.max_fan is not None:
                    s.solver.add(s.total <= a.max_fan)
                for key in seen:
                    total = fan_total(key)
                    if a.min_fan <= total and (a.max_fan is None or total <= a.max_fan):
                        s.block_key(key)
                        stage['block_constraints'] += 1
                for row in rejections:
                    if row['partition'] == family:
                        s.block_saved_state(row['state'])
                for row in lemmas:
                    if row['partition'] == family:
                        s.learn_waits(row['state'], row['unique'])
                for row in inventories:
                    if row['partition']==family:
                        block_inventory(s,row['input'])
                        stage['inventory_rows'] += 1
                partitions[family] = 'running'
                write_json(out/'summary.json', snapshot())
                while True:
                    if a.seconds and time.monotonic()-start >= a.seconds:
                        termination = 'time_limit'; break
                    finish = timed('solver_check')
                    status = s.solver.check()
                    finish()
                    if status == z3.unsat:
                        partitions[family] = 'unsat'; break
                    if status == z3.unknown:
                        termination = 'unknown: '+s.solver.reason_unknown(); break
                    finish = timed('model_witness')
                    model = s.solver.model()
                    data, target = s.witness(model)
                    finish()
                    models += 1
                    before = set(seen)
                    cases=0
                    finish = timed('expand_evaluate')
                    for expanded,result in expand(data):
                        retain(expanded,result);cases+=1
                    finish()
                    stage['contexts_evaluated'] += cases
                    stage['keys_added'] += len(seen-before)
                    for key in seen-before:
                        s.block_key(key)
                        stage['block_constraints'] += 1
                    # All methods, winds, sources, last-copy and opening
                    # projections have now been evaluated for this input.
                    finish = timed('block_inventory')
                    block_inventory(s,data)
                    finish()
                    stage['inventory_rows'] += 1
                    row={'partition':family,'input':data,'contexts_evaluated':cases,
                         'keys_added':len(seen-before)}
                    explored.write(json.dumps(row,ensure_ascii=False)+'\n');inventories.append(row)
                    finish = timed('json_flush')
                    accepted.flush(); observations.flush(); explored.flush()
                    finish()
                    if models % 50 == 0:
                        finish = timed('checkpoint_write')
                        write_json(out/'summary.json', snapshot())
                        finish()
                        print(json.dumps({'family': family, 'models': models, 'count': len(seen),
                                          'seconds': round(time.monotonic()-start, 1)}), flush=True)
                if termination != 'running':
                    break
            else:
                termination = 'unsat'
        except KeyboardInterrupt:
            termination = 'interrupted'
        except Exception:
            termination = 'error'
            raise
        finally:
            for family in partitions:
                if partitions[family] == 'running':
                    partitions[family] = termination
            finish = timed('checkpoint_write')
            write_json(out/'summary.json', snapshot())
            finish()
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    if not snapshot()['domain_complete']:
        sys.exit(3)


if __name__ == '__main__':
    main()
