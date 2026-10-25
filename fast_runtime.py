"""Optional CPU-side runtime tuning for the existing enumeration engine.

This module deliberately patches runtime references instead of changing the
rule sources included in the checkpoint fingerprint.  It therefore preserves
the existing checkpoint format and lets the optimized runner resume an old
band directory after its outputs have been checked.  It contains both Python
memoization and a Z3 arithmetic-engine selection used by the fast wrappers.
"""
from collections import Counter
from functools import lru_cache

import calc_fan
import context_expansion
import decompose


_installed = False
_solver_tuned = False
_blocking_tuned = False


_original_parse = decompose.parse
_original_compact = decompose.compact


@lru_cache(maxsize=250_000)
def _parse_text(text):
    return _original_parse(text)


def parse_cached(value):
    # The hot path uses compact strings.  Keep list/tuple behaviour identical
    # for validation and helper callers.
    if isinstance(value, str):
        return _parse_text(value)
    return _original_parse(value)


@lru_cache(maxsize=250_000)
def _compact_tuple(tiles):
    return _original_compact(tiles)


def compact_cached(tiles):
    return _compact_tuple(tuple(tiles))


@lru_cache(maxsize=250_000)
def _seq_instances(groups, pair):
    return calc_fan._uncached_seq_instances(groups, pair)


@lru_cache(maxsize=250_000)
def _structural(shape, counts, closed, hand, win, method, position):
    raw = {}
    trips, nine = calc_fan._uncached_structural(
        raw, shape, Counter(dict(counts)), closed, hand, win, method, position
    )
    return tuple(sorted(raw.items())), tuple(sorted(trips)), nine


def structural_cached(raw, shape, counts, closed, hand, win, method, position):
    counts_tuple = tuple(sorted(counts.items()))
    raw_items, trips, nine = _structural(
        shape, counts_tuple, closed, tuple(hand), win, method, position
    )
    raw.update(raw_items)
    return set(trips), nine


def install():
    """Install idempotent caches into modules used by ``context_expansion``."""
    global _installed
    if _installed:
        return

    # Preserve the original functions under private module names.  The
    # wrappers then call the originals without recursively entering the cache.
    calc_fan._uncached_seq_instances = calc_fan.seq_instances
    calc_fan._uncached_structural = calc_fan.structural

    # These globals are looked up at call time by evaluate/expand.
    decompose.parse = parse_cached
    decompose.compact = compact_cached
    calc_fan.parse = parse_cached
    calc_fan.compact = compact_cached
    calc_fan.seq_instances = _seq_instances
    calc_fan.structural = structural_cached
    context_expansion.parse = parse_cached
    context_expansion.compact = compact_cached
    _installed = True


def tune_solver():
    """Use Z3's dual-simplex arithmetic engine for the generated QF-LIA model.

    This is a runtime-only choice.  The ordinary solver class and its source
    fingerprint remain unchanged, so old checkpoints stay readable.
    """
    global _solver_tuned
    if _solver_tuned:
        return
    import shape_solver

    original = shape_solver.ShapeSolver

    class TunedShapeSolver(original):
        def __init__(self, family='standard', *solver_args, **solver_kwargs):
            super().__init__(family, *solver_args, **solver_kwargs)
            self.solver.set('smt.arith.solver', 2)

    shape_solver.ShapeSolver = TunedShapeSolver
    _solver_tuned = True


def tune_blocking():
    """Encode a projected fan vector as one injective blocking inequality.

    Every projected fan count currently fits in a base-16 digit.  The wrapper
    falls back to the original exact disjunction if a future rule profile
    exceeds that range, preserving correctness at the cost of speed.
    """
    global _blocking_tuned
    if _blocking_tuned:
        return
    import z3
    import shape_solver

    original = shape_solver.ShapeSolver
    base = 16

    class CompactBlockedShapeSolver(original):
        def __init__(self, family='standard', *solver_args, **solver_kwargs):
            super().__init__(family, *solver_args, **solver_kwargs)
            self._block_base = base
            self._block_fans = tuple(self.projection)
            self._block_code_expr = sum(
                (value * (base ** index)
                 for index, value in enumerate(self.projection.values())),
                z3.IntVal(0))

        def block_key(self, key):
            target = dict(key)
            code = 0
            for index, fan in enumerate(self._block_fans):
                digit = target.get(fan, 0)
                if digit < 0 or digit >= self._block_base:
                    return super().block_key(key)
                code += digit * (self._block_base ** index)
            self.solver.add(self._block_code_expr != code)

    shape_solver.ShapeSolver = CompactBlockedShapeSolver
    _blocking_tuned = True


def stats():
    return {
        'parse_text': _parse_text.cache_info()._asdict(),
        'compact': _compact_tuple.cache_info()._asdict(),
        'seq_instances': _seq_instances.cache_info()._asdict(),
        'structural': _structural.cache_info()._asdict(),
    }
