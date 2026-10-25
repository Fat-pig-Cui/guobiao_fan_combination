"""Standalone MCR/editor evaluator; enumerate decompositions and scoring supports.

No solver or JavaScript dependency. All equal maximum count vectors are retained.
"""
from collections import Counter
from functools import lru_cache
from itertools import combinations
import argparse
import json

from decompose import (parse, compact, shapes, waits, winning_positions, HONORS,
                       WINDS, DRAGONS, TERMINALS, ORPHANS, GREEN, REVERSIBLE)
from reachability import validate
from rules import FANS, PROFILE, get_profile, project, fan_total, describe

# Global exclusions. Partial exclusions (terminal/honor pungs) use tile identities below.
BANS = {
 8000:(8037,8047,8061,8062,8074), 8001:(8053,8058,8059,8060), 8002:(8048,),
 8003:(8021,8055,8063,8077), 8004:(8047,8080),
 8005:(8021,8018,8055,8063,8077,8080),
 8007:(8017,8047,8054,8066,8074,8077), 8008:(8037,8074),
 8009:(8053,8058,8059,8060), 8010:(8017,8047,8054,8074,8048),
 8011:(8047,8055,8063), 8012:(8018,8021,8064,8070,8073,8077),
 8013:(8022,8023,8018,8065,8070), 8014:(8022,8023,8047),
 8015:(8029,8072,8073), 8017:(8047,8054,8074),
 8018:(8055,8063,8080), 8019:(8033,8050,8055,8063,8080),
 8020:(8047,8069,8077), 8021:(8077,), 8022:(8023,8070),
 8024:(8035,8077),8025:(8069,8077),8026:(8036,8077),
 8027:(8072,8073),8028:(8071,8073,8077,8064),8030:(8069,8077),
 8031:(8066,),8033:(8050,8055,8063,8080),8035:(8077,),8036:(8077,),
 8039:(8076,),8040:(8071,),8043:(8081,),8045:(8081,),8046:(8057,),
 8051:(8080,),8052:(8067,),8053:(8058,8059,8060),8055:(8081,),
 8058:(),8059:(),8060:(),8064:(8077,),8069:(8077,),
 8083:(8055,8063,8081,8078,8079,8080),8084:(8063,),8085:(8055,8063,8081),
}

def excluded(raw):
    # High-to-low application avoids a suppressed fan banning something itself.
    alive = dict(raw)
    for fan in sorted(raw,key=lambda f:(-FANS[f]['value'],f)):
        if fan in alive:
            for low in BANS.get(fan,()): alive.pop(low,None)
    return alive

