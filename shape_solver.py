"""Overapproximating structural/count-vector model, independently rescored in Python.

Waiting-form and cross-decomposition maxima are checked by the independent
evaluator. Local chow-pair forests and their maxima are encoded exactly.
Rejections block concrete states; accepted vectors permit projection blocking.
"""
from itertools import combinations
from collections import Counter
import z3
from decompose import compact, Group, KNITTED, ORPHANS, HONORS, WINDS, DRAGONS, TERMINALS, GREEN, REVERSIBLE
from rules import FANS
from calc_fan import BANS

def anyof(xs): return z3.Or(list(xs))
def allof(xs): return z3.And(list(xs))
def isum(xs): return z3.Sum(list(xs))
def num(xs): return isum(z3.If(x,1,0) for x in xs)
def member(x,vals): return anyof(x==v for v in vals)

class ShapeSolver:
    def __init__(self, family='standard', timeout_ms=0, seed=0, canonical=False):
        self.family=family
        self.solver=z3.Solver()
        self.solver.set(random_seed=seed)
        if timeout_ms: self.solver.set(timeout=timeout_ms)
        add=self.solver.add
        self.tile=[z3.Int('tile_'+str(i)) for i in range(4)]
        # 0 concealed chow, 1 chi, 2 concealed pung, 3 pon, 4 open kan, 5 ankan
        self.typ=[z3.Int('type_'+str(i)) for i in range(4)]
        self.pair=z3.Int('pair'); self.win=z3.Int('win'); self.position=z3.Int('position')
        self.pairs=[z3.Int('seven_'+str(i)) for i in range(7)]
        self.bone=z3.Int('backbone')
        self.unique=[z3.Bool('unique_'+str(i)) for i in range(34)]
        self.tsumo=z3.Bool('tsumo'); self.seat=z3.Int('seat'); self.round=z3.Int('round')
        self.source=z3.Int('source'); self.opening=z3.Int('opening')
        self.wall=z3.Bool('wall'); self.last=z3.Bool('last_copy')
        add(self.pair>=0,self.pair<34,self.win>=0,self.win<34,
            member(self.seat,WINDS),member(self.round,WINDS),
            self.source>=0,self.source<=2,self.opening>=0,self.opening<=3)
        used_count=4 if family=='standard' else 1 if family=='knitted' else 0
        used=[i<used_count for i in range(4)]
        seq=[z3.And(used[i],self.typ[i]<=1) for i in range(4)]
        trip=[z3.And(used[i],self.typ[i]>=2) for i in range(4)]
        kan=[z3.And(used[i],self.typ[i]>=4) for i in range(4)]
        opened=[z3.And(used[i],member(self.typ[i],(1,3,4))) for i in range(4)]
        fixed=[z3.And(used[i],member(self.typ[i],(1,3,4,5))) for i in range(4)]
        for i in range(4):
            add(self.tile[i]>=0,self.tile[i]<34,self.typ[i]>=0,self.typ[i]<=5)
            if not used[i]: add(self.tile[i]==0,self.typ[i]==0)
            add(z3.Implies(seq[i],z3.And(self.tile[i]<27,self.tile[i]%9<=6)))
        if family=='standard':
            keys=[self.tile[i]*6+self.typ[i] for i in range(4)]
            add(allof(keys[i]<=keys[i+1] for i in range(3)))
        add(self.bone>=0,self.bone<6)
        if family not in ('knitted','unconnected'): add(self.bone==0)
        for i in range(7):
            add(self.pairs[i]>=0,self.pairs[i]<34)
            if family!='seven_pairs': add(self.pairs[i]==0)
        if family=='seven_pairs': add(allof(self.pairs[i]<=self.pairs[i+1] for i in range(6)))
        for t in range(34):
            if family!='unconnected': add(z3.Not(self.unique[t]))
        def bone_has(t): return anyof(z3.And(self.bone==i,member(t,b)) for i,b in enumerate(KNITTED))
        if family=='unconnected':
            add(num(self.unique)==14)
            add(*(z3.Implies(self.unique[t],z3.Or(t in HONORS,bone_has(t))) for t in range(34)))
        if family=='orphans': add(member(self.pair,ORPHANS))
        if family in ('unconnected','seven_pairs'): add(self.pair==0)
        def group_count(i,t):
            return z3.If(used[i], z3.If(seq[i],z3.If(z3.And(t>=self.tile[i],t<=self.tile[i]+2),1,0),
                                       z3.If(self.tile[i]==t,z3.If(kan[i],4,3),0)),0)
        def count(t):
            if family=='seven_pairs': return 2*num(p==t for p in self.pairs)
            if family=='orphans': return z3.If(member(t,ORPHANS),1,0)+z3.If(t==self.pair,1,0)
            if family=='unconnected':
                return isum(z3.If(z3.And(t==j,self.unique[j]),1,0) for j in range(34))
            return 2*z3.If(t==self.pair,1,0)+isum(group_count(i,t) for i in range(4))+(
                z3.If(bone_has(t),1,0) if family=='knitted' else 0)
        self.counts=[count(t) for t in range(34)]
        add(*(c<=4 for c in self.counts))
        if family in ('standard','knitted'):
            choices=[z3.And(self.position==-1,self.win==self.pair)]
            choices.extend(z3.And(self.position==i,z3.Not(fixed[i]),
                z3.If(seq[i],z3.And(self.win>=self.tile[i],self.win<=self.tile[i]+2),self.win==self.tile[i]))
                for i in range(used_count))
            if family=='knitted': choices.append(z3.And(self.position==-2,bone_has(self.win)))
            add(anyof(choices))
        else: add(self.position==-2,count(self.win)>=1)
        self.closed=z3.Not(anyof(opened))
        kans=num(kan); dark=num(z3.And(used[i],self.typ[i]==5) for i in range(4))
        anke=num(z3.And(trip[i],z3.Not(opened[i]),z3.Or(kan[i],self.tsumo,self.position!=i)) for i in range(4))
        own_public=isum(z3.If(opened[i],group_count(i,self.win),0) for i in range(4))
        win_count=count(self.win)
        add(z3.Implies(self.source==1,z3.And(self.tsumo,kans>=1)),
            z3.Implies(self.source==2,z3.And(z3.Not(self.tsumo),win_count==1,z3.Not(self.wall))),
            z3.Implies(self.last,z3.And(win_count-own_public==1,self.source!=2)),
            z3.Implies(own_public==3,z3.Or(self.last,self.source==2)))
        add(z3.Implies(self.opening!=0,z3.And(self.closed,z3.Not(anyof(fixed)),self.source==0,
                                                           z3.Not(self.wall),z3.Not(self.last))))
        add(z3.Implies(self.opening==1,z3.And(self.seat==27,self.tsumo)),
            z3.Implies(self.opening==2,z3.And(self.seat!=27,z3.Not(self.tsumo))),
            z3.Implies(self.opening==3,z3.And(self.seat!=27,z3.Or(self.tsumo,self.seat!=28))))
        if family not in ('standard','seven_pairs','orphans','unconnected','knitted'):
            raise ValueError('Invalid family')
        def has_trip(t): return anyof(z3.And(trip[i],self.tile[i]==t) for i in range(4))
        def only(tiles): return allof(self.counts[t]==0 for t in range(34) if t not in tiles)
        def exists(tiles): return anyof(self.counts[t]>0 for t in tiles)
        def seq_match(support,predicate):
            return z3.And(allof(seq[i] for i in support),predicate([self.tile[i] for i in support]))
        raw={f:z3.IntVal(0) for f in FANS}
        def setf(f,condition,n=1): raw[f]=z3.If(condition,n,0)
        basic=family in ('standard','knitted')
        setf(8000,allof(has_trip(t) for t in WINDS)); setf(8001,allof(has_trip(t) for t in DRAGONS))
        setf(8002,only(GREEN)); nine=[]
        if family=='standard':
            for s in range(3):
                nine.append(z3.And(self.closed,kans==0,allof(
                    self.counts[t]-z3.If(self.win==t,1,0)==(3 if t%9 in (0,8) else 1) if t//9==s
                    else self.counts[t]==0 for t in range(34))))
        setf(8003,anyof(nine)); setf(8004,kans==4)
        seven=family=='seven_pairs'
        setf(8018,seven)
        setf(8005,z3.And(seven,self.pairs[0]<27,self.pairs[0]/9==self.pairs[6]/9,
            allof(self.pairs[i]==self.pairs[0]+i for i in range(7))))
        setf(8006,family=='orphans'); setf(8007,only(TERMINALS))
        setf(8008,z3.And(member(self.pair,WINDS),num(has_trip(t) for t in WINDS)==3))
        setf(8009,z3.And(member(self.pair,DRAGONS),num(has_trip(t) for t in DRAGONS)==2))
        setf(8010,only(HONORS)); setf(8011,anke==4)
        setf(8014,anyof(allof(has_trip(s*9+r+d) for d in range(4)) for s in range(3) for r in range(6)))
        setf(8016,kans==3); setf(8017,z3.And(only(ORPHANS),z3.Not(only(TERMINALS))))
        setf(8020,z3.And(family=='standard',num(trip)==4,only({t for t in range(27) if t%9%2==1})))
        nsuits=num(exists(range(s*9,s*9+9)) for s in range(3))
        setf(8021,z3.And(nsuits==1,z3.Not(exists(HONORS))))
        setf(8023,anyof(allof(has_trip(s*9+r+d) for d in range(3)) for s in range(3) for r in range(7)))
        for f,ranks in ((8024,range(6,9)),(8025,range(3,6)),(8026,range(3)),(8035,range(5,9)),(8036,range(4))):
            setf(f,only({s*9+r for s in range(3) for r in ranks}))
        setf(8030,z3.And(family=='standard',self.pair<27,self.pair%9==4,allof(
            z3.If(seq[i],z3.And(self.tile[i]%9<=4,self.tile[i]%9+2>=4),
                  z3.And(self.tile[i]<27,self.tile[i]%9==4)) for i in range(4))))
        setf(8031,anyof(allof(has_trip(s*9+r) for s in range(3)) for r in range(9)))
        setf(8032,anke==3)
        if family=='unconnected':
            star=allof(self.unique[t] for t in HONORS)
            setf(8019,star); setf(8033,z3.Not(star))
            setf(8034,z3.And(z3.Not(star),allof(z3.Implies(self.bone==i,allof(self.unique[t] for t in b))
                                                              for i,b in enumerate(KNITTED))))
        else: setf(8034,family=='knitted')
        setf(8037,z3.And(num(has_trip(t) for t in WINDS)==3,z3.Not(member(self.pair,WINDS))))
        setf(8039,only(REVERSIBLE))
        setf(8041,anyof(allof(has_trip(s*9+r) for s,r in enumerate(perm))
            for start in range(7) for perm in __import__('itertools').permutations(range(start,start+3))))
        setf(8043,z3.And(self.wall,self.tsumo)); setf(8044,z3.And(self.wall,z3.Not(self.tsumo)))
        setf(8045,self.source==1);setf(8046,self.source==2)
        setf(8047,num(trip)==4);setf(8048,z3.And(nsuits==1,exists(HONORS)))
        setf(8050,z3.And(nsuits==3,exists(WINDS),exists(DRAGONS)))
        setf(8051,z3.And(num(opened)==4,z3.Not(self.tsumo)))
        setf(8052,z3.And(kans==2,dark==2));setf(8053,num(has_trip(t) for t in DRAGONS)==2)
        setf(8054,z3.And(family=='standard',member(self.pair,ORPHANS),allof(
            z3.If(seq[i],member(self.tile[i]%9,(0,6)),member(self.tile[i],ORPHANS)) for i in range(4))))
        setf(8055,z3.And(self.closed,self.tsumo));setf(8056,z3.And(kans==2,dark==0))
        setf(8057,z3.Or(self.last,self.source==2))
        for f,t in ((8058,31),(8059,32),(8060,33),(8061,self.round),(8062,self.seat)):
            setf(f,has_trip(t))
        setf(8063,z3.And(self.closed,z3.Not(self.tsumo)))
        setf(8064,z3.And(basic,self.pair<27,num(trip)==0))
        quad=num(z3.And(self.counts[t]==4,z3.Not(anyof(z3.And(kan[i],self.tile[i]==t) for i in range(4)))) for t in range(34))
        raw[8065]=quad
        raw[8066]=num(num(has_trip(s*9+r) for s in range(3))==2 for r in range(9))
        setf(8067,anke==2);setf(8068,z3.And(kans==1,dark==1))
        setf(8069,only(set(range(27))-TERMINALS))
        setf(8075,z3.And(kans==1,dark==0));setf(8076,nsuits==2)
        setf(8077,z3.Not(exists(HONORS)));setf(8081,self.tsumo)
        setf(8082,z3.And(kans==2,dark==1))
        for i in range(3): setf(8083+i,self.opening==i+1)
        if family in ('orphans','unconnected'):
            # Special branch does not inherit ordinary face/colour/closed rewards.
            keep={8006,8019,8033,8034,8043,8044,8045,8046,8057,8081,8083,8084,8085}
            raw={f:v if f in keep else z3.IntVal(0) for f,v in raw.items()}
        # All compatible high-chow supports; choose one, independently checked later.
        patterns=[]
        if family=='standard':
            for support in combinations(range(4),3):
                a,b,c=[self.tile[i] for i in support]
                ss=z3.And(a/9==b/9,b/9==c/9)
                ds=z3.Distinct(a/9,b/9,c/9)
                ranks=[a%9,b%9,c%9]
                def rankset(offsets):
                    return anyof(allof(ranks[i]==p[i] for i in range(3))
                        for p in __import__('itertools').permutations(offsets))
                conditions={8022:z3.And(a==b,b==c),8027:z3.And(ss,rankset((0,3,6))),
                    8029:z3.And(ss,z3.Or(z3.And(b-a==1,c-b==1),z3.And(b-a==2,c-b==2))),
                    8038:z3.And(ds,rankset((0,3,6))),8040:z3.And(ds,ranks[0]==ranks[1],ranks[1]==ranks[2]),
                    8049:z3.And(ds,anyof(rankset((r,r+1,r+2)) for r in range(5)))}
                for f,cond in conditions.items(): patterns.append((f,support,z3.And(allof(seq[i] for i in support),cond)))
            a,b,c,d=self.tile
            allseq=allof(seq); same=z3.And(a/9==b/9,b/9==c/9,c/9==d/9)
            patterns.extend([
                (8013,(0,1,2,3),z3.And(allseq,a==b,b==c,c==d)),
                (8015,(0,1,2,3),z3.And(allseq,same,z3.Or(z3.And(b-a==1,c-b==1,d-c==1),z3.And(b-a==2,c-b==2,d-c==2)))),
                (8012,(0,1,2,3),z3.And(allseq,same,a%9==0,a==b,c%9==6,c==d,self.pair==a+4)),
                (8028,(0,1,2,3),z3.And(allseq,a/9==b/9,c/9==d/9,a/9!=c/9,a%9==0,b%9==6,c%9==0,d%9==6,
                    self.pair<27,self.pair%9==4,self.pair/9!=a/9,self.pair/9!=c/9))])
        selected=[z3.Bool('high_'+str(i)) for i in range(len(patterns))]
        any_four=anyof(cond for f,support,cond in patterns if len(support)==4)
        add(num(selected)==z3.If(anyof(p[2] for p in patterns),1,0))
        for i,(f,support,cond) in enumerate(patterns):
            add(z3.Implies(selected[i],cond))
            if len(support)==3: add(z3.Implies(any_four,z3.Not(selected[i])))
        for f in {p[0] for p in patterns}:
            setf(f,anyof(selected[i] for i,p in enumerate(patterns) if p[0]==f))
        # Pair-fan supports: total and repeated-type matching constraints form a
        # superset of the independent evaluator's legal forest plans.
        pair_choices=[]
        for i,j in combinations(range(4),2):
            a,b=self.tile[i],self.tile[j]
            conditions={8070:a==b,8071:z3.And(a%9==b%9,a/9!=b/9),
                        8072:z3.And(a/9==b/9,b-a==3),8073:z3.And(a/9==b/9,a%9==0,b%9==6)}
            for f,cond in conditions.items():
                chosen=z3.Bool(f'pair_{f}_{i}_{j}')
                add(z3.Implies(chosen,z3.And(seq[i],seq[j],cond)))
                for h,(_,support,_) in enumerate(patterns):
                    if i in support and j in support: add(z3.Implies(selected[h],z3.Not(chosen)))
                pair_choices.append((f,i,j,chosen))
        pair_sum=num(x[3] for x in pair_choices)
        add(pair_sum<=z3.If(num(seq)>0,num(seq)-1,0))
        for h,(_,support,_) in enumerate(patterns):
            add(z3.Implies(selected[h],pair_sum<=(0 if len(support)==4 else 1)))
        for f in (8070,8071,8072,8073):
            raw[f]=num(x[3] for x in pair_choices if x[0]==f)
            for i in range(4): add(num(x[3] for x in pair_choices if x[0]==f and i in x[1:3])<=1)
        wait_kind=self.wait_kind=z3.Int('wait_kind'); add(wait_kind>=0,wait_kind<=3)
        add(z3.Implies(wait_kind==3,z3.And(basic,self.position==-1)))
        edge=anyof(z3.And(self.position==i,seq[i],z3.Or(
            z3.And(self.tile[i]%9==0,self.win==self.tile[i]+2),
            z3.And(self.tile[i]%9==6,self.win==self.tile[i]))) for i in range(4))
        middle=anyof(z3.And(self.position==i,seq[i],self.win==self.tile[i]+1) for i in range(4))
        self.wait_expression=z3.If(self.position==-1,3,z3.If(edge,1,z3.If(middle,2,0)))
        add(z3.Implies(wait_kind==1,edge),z3.Implies(wait_kind==2,middle))
        setf(8078,wait_kind==1);setf(8079,wait_kind==2);setf(8080,wait_kind==3)
        # Apply global bans in the same precedence order, independently recompute
        # eligible terminal-pung identities without double-subtracting winds.
        order=sorted(FANS,key=lambda f:(-FANS[f]['value'],f))
        active={}
        for f in order:
            blockers=[active[h] for h in active if f in BANS.get(h,())]
            active[f]=z3.And(raw[f]>0,z3.Not(anyof(blockers)))
        counts=[]
        for t in sorted(ORPHANS):
            removed=[]
            if t in DRAGONS: removed.extend(active[f] for f in (8001,8009,8053,8058+t-31))
            if t in WINDS: removed.append(active[8037])
            removed.extend((z3.And(active[8061],self.round==t),z3.And(active[8062],self.seat==t)))
            counts.append(z3.And(has_trip(t),z3.Not(anyof(removed))))
        raw[8074]=num(counts)-z3.If(active[8003],1,0)
        # Terminal pung never controls other exclusions, so one update suffices.
        active[8074]=z3.And(raw[8074]>0,z3.Not(anyof(active[h] for h in active if 8074 in BANS.get(h,()))))
        self.vector={f:z3.If(active[f],raw[f],0) for f in FANS}
        if family=='standard':
            # There are only six possible chow-pair edges. Enumerate their
            # forests symbolically, after high-fan exclusions. Requiring a
            # maximum local plan avoids millions of deliberately underscored
            # candidates, including false chicken hands. This does not decide
            # which physical-hand decomposition wins globally.
            edges=list(combinations(range(4),2))
            small=(8070,8071,8072,8073)
            available={}
            for e,(i,j) in enumerate(edges):
                a,b=self.tile[i],self.tile[j]
                geometry={8070:a==b,8071:z3.And(a%9==b%9,a/9!=b/9),
                          8072:z3.And(a/9==b/9,b-a==3),
                          8073:z3.And(a/9==b/9,a%9==0,b%9==6)}
                internal=anyof(selected[h] for h,(_,support,_) in enumerate(patterns)
                               if i in support and j in support)
                for f in small:
                    banned=anyof(active[h] for h in active if f in BANS.get(h,()))
                    available[e,f]=z3.And(seq[i],seq[j],geometry[f],z3.Not(internal),z3.Not(banned))
            plans=[]
            for mask in range(1<<len(edges)):
                chosen=[e for e in range(len(edges)) if mask>>e&1]
                if len(chosen)>3:continue
                parent=list(range(4))
                def root(i):
                    while parent[i]!=i:i=parent[i]
                    return i
                cyclic=False
                for e in chosen:
                    i,j=edges[e];a,b=root(i),root(j)
                    if a==b:cyclic=True;break
                    parent[a]=b
                if cyclic:continue
                legal=[anyof(available[e,f] for f in small) for e in chosen]
                if len(chosen)>1:
                    legal.append(z3.Not(anyof(selected)))
                for e,d in combinations(chosen,2):
                    if set(edges[e])&set(edges[d]):
                        legal.extend(z3.Not(z3.And(available[e,f],available[d,f])) for f in small)
                values={f:num(available[e,f] for e in chosen) for f in small}
                plans.append((allof(legal),values))
            def local_score(values):
                total=isum(values[f] for f in small)
                if not canonical:return total
                return total*256+values[8070]*64+values[8071]*16+values[8072]*4+values[8073]
            actual=local_score(self.vector)
            add(anyof(z3.And(legal,allof(self.vector[f]==values[f] for f in small))
                      for legal,values in plans))
            add(*(z3.Implies(legal,actual>=local_score(values)) for legal,values in plans))
        set_no_fan=allof(self.vector[f]==0 for f in FANS if f!=8042)
        self.vector[8042]=z3.If(set_no_fan,1,0)
        self.total=isum(self.vector[f]*FANS[f]['value'] for f in FANS)
        add(self.total>=8)
        self.projection={f:(self.vector[f]+self.vector[8059]+self.vector[8060] if f==8058 else self.vector[f])
                         for f in FANS if f not in (8059,8060)}
        self.state_vars=(self.tile+self.typ+[self.pair,self.win]+self.pairs+[self.bone]+self.unique+
                         [self.tsumo,self.seat,self.round,self.source,self.opening,self.wall,self.last])

    def block_key(self,key):
        target=dict(key)
        self.solver.add(anyof(v!=target.get(f,0) for f,v in self.projection.items()))

    def block_state(self,model):
        self.block_saved_state(self.state_values(model))

    def state_values(self,model):
        out={}
        for v in self.state_vars:
            x=model.eval(v,model_completion=True)
            out[str(v)]=z3.is_true(x) if z3.is_bool(x) else x.as_long()
        return out

    def block_saved_state(self,values):
        # Without a wind pung, neither wind variable changes scoring in any
        # interpretation of this physical hand. Honor tiles cannot form chows;
        # a pair/quad used in seven pairs cannot become a wind pung elsewhere.
        # Opening-event legality can still depend on seat, so retain that seat.
        n=4 if self.family=='standard' else 1 if self.family=='knitted' else 0
        wind_pung=any(values['type_'+str(i)]>=2 and 27<=values['tile_'+str(i)]<=30
                      for i in range(n))
        ignored=set() if wind_pung else {'round'}
        if not wind_pung and values['opening']==0: ignored.add('seat')
        self.solver.add(anyof(v!=values[str(v)] for v in self.state_vars if str(v) not in ignored))

    def wait_values(self,model):
        if self.family=='standard': vs=self.tile+self.typ+[self.pair,self.win]
        elif self.family=='knitted': vs=[self.tile[0],self.typ[0],self.pair,self.win,self.bone]
        elif self.family=='seven_pairs': vs=self.pairs+[self.win]
        elif self.family=='orphans': vs=[self.pair,self.win]
        else: vs=self.unique+[self.win,self.bone]
        values=self.state_values(model)
        return {str(v):values[str(v)] for v in vs}

    def learn_waits(self,values,unique):
        vars_by_name={str(v):v for v in self.state_vars}
        match=allof(vars_by_name[n]==v for n,v in values.items())
        expected=self.wait_expression if unique and self.family in ('standard','knitted') else 0
        self.solver.add(z3.Implies(match,self.wait_kind==expected))

    def witness(self,model):
        def value(v):
            x=model.eval(v,model_completion=True)
            return z3.is_true(x) if z3.is_bool(x) else x.as_long()
        family=self.family
        groups=[]; fixed=[]; concealed=[]
        n=4 if family=='standard' else 1 if family=='knitted' else 0
        kinds=('sequence','chi','triplet','pon','minkan','ankan')
        for i in range(n):
            g=Group(kinds[value(self.typ[i])],value(self.tile[i])); groups.append(g)
            if g.fixed: fixed.append(g)
            else: concealed.extend(g.tiles)
        if family in ('standard','knitted'): concealed.extend([value(self.pair)]*2)
        if family=='knitted': concealed.extend(KNITTED[value(self.bone)])
        if family=='seven_pairs': concealed=[value(p) for p in self.pairs for _ in range(2)]
        if family=='orphans': concealed=list(ORPHANS)+[value(self.pair)]
        if family=='unconnected': concealed=[t for t,v in enumerate(self.unique) if value(v)]
        win=value(self.win); concealed.remove(win)
        source=('normal','kan_replacement','kakan_ron')[value(self.source)]
        public=sum(g.tiles.count(win) for g in fixed if g.opened)
        external=3 if source=='kakan_ron' else 3-public if value(self.last) else 0
        data={'hand':compact(concealed),'win':compact((win,)),
              'melds':[{'kind':g.kind,'tiles':compact(g.tiles)} for g in fixed],
              'method':'tsumo' if value(self.tsumo) else 'ron',
              'seat_wind':compact((value(self.seat),)),'round_wind':compact((value(self.round),)),
              'context':{'draw_source':source,'wall_empty':value(self.wall),
                         'opening':('none','heaven','earth','human')[value(self.opening)],
                         'visible_before_win':compact([win]*external)}}
        key=tuple((f,value(v)) for f,v in self.projection.items() if value(v))
        return data,key
