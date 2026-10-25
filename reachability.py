"""Finite event constraints and inventory certificates; no server/replay claims."""
from collections import Counter
from decompose import Group, parse, compact

DRAW_SOURCES = ('normal','kan_replacement','kakan_ron','flower_replacement')
OPENINGS = ('none','heaven','earth','human')

def validate(data):
    hand, win = parse(data['hand']), parse(data['win'])
    if len(win) != 1: raise ValueError('win must contain exactly one tile')
    fixed = []
    for item in data.get('melds',[]):
        ts = parse(item['tiles']); kind = item['kind']
        if kind not in ('chi','pon','minkan','kakan','ankan'): raise ValueError('Invalid fixed meld kind')
        if not ts: raise ValueError('Empty fixed meld')
        g = Group(kind,min(ts))
        if sorted(ts) != sorted(g.tiles) or (g.sequence and (g.tile >= 27 or g.tile%9 > 6)):
            raise ValueError('Invalid fixed meld tiles')
        fixed.append(g)
    fixed = tuple(sorted(fixed))
    if len(fixed)>4 or len(hand) != 13-3*len(fixed): raise ValueError('Incorrect hand size')
    full = Counter(hand+win); full.update(t for g in fixed for t in g.tiles)
    if any(c>4 for c in full.values()): raise ValueError('More than four physical copies')
    method = data.get('method','ron')
    if method not in ('tsumo','ron'): raise ValueError('method must be tsumo or ron')
    seat, rnd = parse(data.get('seat_wind','2z')), parse(data.get('round_wind','1z'))
    if len(seat)!=1 or seat[0] not in range(27,31) or len(rnd)!=1 or rnd[0] not in range(27,31):
        raise ValueError('Winds must be 1z..4z')
    ctx = dict(data.get('context',{}))
    allowed = {'draw_source','wall_empty','opening','visible_before_win','certificate'}
    if set(ctx)-allowed: raise ValueError('Unknown context fields: '+str(sorted(set(ctx)-allowed)))
    source, opening = ctx.get('draw_source','normal'), ctx.get('opening','none')
    if source not in DRAW_SOURCES or source == 'flower_replacement':
        raise ValueError('Unsupported draw source for no-flower profile')
    if opening not in OPENINGS: raise ValueError('Invalid opening')
    wall = ctx.get('wall_empty',False)
    if type(wall) is not bool: raise ValueError('wall_empty must be a boolean')
    kans = [g for g in fixed if g.kan]
    if source == 'kan_replacement' and (method!='tsumo' or not kans):
        raise ValueError('Kan replacement requires tsumo and an existing kan')
    if source == 'kakan_ron' and (method!='ron' or full[win[0]]!=1 or wall):
        raise ValueError('Robbing kakan requires ron, one own copy, and a nonempty wall')
    if opening != 'none':
        if fixed or wall or source!='normal': raise ValueError('Opening incompatible with melds/late events')
        if opening=='heaven' and not (seat[0]==27 and method=='tsumo'):
            raise ValueError('Heaven requires dealer tsumo')
        if opening=='earth' and not (seat[0]!=27 and method=='ron'):
            raise ValueError('Earth requires nondealer ron on dealer first discard')
        if opening=='human' and (seat[0]==27 or (seat[0]==28 and method=='ron')):
            raise ValueError('Human ron must precede own first draw, excluding south/dealer')
    visible = parse(ctx.get('visible_before_win',[]))
    # This list contains only external public copies, not our own melds or winning tile.
    external = Counter(visible)
    if any(full[t]+n>4 for t,n in external.items()): raise ValueError('External visible copies exceed inventory')
    if source=='kakan_ron' and external[win[0]] != 3:
        raise ValueError('Robbed opponent pon must be included as three external public copies')
    if opening != 'none' and visible: raise ValueError('Opening cannot have prior visible copies')
    own_public = Counter(t for g in fixed if g.opened for t in g.tiles)
    last_copy = own_public[win[0]]+external[win[0]] == 3
    if opening!='none' and last_copy: raise ValueError('Opening last-copy event is impossible')
    # A structural resource/scheduling certificate, explicitly not a complete action log.
    cert = {'version':1,'model':'finite-inventory-and-scheduling-v1',
            'source':source,'opening':opening,'wall_empty':wall,
            'own_tiles':compact(full.elements()),'external_visible':compact(visible),
            'kan_count':len(kans),'last_copy':last_copy,
            'construction':('initial-deal' if opening!='none' else 'early-melds-then-delayed-winning-event')}
    return hand,win[0],fixed,method,seat[0],rnd[0],source,opening,wall,last_copy,cert

def contexts(hand, win, fixed):
    """Generate all event projections, using minimal external public inventories."""
    full = Counter(hand+(win,)); full.update(t for g in fixed for t in g.tiles)
    public = sum(g.tiles.count(win) for g in fixed if g.opened)
    for method in ('ron','tsumo'):
        sources = ['normal']
        if method=='tsumo' and any(g.kan for g in fixed): sources.append('kan_replacement')
        if method=='ron' and full[win]==1: sources.append('kakan_ron')
        for source in sources:
            for wall in (False,True):
                if source=='kakan_ron' and wall: continue
                amounts = [3] if source=='kakan_ron' else [0]
                needed = 3-public
                if source!='kakan_ron' and 0<needed<=4-full[win]: amounts.append(needed)
                for n in amounts:
                    yield method,{'draw_source':source,'wall_empty':wall,'opening':'none',
                                  'visible_before_win':[win]*n}
        if not fixed:
            for opening in ('heaven','earth','human'):
                if (opening=='heaven') != (method=='tsumo') and opening!='human': continue
                yield method,{'draw_source':'normal','wall_empty':False,'opening':opening,
                              'visible_before_win':[]}
