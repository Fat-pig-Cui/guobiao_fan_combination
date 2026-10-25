"""All structural interpretations, including knitted and duplicate-pair hands."""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import permutations
import re

SUITS = 'mpsz'
HONORS = frozenset(range(27,34))
WINDS = frozenset(range(27,31))
DRAGONS = frozenset(range(31,34))
TERMINALS = frozenset(t for t in range(27) if t%9 in (0,8))
ORPHANS = TERMINALS | HONORS
GREEN = frozenset((19,20,21,23,25,32))
REVERSIBLE = frozenset((9,10,11,12,13,16,17,19,21,22,23,25,26,31))
KNITTED = tuple(tuple(sorted(s*9+r for s,p in enumerate(order) for r in range(p,9,3)))
                for order in permutations(range(3)))

def parse(text):
    if isinstance(text, (tuple,list)):
        if not all(type(t) is int and 0 <= t < 34 for t in text):
            raise ValueError('Tile integers must be 0..33')
        return tuple(text)
    if not isinstance(text,str):
        raise ValueError('Tiles must be compact notation or integer list')
    compact = ''.join(text.split())
    parts = re.findall(r'([1-9]+)([mpsz])', compact)
    if ''.join(a+b for a,b in parts) != compact:
        raise ValueError('Invalid compact tile notation: '+text)
    out = tuple(SUITS.index(s)*9+int(d)-1 for ds,s in parts for d in ds)
    if any(t >= 34 for t in out):
        raise ValueError('Honor tiles must be 1z..7z')
    return out

def compact(tiles):
    counts = Counter(tiles)
    return ''.join(''.join(str(t%9+1)*counts[t] for t in range(s*9,min(s*9+9,34)))+SUITS[s]
                   for s in range(4) if any(t//9 == s for t in counts))

@dataclass(frozen=True, order=True)
class Group:
    kind: str
    tile: int

    @property
    def sequence(self): return self.kind in ('sequence','chi')
    @property
    def kan(self): return self.kind in ('minkan','kakan','ankan')
    @property
    def opened(self): return self.kind in ('chi','pon','minkan','kakan')
    @property
    def fixed(self): return self.kind not in ('sequence','triplet')
    @property
    def tiles(self):
        return (self.tile,self.tile+1,self.tile+2) if self.sequence else (self.tile,)*(4 if self.kan else 3)

@dataclass(frozen=True)
class Shape:
    kind: str
    groups: tuple = ()
    pair: int = -1
    backbone: tuple = ()

@lru_cache(maxsize=100000)
def melds(counts):
    if not any(counts): return ((),)
    first = next(i for i,c in enumerate(counts) if c)
    out = []
    if counts[first] >= 3:
        rest = list(counts); rest[first] -= 3
        out.extend((Group('triplet',first),)+r for r in melds(tuple(rest)))
    if first < 27 and first%9 <= 6 and counts[first+1] and counts[first+2]:
        rest = list(counts)
        for t in (first,first+1,first+2): rest[t] -= 1
        out.extend((Group('sequence',first),)+r for r in melds(tuple(rest)))
    return tuple(out)

@lru_cache(maxsize=50000)
def shapes(concealed, fixed=()):
    counts = Counter(concealed)
    out = []
    expected = (4-len(fixed))*3+2
    if len(concealed) != expected: return ()
    for p in sorted(counts):
        if counts[p] < 2: continue
        rest = tuple(counts[t]-(2 if t == p else 0) for t in range(34))
        for groups in melds(rest):
            if len(groups)+len(fixed) == 4:
                out.append(Shape('standard',fixed+groups,p))
    if not fixed and len(concealed) == 14:
        if all(n%2 == 0 for n in counts.values()):
            out.append(Shape('seven_pairs'))
        if set(counts) == ORPHANS and sorted(counts.values()) == [1]*12+[2]:
            out.append(Shape('orphans'))
        if len(counts) == 14:
            for backbone in KNITTED:
                if set(counts) <= set(backbone)|HONORS:
                    out.append(Shape('unconnected',backbone=backbone))
    if len(fixed) <= 1:
        for backbone in KNITTED:
            if all(counts[t] for t in backbone):
                rest = counts.copy(); rest.subtract(backbone)
                for p,n in sorted(rest.items()):
                    if n < 2: continue
                    residue = tuple(rest[t]-(2 if t == p else 0) for t in range(34))
                    for groups in melds(residue):
                        if len(groups)+len(fixed) == 1:
                            out.append(Shape('knitted',fixed+groups,p,backbone))
    return tuple(dict.fromkeys(out))

@lru_cache(maxsize=10000)
def waits(hand, fixed=(), formal=False):
    inventory = Counter(hand)
    inventory.update(t for g in fixed for t in g.tiles)
    return tuple(t for t in range(34)
                 if (formal or inventory[t] < 4) and shapes(tuple(sorted(hand+(t,))),fixed))

def winning_positions(shape, win):
    if shape.kind in ('seven_pairs','orphans','unconnected'):
        return (-2,)
    positions = [-1] if shape.pair == win else []
    positions.extend(i for i,g in enumerate(shape.groups) if not g.fixed and win in g.tiles)
    if win in shape.backbone: positions.append(-2)
    return tuple(positions)
