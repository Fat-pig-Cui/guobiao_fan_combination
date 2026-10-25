"""Run one exact ``standard.tile_0`` prefix of the band census.

The prefix is a disjoint structural partition.  Non-standard families are
assigned to prefix zero only, so a complete prefix queue is an exact union.
This worker is intentionally separate from ``band_census_sharded.py``: a
queue can schedule prefixes dynamically while retaining the original
checkpoint and audit format inside each task directory.
"""
import argparse
import json
import runpy
import sys
from pathlib import Path

import z3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    own = argparse.ArgumentParser(add_help=False)
    own.add_argument('--prefix', type=int, required=True,
                     help='Exact tile_0 value; standard tile_0 ranges from 0 to 33')
    own.add_argument('--no-cache', action='store_true')
    own.add_argument('--no-z3-tuning', action='store_true')
    own.add_argument('--no-compact-blocking', action='store_true')
    args, remaining = own.parse_known_args()
    if not 0 <= args.prefix < 34:
        own.error('Require 0 <= prefix < 34')

    output_parser = argparse.ArgumentParser(add_help=False)
    output_parser.add_argument('--output', required=True)
    output_args, _ = output_parser.parse_known_args(remaining)
    output = Path(output_args.output)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        'schema_version': 1,
        'prefix': args.prefix,
        'partition': 'standard.tile_0 exact prefix',
        'nonstandard_families': 'prefix_zero_only',
        'z3_arith_solver': None if args.no_z3_tuning else 2,
        'blocking_encoding': None if args.no_compact_blocking else 'mixed_radix_base_16',
    }
    proof_path = output / 'prefix.json'
    if any(output.iterdir()) and not proof_path.exists():
        own.error('Output is not an initialized prefix checkpoint; use a new directory')
    if proof_path.exists():
        old = json.loads(proof_path.read_text(encoding='utf-8'))
        if old != metadata:
            own.error('Existing prefix metadata does not match this invocation')
    else:
        proof_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')

    if '--resume' not in remaining:
        remaining = [*remaining, '--resume']

    from fast_runtime import install, tune_blocking, tune_solver
    if not args.no_cache:
        install()
    if not args.no_z3_tuning:
        tune_solver()
    if not args.no_compact_blocking:
        tune_blocking()

    import shape_solver
    original = shape_solver.ShapeSolver
    prefix = args.prefix

    class PrefixShapeSolver(original):
        def __init__(self, family='standard', *solver_args, **solver_kwargs):
            super().__init__(family, *solver_args, **solver_kwargs)
            if family == 'standard':
                self.solver.add(self.tile[0] == prefix)
            elif prefix != 0:
                self.solver.add(z3.BoolVal(False))

    shape_solver.ShapeSolver = PrefixShapeSolver
    sys.argv = [str(ROOT / 'tools' / 'band_census.py'), *remaining]
    return runpy.run_path(str(ROOT / 'tools' / 'band_census.py'), run_name='__main__')


if __name__ == '__main__':
    main()
