"""Exhaust a small direct structural space and compare its projected solver set."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from decompose import Group, compact, parse
from enumerate_combinations import fingerprint, key_tuple, write_json
from shape_solver import ShapeSolver
from tools.direct_shapes import standard_states


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tiles', default='123m55p')
    parser.add_argument('--output', required=True)
    parser.add_argument('--generator', choices=('reference','native'), default='reference')
    args = parser.parse_args()
    allowed = set(parse(args.tiles))
    def states():
        if args.generator == 'reference':
            yield from standard_states(allowed)
            return
        from native_backend import build, decode, generate_batch, read_batch
        with tempfile.TemporaryDirectory(prefix='mcr-native-z3-') as tmp:
            batch = Path(tmp)/'batch.bin'
            info = generate_batch(build(),batch,tiles=allowed,max_records=0)
            if not info['complete']:
                raise RuntimeError('Native small-domain generation incomplete')
            for rank,identity in read_batch(batch):
                data = decode(identity)
                fixed = tuple(Group(m['kind'],min(parse(m['tiles']))) for m in data['melds'])
                yield parse(data['hand']),parse(data['win'])[0],fixed
    direct = set()
    inputs = set()
    for hand, win, fixed in states():
        for method in ('ron', 'tsumo'):
            data = {'hand': compact(hand), 'win': compact((win,)), 'method': method,
                    'melds': [{'kind': g.kind, 'tiles': compact(g.tiles)} for g in sorted(fixed)],
                    'seat_wind': '2z', 'round_wind': '1z'}
            text = json.dumps(data, sort_keys=True)
            if text in inputs:
                continue
            inputs.add(text)
            result = evaluate(data)
            if result['eligible']:
                direct.update(key_tuple(i['key']) for i in result['optimal'])
    s = ShapeSolver('standard')
    s.solver.add(*(s.counts[t] == 0 for t in range(34) if t not in allowed))
    s.solver.add(s.seat == 28, s.round == 27, s.source == 0, s.opening == 0, z3.Not(s.wall))
    public = z3.Sum([z3.If(s.typ[i] == 1,
                          z3.If(z3.And(s.win >= s.tile[i], s.win <= s.tile[i] + 2), 1, 0),
                          z3.If(z3.And(s.typ[i] == 3, s.win == s.tile[i]), 3,
                                z3.If(z3.And(s.typ[i] == 4, s.win == s.tile[i]), 4, 0)))
                     for i in range(4)])
    # No external visible tiles; own fixed public copies still count normally.
    s.solver.add(s.last == (public == 3))
    projected = set()
    models = 0
    while s.solver.check() == z3.sat:
        model = s.solver.model()
        data, target = s.witness(model)
        result = evaluate(data)
        models += 1
        s.learn_waits(s.wait_values(model), len(parse(result['formal_waits'])) == 1)
        actual = {key_tuple(i['key']) for i in result['optimal']} if result['eligible'] else set()
        for key in actual - projected:
            s.block_key(key)
            projected.add(key)
        if target not in actual:
            s.block_state(model)
    complete = s.solver.check() == z3.unsat
    report = {'passed': complete and direct == projected, 'scope_complete': complete,
              'tiles': args.tiles, 'physical_inputs': len(inputs), 'solver_models': models,
              'generator':args.generator,
              'generator_sha256': {name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
                                   for name in (('native_backend.py','native/structure_enumerator.cpp')
                                                if args.generator == 'native' else ('tools/direct_shapes.py',))},
              'direct_combinations': len(direct), 'solver_combinations': len(projected),
              'only_direct': sorted(direct - projected), 'only_solver': sorted(projected - direct),
              'source_sha256': fingerprint(),
              'scope': 'standard generated structures; normal events; no external visible tiles; fixed winds; all_optimal'}
    write_json(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['passed']:
        sys.exit(1)


if __name__ == '__main__':
    main()
