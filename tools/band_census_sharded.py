"""Run an exact CPU shard of the existing band census.

The standard-family state space is partitioned by ``tile_0 % shard_count``.
All non-standard families run only in shard zero, so the union of all shards is
exact and does not duplicate their work.  The original band runner is loaded
unchanged; this wrapper records the shard proof beside its checkpoint.
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
    own.add_argument('--shard-index', type=int, required=True)
    own.add_argument('--shard-count', type=int, required=True)
    own.add_argument('--no-cache', action='store_true',
                     help='Disable the optional Python memoization for benchmarking')
    own.add_argument('--no-z3-tuning', action='store_true',
                     help='Disable the optional Z3 arithmetic parameter')
    own.add_argument('--no-compact-blocking', action='store_true',
                     help='Disable mixed-radix vector blocking for benchmarking')
    args, remaining = own.parse_known_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        own.error('Require 0 <= shard-index < shard-count and shard-count >= 1')

    output_parser = argparse.ArgumentParser(add_help=False)
    output_parser.add_argument('--output', required=True)
    output_args, _ = output_parser.parse_known_args(remaining)
    output = Path(output_args.output)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        'schema_version': 1,
        'shard_index': args.shard_index,
        'shard_count': args.shard_count,
        'partition': 'standard.tile_0 modulo shard_count',
        'nonstandard_families': 'shard_zero_only',
        'z3_arith_solver': None if args.no_z3_tuning else 2,
        'blocking_encoding': None if args.no_compact_blocking else 'mixed_radix_base_16',
    }
    proof_path = output / 'shard.json'
    if any(output.iterdir()) and not proof_path.exists():
        own.error('Output is not an initialized sharded checkpoint; use a new directory')
    if proof_path.exists():
        old = json.loads(proof_path.read_text(encoding='utf-8'))
        if old != metadata:
            own.error('Existing shard metadata does not match this invocation')
    else:
        proof_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')

    # The original runner refuses any non-empty directory unless --resume is
    # present.  The sidecar is intentionally written before the run so an
    # interrupted shard remains identifiable, therefore pass --resume even
    # for a brand-new shard directory.
    if '--resume' not in remaining:
        remaining = [*remaining, '--resume']

    # Reuse the low-risk CPU memoization from the ordinary fast runner.
    from fast_runtime import install, tune_blocking, tune_solver
    if not args.no_cache:
        install()
    if not args.no_z3_tuning:
        tune_solver()
    if not args.no_compact_blocking:
        tune_blocking()

    import shape_solver
    original = shape_solver.ShapeSolver
    shard_index = args.shard_index
    shard_count = args.shard_count

    class ShardedShapeSolver(original):
        def __init__(self, family='standard', *solver_args, **solver_kwargs):
            super().__init__(family, *solver_args, **solver_kwargs)
            if family == 'standard':
                self.solver.add(self.tile[0] % shard_count == shard_index)
            elif shard_index != 0:
                self.solver.add(z3.BoolVal(False))

    shape_solver.ShapeSolver = ShardedShapeSolver
    sys.argv = [str(ROOT / 'tools' / 'band_census.py'), *remaining]
    return runpy.run_path(str(ROOT / 'tools' / 'band_census.py'), run_name='__main__')


if __name__ == '__main__':
    main()
