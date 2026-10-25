"""Check independently generated, restricted ordinary hands against the model."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from decompose import compact, parse
from enumerate_combinations import write_json, fingerprint
from shape_solver import ShapeSolver
from tools.direct_shapes import standard_states
from tools.check_model_coverage import constraints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tiles', default='123m123p123s11z')
    parser.add_argument('--hands', type=int, default=300)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    solvers = {}
    hands = checks = 0
    failures = []
    # Alternate physical structures, fixed-meld choices and winning tiles come
    # from direct_shapes, independently of Z3's scoring/structural predicates.
    for hand, win, fixed in standard_states(parse(args.tiles)):
        hands += 1
        for method in ('ron', 'tsumo'):
            data = {'hand': compact(hand), 'win': compact((win,)),
                    'melds': [{'kind': g.kind, 'tiles': compact(g.tiles)} for g in fixed],
                    'method': method, 'seat_wind': '2z', 'round_wind': '1z'}
            result = evaluate(data)
            if not result['eligible']:
                continue
            for interpretation in result['optimal']:
                family = interpretation['family']
                if family not in solvers:
                    solvers[family] = ShapeSolver(family, timeout_ms=10000)
                solver = solvers[family]
                solver.solver.push()
                solver.solver.add(*constraints(solver, data, result, interpretation))
                status = solver.solver.check()
                solver.solver.pop()
                checks += 1
                if status != z3.sat:
                    failures.append({'input': data, 'interpretation': interpretation, 'status': str(status)})
        if args.hands and hands >= args.hands:
            break
    report = {'hands': hands, 'optimal_interpretations_checked': checks, 'failures': failures,
              'source_sha256': fingerprint(), 'tiles': args.tiles,
              'scope': 'bounded direct ordinary-shape generation; not a global coverage proof'}
    write_json(Path(args.output), report)
    print(json.dumps({'hands': hands, 'checked': checks, 'failures': len(failures)}))
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