def seq_instances(groups,pair):
    """(fan, support) for all three-/four-chow combination patterns."""
    indices = [i for i,g in enumerate(groups) if g.sequence]
    out = []
    for support in combinations(indices,3):
        ts = sorted(groups[i].tile for i in support)
        ranks = sorted(t%9 for t in ts)
        suits = {t//9 for t in ts}
        fans = []
        if len(set(ts))==1: fans.append(8022)
        if len(suits)==1:
            if ranks==[0,3,6]: fans.append(8027)
            if ranks[1]-ranks[0] == ranks[2]-ranks[1] and ranks[1]-ranks[0] in (1,2): fans.append(8029)
        if len(suits)==3:
            if ranks==[0,3,6]: fans.append(8038)
            if len(set(ranks))==1: fans.append(8040)
            if ranks==list(range(ranks[0],ranks[0]+3)): fans.append(8049)
        out.extend((f,support) for f in fans)
    if len(indices)==4:
        ts=sorted(groups[i].tile for i in indices); suits={t//9 for t in ts}
        ranks=sorted(t%9 for t in ts)
        if len(set(ts))==1: out.append((8013,tuple(indices)))
        if len(suits)==1 and (ranks==list(range(ranks[0],ranks[0]+4)) or ranks==[0,2,4,6]):
            out.append((8015,tuple(indices)))
        if len(suits)==1 and ranks==[0,0,6,6] and pair==ts[0]//9*9+4:
            out.append((8012,tuple(indices)))
        if len(suits)==2 and pair<27 and pair//9 not in suits:
            if pair%9==4 and all(sorted(t%9 for t in ts if t//9==s)==[0,6] for s in suits):
                out.append((8028,tuple(indices)))
    return tuple(out)

@lru_cache(maxsize=50000)
def small_plans(groups, high_support=(), banned=()):
    """Legal chow-pair forests; repeated same fans require disjoint pair supports.

    Starting with an unused pair, each subsequent pair must introduce an unused
    chow (or start a disjoint component). A three-chow high pattern consumes its
    support and permits the one remaining chow to attach only once.
    """
    ids=[i for i,g in enumerate(groups) if g.sequence]
    if len(high_support)==4: return ((),)
    edges=[]
    for i,j in combinations(ids,2):
        a,b=groups[i].tile,groups[j].tile
        if a==b: f=8070
        elif a%9==b%9 and a//9!=b//9: f=8071
        elif a//9==b//9 and abs(a-b)==3: f=8072
        elif a//9==b//9 and {a%9,b%9}=={0,6}: f=8073
        else: continue
        if f not in banned and not (i in high_support and j in high_support): edges.append((f,i,j))
    results=set()
    # Tiny local search: at most six labelled pair supports among four chows.
    def visit(selected, used, labels, remaining):
        cnt=Counter(f for f,_,_ in selected)
        results.add(tuple(sorted(cnt.items())))
        for idx in remaining:
            f,i,j=edges[idx]
            mask=(1<<i)|(1<<j)
            if labels.get(f,0)&mask: continue
            if used&mask == mask: continue
            if high_support and len(selected)>=1: continue
            new=dict(labels); new[f]=new.get(f,0)|mask
            visit(selected+(edges[idx],),used|mask,new,remaining-{idx})
    visit((),sum(1<<i for i in high_support),{},set(range(len(edges))))
    return tuple(sorted(results))

def structural(raw,shape,counts,closed,hand,win,method,position):
    """All non-chow-support predicates, with partial exclusions by identities."""
    groups=shape.groups; tiles=set(counts); basic=shape.kind in ('standard','knitted')
    tsumo=method=='tsumo'; pair=shape.pair
    trips={g.tile for g in groups if not g.sequence}
    seq=[g.tile for g in groups if g.sequence]
    kans=[g for g in groups if g.kan]
    hidden=[g for i,g in enumerate(groups) if not g.sequence and not g.opened
            and (g.kan or tsumo or i!=position)]
    dark=sum(g.kind=='ankan' for g in kans)
    def add(f,condition=True,n=1):
        if condition: raw[f]=n
    add(8000,WINDS<=trips); add(8001,DRAGONS<=trips)
    add(8002,tiles<=GREEN)
    base=Counter(hand)
    nine=False
    if basic and closed and not kans:
        for suit in range(3):
            target=Counter({suit*9+r:(3 if r in (0,8) else 1) for r in range(9)})
            if base==target: nine=True
    add(8003,nine); add(8004,len(kans)==4)
    if shape.kind=='seven_pairs':
        add(8018)
        st=sorted(counts)
        add(8005,len(st)==7 and all(n==2 for n in counts.values()) and st[0]<27
            and st[-1]//9==st[0]//9 and st==list(range(st[0],st[0]+7)))
    add(8007,tiles<=TERMINALS)
    add(8008,pair in WINDS and len(trips&WINDS)==3)
    add(8009,pair in DRAGONS and len(trips&DRAGONS)==2)
    add(8010,tiles<=HONORS)
    add(8011,len(hidden)==4)
    four_step=any(all(s*9+r+d in trips for d in range(4)) for s in range(3) for r in range(6))
    add(8014,four_step); add(8016,len(kans)==3)
    add(8017,tiles<=ORPHANS and not tiles<=TERMINALS)
    add(8020,shape.kind=='standard' and len(trips)==4 and all(t<27 and t%9%2==1 for t in tiles))
    suits={t//9 for t in tiles if t<27}
    add(8021,len(suits)==1 and not tiles&HONORS)
    add(8023,any(all(s*9+r+d in trips for d in range(3)) for s in range(3) for r in range(7)))
    add(8024,all(t<27 and t%9>=6 for t in tiles))
    add(8025,all(t<27 and 3<=t%9<=5 for t in tiles))
    add(8026,all(t<27 and t%9<=2 for t in tiles))
    add(8030,basic and pair<27 and pair%9==4 and all(
        (g.tile<27 and g.tile%9<=4<=g.tile%9+2) if g.sequence
        else (g.tile<27 and g.tile%9==4) for g in groups) and not shape.backbone)
    add(8031,any(all(s*9+r in trips for s in range(3)) for r in range(9)))
    add(8032,len(hidden)==3)
    add(8034,shape.kind=='knitted')
    add(8035,all(t<27 and t%9>=5 for t in tiles)); add(8036,all(t<27 and t%9<=3 for t in tiles))
    add(8037,len(trips&WINDS)==3 and pair not in WINDS)
    add(8039,tiles<=REVERSIBLE)
    add(8041,any(len({t//9 for t in tr})==3 and
                 sorted(t%9 for t in tr)==list(range(min(t%9 for t in tr),min(t%9 for t in tr)+3))
                 for tr in combinations(sorted(t for t in trips if t<27),3)))
    add(8047,len(groups)==4 and len(trips)==4)
    add(8048,len(suits)==1 and bool(tiles&HONORS))
    add(8050,len(suits)==3 and bool(tiles&WINDS) and bool(tiles&DRAGONS))
    add(8051,len(groups)==4 and all(g.opened for g in groups) and not tsumo)
    add(8052,len(kans)==2 and dark==2)
    add(8053,len(trips&DRAGONS)==2)
    add(8054,basic and (pair in ORPHANS) and not shape.backbone and
        all((g.tile%9 in (0,6)) if g.sequence else g.tile in ORPHANS for g in groups))
    add(8055,closed and tsumo)
    add(8056,len(kans)==2 and dark==0)
    for t in sorted(trips&DRAGONS): add(8058+t-31)
    add(8063,closed and not tsumo)
    add(8064,basic and pair<27 and all(g.sequence for g in groups))
    n=sum(counts[t]==4 and t not in {g.tile for g in kans} for t in counts)
    add(8065,n>0,n)
    same_pairs=sum(sum(s*9+r in trips for s in range(3))==2 for r in range(9))
    add(8066,same_pairs>0,same_pairs)
    add(8067,len(hidden)==2)
    add(8068,len(kans)==1 and dark==1)
    add(8069,all(t<27 and t%9 not in (0,8) for t in tiles))
    add(8075,len(kans)==1 and dark==0)
    add(8076,len(suits)==2); add(8077,not tiles&HONORS)
    add(8081,tsumo); add(8082,len(kans)==2 and dark==1)
    return trips,nine

def terminal_counts(raw,trips,seat,rnd,nine):
    active=excluded(raw)
    removed=set()
    if any(f in active for f in (8001,8009,8053)): removed|=trips&DRAGONS
    if 8037 in active: removed|=trips&WINDS
    for fan,t in ((8058,31),(8059,32),(8060,33),(8061,rnd),(8062,seat)):
        if fan in active: removed.add(t)
    terminal=trips&ORPHANS-removed
    n=len(terminal)-(1 if nine else 0)
    if n>0: raw[8074]=n

def canonical_key(raw):
    order=(8070,8071,8072,8073,8078,8079,8080)+tuple(sorted(FANS))
    return tuple(raw.get(i,0) for i in order)

def evaluate(data):
    get_profile(data.get('profile',PROFILE))
    hand,win,fixed,method,seat,rnd,source,opening,wall,last,cert=validate(data)
    closed=not any(g.opened for g in fixed)
    concealed=tuple(sorted(hand+(win,)))
    interpretations=shapes(concealed,fixed)
    if not interpretations: raise ValueError('Not a legal winning structure')
    full=Counter(concealed); full.update(t for g in fixed for t in g.tiles)
    physical=waits(tuple(sorted(hand)),fixed)
    formal=waits(tuple(sorted(hand)),fixed,True)
    results=[]
    for shape in interpretations:
        for position in winning_positions(shape,win):
            raw={}
            if shape.kind in ('orphans','unconnected'):
                if shape.kind=='orphans': raw[8006]=1
                elif HONORS<=set(full): raw[8019]=1
                else:
                    raw[8033]=1
                    if set(shape.backbone)<=set(full): raw[8034]=1
                trips=set(); nine=False
            else:
                trips,nine=structural(raw,shape,full,closed,hand,win,method,position)
                if rnd in trips: raw[8061]=1
                if seat in trips: raw[8062]=1
            if method=='tsumo': raw[8081]=1
            if wall: raw[8043 if method=='tsumo' else 8044]=1
            if source=='kan_replacement': raw[8045]=1
            if source=='kakan_ron': raw[8046]=1
            if last: raw[8057]=1
            if opening!='none': raw[{'heaven':8083,'earth':8084,'human':8085}[opening]]=1
            if len(formal)==1 and shape.kind in ('standard','knitted'):
                if position==-1: raw[8080]=1
                elif position>=0:
                    g=shape.groups[position]
                    if g.sequence:
                        if (g.tile%9==0 and win==g.tile+2) or (g.tile%9==6 and win==g.tile): raw[8078]=1
                        elif win==g.tile+1: raw[8079]=1
            patterns=seq_instances(shape.groups,shape.pair) if shape.kind=='standard' else ()
            if patterns:
                # Four-chow patterns take precedence over their contained three-chow patterns.
                four=[p for p in patterns if len(p[1])==4]
                choices=four or patterns
            else: choices=((None,()),)
            for high,support in choices:
                candidate=dict(raw)
                if high: candidate[high]=1
                active=excluded(candidate)
                banned=set().union(*(set(BANS.get(f,())) for f in active)) if active else set()
                plans=small_plans(shape.groups,support,tuple(sorted(banned))) if shape.kind=='standard' else ((),)
                # An empty/underscored subset cannot turn an existing low fan
                # into an 8-fan chicken hand. All these unbanned local fans are
                # worth one, so retain all maximum local accounting plans.
                maximum=max(sum(n for f,n in p) for p in plans)
                plans=tuple(p for p in plans if sum(n for f,n in p)==maximum)
                for plan in plans:
                    scored=dict(candidate); scored.update(plan)
                    terminal_counts(scored,trips,seat,rnd,nine)
                    scored=excluded(scored)
                    if not scored: scored={8042:1}
                    key=project(scored)
                    results.append({'key':key,'raw':scored,'total':fan_total(key),
                                    'shape':shape,'position':position,'support':support,'small':plan})
    best=max(r['total'] for r in results)
    optimal=[r for r in results if r['total']==best]
    canonical=max(optimal,key=lambda r:(canonical_key(r['raw']),r['shape'].pair,
                                       repr(r['shape']),r['position']))
    by_key={r['key']:r for r in optimal}
    def encode(r):
        sh=r['shape']
        return {'key':[list(x) for x in r['key']],'fans':describe(r['key']),
                'raw_key':[[i,n] for i,n in sorted(r['raw'].items())],
                'total':r['total'],'family':sh.kind,'pair':compact((sh.pair,)) if sh.pair>=0 else None,
                'groups':[{'kind':g.kind,'tiles':compact(g.tiles)} for g in sh.groups],
                'backbone':compact(sh.backbone),'win_position':r['position'],
                'high_chow_support':list(r['support']), 'small_fans':[list(x) for x in r['small']]}
    return {'profile':PROFILE,'eligible':best>=8,'total':best,'closed':closed,
            'method':method,'physical_waits':compact(physical),'formal_waits':compact(formal),
            'optimal':[encode(by_key[k]) for k in sorted(by_key)],'canonical':encode(canonical),
            'certificate':cert}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input'); args=parser.parse_args()
    try:
        with open(args.input,encoding='utf-8') as f: result=evaluate(json.load(f))
    except (ValueError,KeyError,TypeError) as exc: parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
