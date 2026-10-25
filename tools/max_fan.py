"""Model-wide score upper bounds, independently checked against a concrete hand."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import z3
from calc_fan import evaluate
from enumerate_combinations import FAMILIES, fingerprint, write_json
from shape_solver import ShapeSolver


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--timeout-ms', type=int, default=60000)
    a = p.parse_args()
    bounds = {}
    best = None
    for family in FAMILIES:
        s = ShapeSolver(family)
        optimizer = z3.Optimize()
        if a.timeout_ms:
            optimizer.set(timeout=a.timeout_ms)
        optimizer.add(*s.solver.assertions())
        objective = optimizer.maximize(s.total)
        status = optimizer.check()
        entry = {'status': str(status)}
        if status == z3.sat:
            entry.update(upper=str(objective.upper()), lower=str(objective.lower()))
            data, _ = s.witness(optimizer.model())
            result = evaluate(data)
            entry['witness_total'] = result['total']
            if best is None or result['total'] > best['result']['total']:
                best = {'input': data, 'result': result}
        else:
            entry['reason'] = optimizer.reason_unknown()
        bounds[family] = entry
        print(json.dumps({family: entry}), flush=True)
    proved = best is not None and all(
        entry['status'] == 'sat' and entry['upper'].isdigit()
        and int(entry['upper']) <= best['result']['total'] for entry in bounds.values())
    report = {'maximum_proved': proved, 'bounds': bounds, 'best_witness': best,
              'source_sha256': fingerprint(),
              'scope': 'frozen finite model; no complete four-player histories'}
    write_json(Path(a.output), report)
    print(json.dumps({'maximum_proved': proved,
                      'maximum': best['result']['total'] if best else None}))
    if not proved:
        sys.exit(3)


if __name__ == '__main__':
    main()
