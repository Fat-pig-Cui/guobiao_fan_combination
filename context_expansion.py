"""Exhaust event projections for one physical input before excluding its inventory."""
from collections import Counter
import hashlib
from pathlib import Path

from calc_fan import evaluate
from decompose import Group, WINDS, compact, parse
from reachability import contexts


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def expand(data, *, equivalent_winds=False):
    hand, win = parse(data['hand']), parse(data['win'])[0]
    fixed = tuple(sorted(Group(m['kind'], min(parse(m['tiles']))) for m in data['melds']))
    full = Counter(hand+(win,))
    full.update(t for g in fixed for t in g.tiles)
    wind_relevant = (any(full[t] == 3 for t in WINDS)
                     or any(g.tile in WINDS and not g.sequence for g in fixed))
    wind_trips = {t for t in WINDS if full[t] == 3}
    wind_trips.update(g.tile for g in fixed if g.tile in WINDS and not g.sequence)
    for method, context in contexts(hand, win, fixed):
        opening = context['opening']
        # With no wind pung, ordinary scoring is independent of both winds.
        # Opening eligibility still depends on seat, so visit all four seats.
        seats = range(27, 31) if wind_relevant or opening != 'none' else (28,)
        rounds = range(27, 31) if wind_relevant else (27,)
        seen_winds = set()
        for seat in seats:
            if opening == 'heaven' and seat != 27:
                continue
            if opening == 'earth' and seat == 27:
                continue
            if opening == 'human' and (seat == 27 or (method == 'ron' and seat == 28)):
                continue
            for wind in rounds:
                if equivalent_winds:
                    # Both role fans and terminal-pung subtraction depend on
                    # these flags, not the identities of unrelated winds.
                    signature = (seat in wind_trips, wind in wind_trips,
                                 seat == wind and seat in wind_trips)
                    if signature in seen_winds:
                        continue
                    seen_winds.add(signature)
                candidate = dict(data, method=method, context=context,
                                 seat_wind=compact((seat,)), round_wind=compact((wind,)))
                # Unexpected validation errors are fatal, never silently skip
                # a context and then claim that the physical input is closed.
                yield candidate, evaluate(candidate)


def block_inventory(solver, data):
    import z3
    full = Counter(parse(data['hand'])+parse(data['win']))
    fixed = Counter()
    for m in data['melds']:
        tiles = parse(m['tiles'])
        full.update(tiles)
        kind = ('sequence', 'chi', 'triplet', 'pon', 'minkan', 'ankan').index(m['kind'])
        fixed[kind, min(tiles)] += 1
    same = [solver.win == parse(data['win'])[0]]
    same += [count == full[t] for t, count in enumerate(solver.counts)]
    is_fixed = lambda typ: z3.Or(typ == 1, typ == 3, typ == 4, typ == 5)
    same.append(z3.Sum([z3.If(is_fixed(typ), 1, 0) for typ in solver.typ]) == sum(fixed.values()))
    for (kind, tile), count in fixed.items():
        same.append(z3.Sum([z3.If(z3.And(typ == kind, t == tile), 1, 0)
                            for typ, t in zip(solver.typ, solver.tile)]) == count)
    solver.solver.add(z3.Not(z3.And(same)))
