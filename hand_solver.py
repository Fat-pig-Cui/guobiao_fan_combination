"""Finite-domain hand generator independent of Z3.

This module deliberately generates physical inputs and delegates event
expansion and exact scoring to the existing Python implementation.  It is a
reference hand-written backend, not a claim that every large domain is fast
without further pruning.
"""
from collections import Counter
from itertools import combinations, product

from decompose import KNITTED, ORPHANS, Group
from decompose import compact


def _compact_input(concealed, win, fixed):
    """Build the canonical physical input accepted by ``reachability``."""
    return {
        'hand': compact(tuple(sorted(concealed))),
        'win': compact((win,)),
        'melds': [{'kind': g.kind, 'tiles': compact(g.tiles)} for g in fixed],
    }


def _valid_counts(groups, pair):
    counts = Counter((pair, pair))
    for group in groups:
        counts.update(group.tiles)
    return all(value <= 4 for value in counts.values())


def _group_states(groups, include_melds):
    """Yield one declaration state for each group.

    A concealed group is represented by the original ``sequence`` or
    ``triplet`` kind.  A sequence may become ``chi``; a triplet may become a
    ``pon``, ``minkan`` or ``ankan``.  This covers physical declarations while
    preserving a deterministic group order.
    """
    if not include_melds:
        yield groups
        return
    choices = []
    for group in groups:
        if group.sequence:
            choices.append((group, Group('chi', group.tile)))
        else:
            choices.append((group, Group('pon', group.tile),
                            Group('minkan', group.tile),
                            Group('ankan', group.tile)))
    for selected in product(*choices):
        # Equal geometric groups are interchangeable, including declarations.
        if any(groups[i] == groups[i-1]
               and choices[i].index(selected[i]) < choices[i-1].index(selected[i-1])
               for i in range(1, len(groups))):
            continue
        # ``choices`` includes the concealed value first.
        yield tuple(item for item in selected)


def _physical_inputs(groups, pair, include_melds=True, prefix=None):
    """Yield all standard-family physical inputs for one group skeleton."""
    for state in _group_states(groups, include_melds):
        if prefix is not None and (not groups or groups[0].tile != prefix):
            continue
        fixed = tuple(g for g in state if g.fixed)
        concealed_groups = tuple(g for g in state if not g.fixed)
        # The declared kan contributes a fourth physical copy, so reject
        # impossible states before calling the more expensive evaluator.
        if not _valid_counts(state, pair):
            continue
        concealed = [pair, pair]
        for group in concealed_groups:
            concealed.extend(group.tiles)
        # A winning tile can come from the pair or any concealed group.  A
        # fixed group cannot be the source of a normal winning tile; kakan-ron
        # is generated later by context_expansion from the physical input.
        win_options = {pair}
        for group in concealed_groups:
            win_options.update(group.tiles)
        for win in sorted(win_options):
            hand = list(concealed)
            hand.remove(win)
            yield _compact_input(hand, win, fixed)


def _group_geometries(start=0, groups=(), counts=None, prefix=None):
    """Generate four canonical groups with at most four copies of a tile."""
    if counts is None:
        counts = [0] * 34
    if len(groups) == 4:
        yield tuple(groups)
        return
    atoms = tuple(g for t in range(34) for g in
                  ((Group('triplet', t), Group('sequence', t))
                   if t < 27 and t % 9 <= 6 else (Group('triplet', t),)))
    for index in range(start, len(atoms)):
        group = atoms[index]
        if not groups and prefix is not None and group.tile != prefix:
            continue
        # Sequence inventory must use the incoming counts, not counts after
        # tentatively adding the competing triplet at the same tile.
        next_counts = list(counts)
        for tile in group.tiles:
            next_counts[tile] += 1
        if any(n > 4 for n in next_counts):
            continue
        yield from _group_geometries(index, groups + (group,), next_counts, prefix)


def standard_inputs(include_melds=True, prefix=None):
    """Enumerate standard-family physical inputs in canonical geometry order."""
    for groups in _group_geometries(prefix=prefix):
        for pair in range(34):
            if not _valid_counts(groups, pair):
                continue
            yield from _physical_inputs(groups, pair, include_melds, prefix)


def seven_pairs_inputs():
    def bounded_pairs(chosen=(), start=0):
        if len(chosen) == 7:
            yield chosen
            return
        for tile in range(start, 34):
            if chosen.count(tile) < 2:
                yield from bounded_pairs(chosen+(tile,), tile)
    for tiles in bounded_pairs():
        concealed = tuple(t for t in tiles for _ in range(2))
        for win in sorted(set(tiles)):
            hand = list(concealed)
            hand.remove(win)
            yield _compact_input(hand, win, ())


def orphans_inputs():
    for pair in sorted(ORPHANS):
        concealed = list(ORPHANS) + [pair]
        for win in sorted(ORPHANS):
            hand = list(concealed)
            hand.remove(win)
            yield _compact_input(hand, win, ())


def unconnected_inputs():
    """Enumerate all 14-distinct full-not-connected physical inputs."""
    for backbone in KNITTED:
        allowed = tuple(sorted(set(backbone) | set(range(27, 34))))
        for tiles in combinations(allowed, 14):
            selected = set(tiles)
            # The unconnected rule permits any unique 14 tiles selected from
            # one knitted backbone plus honors.
            for win in tiles:
                hand = list(tiles)
                hand.remove(win)
                yield _compact_input(hand, win, ())


def knitted_inputs(include_melds=True):
    """Generate knitted structures with one ordinary group and a pair."""
    for backbone in KNITTED:
        for pair in range(34):
            for tile in range(34):
                for kind in ('triplet', 'sequence'):
                    if kind == 'sequence' and (tile >= 27 or tile % 9 > 6):
                        continue
                    group = Group(kind, tile)
                    choices = ((group,) if not include_melds else
                               (group, Group('chi', tile)) if group.sequence else
                               (group, Group('pon', tile), Group('minkan', tile), Group('ankan', tile)))
                    for selected in choices:
                        state = (selected,)
                        fixed = tuple(g for g in state if g.fixed)
                        concealed_groups = tuple(g for g in state if not g.fixed)
                        full = list(backbone) + [pair, pair]
                        for g in state:
                            full.extend(g.tiles)
                        if any(full.count(t) > 4 for t in set(full)):
                            continue
                        concealed = list(backbone) + [pair, pair]
                        for g in concealed_groups:
                            concealed.extend(g.tiles)
                        win_options = set(backbone) | {pair}
                        for g in concealed_groups:
                            win_options.update(g.tiles)
                        for win in sorted(win_options):
                            hand = list(concealed)
                            hand.remove(win)
                            yield _compact_input(hand, win, fixed)


GENERATORS = {
    'standard': standard_inputs,
    'seven_pairs': seven_pairs_inputs,
    'orphans': orphans_inputs,
    'unconnected': unconnected_inputs,
    'knitted': knitted_inputs,
}


def iter_inputs(family='standard', **kwargs):
    try:
        generator = GENERATORS[family]
    except KeyError as exc:
        raise ValueError('unknown family: ' + family) from exc
    yield from generator(**kwargs)
