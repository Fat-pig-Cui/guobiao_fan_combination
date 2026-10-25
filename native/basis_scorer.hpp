// Independent C++ evaluator for editor_no_flower_v1. Python remains the oracle.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <fstream>
#include <functional>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace basis {
using Counts = std::array<uint8_t,34>;
using Fans = std::array<uint8_t,86>;
constexpr uint64_t winds = uint64_t(15)<<27, dragons = uint64_t(7)<<31;
constexpr uint64_t honors = winds|dragons;
inline uint64_t bit(int t) { return uint64_t(1)<<t; }
inline bool terminal(int t) { return t<27 && (t%9==0 || t%9==8); }
inline bool orphan(int t) { return t>=27 || terminal(t); }
inline int pop(uint64_t x) { int n=0; while(x) { x&=x-1; ++n; } return n; }
inline uint64_t mask(const Counts& c) { uint64_t m=0; for(int t=0;t<34;++t) if(c[t]) m|=bit(t); return m; }
inline bool only(uint64_t m,uint64_t allowed) { return !(m&~allowed); }
inline uint64_t tileset(std::initializer_list<int> ts) { uint64_t m=0; for(int t:ts)m|=bit(t);return m; }
inline uint64_t orphan_mask() { return honors|tileset({0,8,9,17,18,26}); }
struct Group {
    // 0 concealed chow, 1 chi, 2 concealed pung, 3 pon, 4 minkan, 5 ankan.
    int kind=0,tile=0;
    bool seq() const { return kind<2; }
    bool fixed() const { return kind==1 || kind>=3; }
    bool open() const { return kind==1 || kind==3 || kind==4; }
    bool kan() const { return kind>=4; }
    bool same(const Group& g) const { return seq()==g.seq() && tile==g.tile; }
};
inline void add(Counts& c,Group g,int delta=1,bool geometric=false) {
    if(g.seq()) for(int j=0;j<3;++j)c[g.tile+j]+=delta;
    else c[g.tile]+=delta*((g.kan()&&!geometric)?4:3);
}
inline void sort_fixed(std::vector<Group>& gs) {
    // Python sorts Group by its textual kind before its tile.
    auto rank=[](int k) { return k==5?0:k==1?1:k==4?2:3; };
    std::sort(gs.begin(),gs.end(),[&](Group a,Group b){return std::make_pair(rank(a.kind),a.tile)<std::make_pair(rank(b.kind),b.tile);});
}
enum { STANDARD, SEVEN, ORPHANS, UNCONNECTED, KNITTED };
struct Shape { int kind=STANDARD,pair=-1; std::vector<Group> groups; uint64_t bone=0; };
inline std::vector<uint64_t> backbones() {
    std::vector<uint64_t> out; std::array<int,3> p{0,1,2};
    do { uint64_t m=0;for(int s=0;s<3;++s)for(int r=p[s];r<9;r+=3)m|=bit(9*s+r);out.push_back(m); }
    while(std::next_permutation(p.begin(),p.end())); return out;
}
inline const std::vector<uint64_t>& bones() { static auto b=backbones(); return b; }
inline bool meldable(Counts& c,int need) {
    int t=0;while(t<34&&!c[t])++t;
    if(t==34)return need==0;
    if(need<=0)return false;
    if(c[t]>=3) {c[t]-=3;bool ok=meldable(c,need-1);c[t]+=3;if(ok)return true;}
    if(t<27&&t%9<=6&&c[t+1]&&c[t+2]) {
        --c[t];--c[t+1];--c[t+2];bool ok=meldable(c,need-1);++c[t];++c[t+1];++c[t+2];if(ok)return true;
    } return false;
}
inline void meld_shapes(Counts& c,int need,std::vector<Group>& gs,int pair,int kind,uint64_t bone,std::vector<Shape>& out) {
    int t=0;while(t<34&&!c[t])++t;
    if(t==34) {if(need==0)out.push_back({kind,pair,gs,bone});return;}
    if(need<=0)return;
    if(c[t]>=3) {c[t]-=3;gs.push_back({2,t});meld_shapes(c,need-1,gs,pair,kind,bone,out);gs.pop_back();c[t]+=3;}
    if(t<27&&t%9<=6&&c[t+1]&&c[t+2]) {
        --c[t];--c[t+1];--c[t+2];gs.push_back({0,t});meld_shapes(c,need-1,gs,pair,kind,bone,out);gs.pop_back();++c[t];++c[t+1];++c[t+2];
    }
}
inline std::vector<Shape> decompositions(Counts c) {
    std::vector<Shape> out;std::vector<Group> gs;int n=0;for(auto x:c)n+=x;
    if(n!=14)throw std::runtime_error("basis must contain fourteen geometric tiles");
    for(int p=0;p<34;++p)if(c[p]>=2) {c[p]-=2;meld_shapes(c,4,gs,p,STANDARD,0,out);c[p]+=2;}
    bool even=true;int distinct=0;for(auto x:c){even&=x%2==0;distinct+=x!=0;}
    if(even)out.push_back({SEVEN,-1,{},0});
    uint64_t m=mask(c);
    if(m==orphan_mask()&&distinct==13)out.push_back({ORPHANS,-1,{},0});
    if(distinct==14)for(uint64_t b:bones())if(only(m,b|honors))out.push_back({UNCONNECTED,-1,{},b});
    for(uint64_t b:bones())if((m&b)==b) {
        for(int t=0;t<27;++t)if(b&bit(t))--c[t];
        for(int p=0;p<34;++p)if(c[p]>=2){c[p]-=2;meld_shapes(c,1,gs,p,KNITTED,b,out);c[p]+=2;}
        for(int t=0;t<27;++t)if(b&bit(t))++c[t];
    }
    return out;
}
inline bool winning(Counts c,int fixed) {
    for(int p=0;p<34;++p)if(c[p]>=2){c[p]-=2;bool ok=meldable(c,4-fixed);c[p]+=2;if(ok)return true;}
    uint64_t m=mask(c);int distinct=pop(m);
    if(!fixed) {
        bool even=true;for(auto x:c)even&=x%2==0;
        if(even|| (m==orphan_mask()&&distinct==13))return true;
        if(distinct==14)for(auto b:bones())if(only(m,b|honors))return true;
    }
    if(fixed<=1)for(uint64_t b:bones())if((m&b)==b) {
        for(int t=0;t<27;++t)if(b&bit(t))--c[t];bool ok=false;
        for(int p=0;p<34&&!ok;++p)if(c[p]>=2){c[p]-=2;ok=meldable(c,1-fixed);c[p]+=2;}
        for(int t=0;t<27;++t)if(b&bit(t))++c[t];if(ok)return true;
    }
    return false;
}
inline std::vector<Shape> compatible(const std::vector<Shape>& all,const std::vector<Group>& fixed) {
    std::vector<Shape> out;
    for(const auto& s:all) {
        if(s.kind!=STANDARD&&s.kind!=KNITTED){if(fixed.empty())out.push_back(s);continue;}
        auto rest=s.groups;bool ok=true;
        for(auto g:fixed){auto i=std::find_if(rest.begin(),rest.end(),[&](Group x){return x.same(g);});if(i==rest.end()){ok=false;break;}rest.erase(i);}
        if(ok){Shape v=s;v.groups=fixed;v.groups.insert(v.groups.end(),rest.begin(),rest.end());out.push_back(v);}
    }return out;
}
struct Rules {
    std::array<int,86> values{};std::array<std::vector<int>,86> bans;std::vector<int> order;
    explicit Rules(const std::string& path) {
        std::ifstream f(path);std::string magic;f>>magic;if(magic!="MCRRULE1")throw std::runtime_error("invalid rules file");
        for(auto& v:values)f>>v;
        for(int i=0;i<86;++i){int n;f>>n;if(!f||n<0||n>86)throw std::runtime_error("invalid bans");while(n--){int v;f>>v;if(v<0||v>=86)throw std::runtime_error("invalid fan id");bans[i].push_back(v);}order.push_back(i);}
        if(!f)throw std::runtime_error("truncated rules file");
        std::sort(order.begin(),order.end(),[&](int a,int b){return values[a]!=values[b]?values[a]>values[b]:a<b;});
    }
    Fans excluded(Fans f) const { for(int i:order)if(f[i])for(int j:bans[i])f[j]=0;return f; }
    int total(const Fans& f) const {int n=0;for(int i=0;i<86;++i)n+=f[i]*values[i];return n;}
};
inline Fans project(Fans f) { f[58]+=f[59]+f[60];f[59]=f[60]=0;return f; }
inline bool canonical_less(const Fans& a,const Fans& b) {
    for(int i:{70,71,72,73,78,79,80})if(a[i]!=b[i])return a[i]<b[i];return a<b;
}
struct Pattern { int fan=-1,support=0; };
inline std::vector<Pattern> patterns(const Shape& s) {
    std::vector<int> ids;for(int i=0;i<int(s.groups.size());++i)if(s.groups[i].seq())ids.push_back(i);
    std::vector<Pattern> out;
    for(int a=0;a<int(ids.size());++a)for(int b=a+1;b<int(ids.size());++b)for(int c=b+1;c<int(ids.size());++c) {
        std::array<int,3> ts{s.groups[ids[a]].tile,s.groups[ids[b]].tile,s.groups[ids[c]].tile};std::sort(ts.begin(),ts.end());
        std::array<int,3> rs{ts[0]%9,ts[1]%9,ts[2]%9};std::sort(rs.begin(),rs.end());
        int support=(1<<ids[a])|(1<<ids[b])|(1<<ids[c]);std::set<int> suits{ts[0]/9,ts[1]/9,ts[2]/9};
        auto put=[&](int f){out.push_back({f,support});};
        if(ts[0]==ts[2])put(22);
        if(suits.size()==1){if(rs==std::array<int,3>{0,3,6})put(27);if(rs[1]-rs[0]==rs[2]-rs[1]&&(rs[1]-rs[0]==1||rs[1]-rs[0]==2))put(29);}
        if(suits.size()==3){if(rs==std::array<int,3>{0,3,6})put(38);if(rs[0]==rs[2])put(40);if(rs[1]==rs[0]+1&&rs[2]==rs[0]+2)put(49);}
    }
    std::vector<Pattern> four;
    if(ids.size()==4) {
        std::array<int,4> ts{},rs{};std::set<int> suits;
        for(int i=0;i<4;++i){ts[i]=s.groups[i].tile;rs[i]=ts[i]%9;suits.insert(ts[i]/9);}std::sort(ts.begin(),ts.end());std::sort(rs.begin(),rs.end());
        if(ts[0]==ts[3])four.push_back({13,15});
        if(suits.size()==1&&((rs[1]==rs[0]+1&&rs[2]==rs[0]+2&&rs[3]==rs[0]+3)||rs==std::array<int,4>{0,2,4,6}))four.push_back({15,15});
        if(suits.size()==1&&rs==std::array<int,4>{0,0,6,6}&&s.pair==ts[0]/9*9+4)four.push_back({12,15});
        if(suits.size()==2&&s.pair<27&&!suits.count(s.pair/9)&&s.pair%9==4){bool ok=true;for(int suit:suits){std::vector<int> r;for(int t:ts)if(t/9==suit)r.push_back(t%9);ok&=r==std::vector<int>{0,6};}if(ok)four.push_back({28,15});}
    }
    if(!four.empty())return four;if(out.empty())out.push_back({-1,0});return out;
}
inline std::string pattern_key(const Shape& s) {
    std::string key;key+=char(s.pair+1);
    for(auto g:s.groups){key+=char(g.seq());key+=char(g.tile);}return key;
}
inline std::vector<Fans> small_plans(const Shape& s,int support,const std::array<bool,86>& banned) {
    if(pop(support)==4)return {Fans{}};
    struct Edge{int fan,mask;};std::vector<Edge> edges;
    for(int i=0;i<int(s.groups.size());++i)if(s.groups[i].seq())for(int j=i+1;j<int(s.groups.size());++j)if(s.groups[j].seq()) {
        int a=s.groups[i].tile,b=s.groups[j].tile,f=-1;
        if(a==b)f=70;else if(a%9==b%9&&a/9!=b/9)f=71;else if(a/9==b/9&&std::abs(a-b)==3)f=72;else if(a/9==b/9&&std::min(a%9,b%9)==0&&std::max(a%9,b%9)==6)f=73;
        int m=(1<<i)|(1<<j);if(f>=0&&!banned[f]&&(support&m)!=m)edges.push_back({f,m});
    }
    std::set<Fans> results;Fans counts{};std::array<int,4> labels{};int best=-1;
    std::function<void(int,int,int)> visit=[&](int remaining,int used,int n){
        if(n>best){best=n;results.clear();}if(n==best)results.insert(counts);
        if(support&&n>=1)return;
        for(int i=0;i<int(edges.size());++i)if(remaining>>i&1){auto e=edges[i];int k=e.fan-70;if((labels[k]&e.mask)||(used&e.mask)==e.mask)continue;
            int old=labels[k];labels[k]|=e.mask;++counts[e.fan];visit(remaining&~(1<<i),used|e.mask,n+1);--counts[e.fan];labels[k]=old;}
    };visit((1<<edges.size())-1,support,0);return {results.begin(),results.end()};
}
struct Structural { Fans raw{};uint64_t trips=0;bool nine=false;std::vector<Pattern> patterns; };
inline Structural structural(const Shape& s,const Counts& full,const Counts& hand,bool closed,int win,bool tsumo,int pos) {
    Structural z;Fans& f=z.raw;uint64_t m=mask(full),trips=0;int kans=0,dark=0,hidden=0,opened=0;uint64_t kan_tiles=0;bool basic=s.kind==STANDARD||s.kind==KNITTED;
    for(int i=0;i<int(s.groups.size());++i){auto g=s.groups[i];if(!g.seq())trips|=bit(g.tile);kans+=g.kan();dark+=g.kind==5;opened+=g.open();if(g.kan())kan_tiles|=bit(g.tile);hidden+=!g.seq()&&!g.open()&&(g.kan()||tsumo||i!=pos);}
    z.trips=trips;
    auto put=[&](int i,bool yes=true,int n=1){if(yes)f[i]=uint8_t(n);};
    put(0,(trips&winds)==winds);put(1,(trips&dragons)==dragons);put(2,only(m,tileset({19,20,21,23,25,32})));
    if(basic&&closed&&!kans)for(int suit=0;suit<3;++suit){bool ok=true;for(int t=0;t<34;++t)ok&=hand[t]==(t/9==suit?(t%9==0||t%9==8?3:1):0);z.nine|=ok;}
    put(3,z.nine);put(4,kans==4);
    if(s.kind==SEVEN){put(18);if(pop(m)==7){int lo=0;while(!(m&bit(lo)))++lo;bool ok=lo<27&&lo%9<=2;for(int t=0;t<34;++t)ok&=full[t]==(t>=lo&&t<lo+7?2:0);put(5,ok);}}
    put(7,only(m,orphan_mask()&~honors));put(8,s.pair>=27&&s.pair<=30&&pop(trips&winds)==3);put(9,s.pair>=31&&pop(trips&dragons)==2);put(10,only(m,honors));put(11,hidden==4);
    bool four=false,three=false;for(int suit=0;suit<3;++suit)for(int r=0;r<7;++r){bool ok=true;for(int j=0;j<3;++j)ok&=bool(trips&bit(suit*9+r+j));three|=ok;if(r<6)four|=ok&&bool(trips&bit(suit*9+r+3));}put(14,four);put(16,kans==3);put(17,only(m,orphan_mask())&&!only(m,orphan_mask()&~honors));
    uint64_t even=0,no_terminal=0;for(int t=0;t<27;++t){if(t%9%2==1)even|=bit(t);if(!terminal(t))no_terminal|=bit(t);}
    put(20,s.kind==STANDARD&&pop(trips)==4&&only(m,even));int suits=0;for(int suit=0;suit<3;++suit)suits+=bool(m&(uint64_t(511)<<(suit*9)));put(21,suits==1&&!(m&honors));put(23,three);
    bool big=true,mid=true,small=true,gt=true,lt=true;for(int t=0;t<34;++t)if(full[t]){big&=t<27&&t%9>=6;mid&=t<27&&t%9>=3&&t%9<=5;small&=t<27&&t%9<=2;gt&=t<27&&t%9>=5;lt&=t<27&&t%9<=3;}
    put(24,big);put(25,mid);put(26,small);bool allfive=basic&&s.pair>=0&&s.pair<27&&s.pair%9==4&&!s.bone;
    for(auto g:s.groups)allfive&=g.tile<27&&(g.seq()?(g.tile%9<=4&&g.tile%9+2>=4):g.tile%9==4);put(30,allfive);
    bool triple=false;int doubles=0;for(int r=0;r<9;++r){int n=0;for(int suit=0;suit<3;++suit)n+=bool(trips&bit(suit*9+r));triple|=n==3;doubles+=n==2;}put(31,triple);put(32,hidden==3);put(34,s.kind==KNITTED);put(35,gt);put(36,lt);put(37,pop(trips&winds)==3&&!(s.pair>=27&&s.pair<=30));
    put(39,only(m,tileset({9,10,11,12,13,16,17,19,21,22,23,25,26,31})));
    bool mixed=false;for(int a=0;a<27;++a)if(trips&bit(a))for(int b=a+1;b<27;++b)if(trips&bit(b))for(int c=b+1;c<27;++c)if(trips&bit(c)){std::array<int,3> rs{a%9,b%9,c%9};std::sort(rs.begin(),rs.end());mixed|=a/9!=b/9&&b/9!=c/9&&a/9!=c/9&&rs[1]==rs[0]+1&&rs[2]==rs[0]+2;}put(41,mixed);
    put(47,s.groups.size()==4&&pop(trips)==4);put(48,suits==1&&bool(m&honors));put(50,suits==3&&bool(m&winds)&&bool(m&dragons));put(51,s.groups.size()==4&&opened==4&&!tsumo);put(52,kans==2&&dark==2);put(53,pop(trips&dragons)==2);
    bool outside=basic&&s.pair>=0&&orphan(s.pair)&&!s.bone;for(auto g:s.groups)outside&=g.seq()?(g.tile%9==0||g.tile%9==6):orphan(g.tile);put(54,outside);put(55,closed&&tsumo);put(56,kans==2&&dark==0);
    for(int t=31;t<34;++t)put(58+t-31,bool(trips&bit(t)));put(63,closed&&!tsumo);put(64,basic&&s.pair>=0&&s.pair<27&&!trips);int quads=0;for(int t=0;t<34;++t)quads+=full[t]==4&&!(kan_tiles&bit(t));put(65,quads>0,quads);put(66,doubles>0,doubles);put(67,hidden==2);put(68,kans==1&&dark==1);put(69,only(m,no_terminal));put(75,kans==1&&dark==0);put(76,suits==2);put(77,!(m&honors));put(81,tsumo);put(82,kans==2&&dark==1);
    (void)win;return z;
}
struct Event { int method=0,source=0,opening=0,wall=0,external=0,seat=28,round=27;bool last=false; };
struct Result { int total=-1;std::set<Fans> optimal;Fans canonical{}; };
struct Prepared { const Shape* shape=nullptr;int position=-2;Structural data; };
inline std::vector<Prepared> prepare(const std::vector<Shape>& shapes,const Counts& full,const Counts& hand,bool closed,int win,bool tsumo,bool unique,
                                    std::map<std::string,std::vector<Pattern>>& pattern_cache) {
    std::vector<Prepared> out;
    for(const auto& s:shapes){std::vector<int> ps;
        if(s.kind==SEVEN||s.kind==ORPHANS||s.kind==UNCONNECTED)ps={-2};
        else {if(s.pair==win)ps.push_back(-1);for(int i=0;i<int(s.groups.size());++i){auto g=s.groups[i];if(!g.fixed()&&(g.seq()?(win>=g.tile&&win<=g.tile+2):win==g.tile))ps.push_back(i);}if(s.bone&bit(win))ps.push_back(-2);}
        for(int pos:ps){Structural z;
            if(s.kind==ORPHANS)z.raw[6]=1;
            else if(s.kind==UNCONNECTED){if((mask(full)&honors)==honors)z.raw[19]=1;else{z.raw[33]=1;if((mask(full)&s.bone)==s.bone)z.raw[34]=1;}}
            else z=structural(s,full,hand,closed,win,tsumo,pos);
            if(s.kind==STANDARD){auto key=pattern_key(s);auto i=pattern_cache.find(key);if(i==pattern_cache.end())i=pattern_cache.emplace(std::move(key),patterns(s)).first;z.patterns=i->second;}
            else z.patterns={{-1,0}};
            if(unique&&(s.kind==STANDARD||s.kind==KNITTED)){
                if(pos==-1)z.raw[80]=1;else if(pos>=0){auto g=s.groups[pos];if(g.seq()){if((g.tile%9==0&&win==g.tile+2)||(g.tile%9==6&&win==g.tile))z.raw[78]=1;else if(win==g.tile+1)z.raw[79]=1;}}
            }out.push_back({&s,pos,std::move(z)});
        }
    }return out;
}
inline Result score(const Rules& rules,const std::vector<Prepared>& prepared,const Event& e,
                    std::map<std::string,std::vector<Fans>>& plan_cache) {
    Result result;Fans canonical_raw{};
    for(const auto& p:prepared){const Shape& s=*p.shape;const auto& z=p.data;Fans raw=z.raw;
        if(s.kind!=ORPHANS&&s.kind!=UNCONNECTED){if(z.trips&bit(e.round))raw[61]=1;if(z.trips&bit(e.seat))raw[62]=1;}
        if(e.method)raw[81]=1;if(e.wall)raw[e.method?43:44]=1;if(e.source==1)raw[45]=1;if(e.source==2)raw[46]=1;if(e.last)raw[57]=1;if(e.opening)raw[82+e.opening]=1;
        for(auto pattern:z.patterns){Fans candidate=raw;if(pattern.fan>=0)candidate[pattern.fan]=1;Fans active=rules.excluded(candidate);std::array<bool,86> banned{};for(int i=0;i<86;++i)if(active[i])for(int j:rules.bans[i])banned[j]=true;
            static const std::vector<Fans> empty_plan{Fans{}};const std::vector<Fans>* plans=&empty_plan;
            if(s.kind==STANDARD){std::string key=pattern_key(s);key+=char(pattern.support);int forbidden=0;for(int f=70;f<=73;++f)if(banned[f])forbidden|=1<<(f-70);key+=char(forbidden);
                auto i=plan_cache.find(key);if(i==plan_cache.end())i=plan_cache.emplace(std::move(key),small_plans(s,pattern.support,banned)).first;plans=&i->second;}
            for(const auto& plan:*plans){Fans scored=candidate;for(int f=70;f<=73;++f)if(plan[f])scored[f]=plan[f];Fans alive=rules.excluded(scored);uint64_t removed=0;
                if(alive[1]||alive[9]||alive[53])removed|=z.trips&dragons;if(alive[37])removed|=z.trips&winds;
                for(auto ft:std::array<std::pair<int,int>,5>{{{58,31},{59,32},{60,33},{61,e.round},{62,e.seat}}})if(alive[ft.first])removed|=bit(ft.second);
                int n=pop(z.trips&orphan_mask()&~removed)-(z.nine?1:0);if(n>0)scored[74]=uint8_t(n);scored=rules.excluded(scored);bool empty=true;for(auto x:scored)empty&=x==0;if(empty)scored[42]=1;
                Fans key=project(scored);int total=rules.total(key);
                if(total>result.total){result.total=total;result.optimal.clear();canonical_raw=scored;result.canonical=key;}
                if(total==result.total){result.optimal.insert(key);if(canonical_less(canonical_raw,scored)){canonical_raw=scored;result.canonical=key;}}
            }
        }
    }if(result.total<0)throw std::runtime_error("no scoring interpretation");return result;
}
// Stable 44-byte physical payload, identical to the old generator's payload.
inline std::array<uint8_t,44> payload(Counts concealed,int win,std::vector<Group> fixed) {
    std::sort(fixed.begin(),fixed.end(),[](Group a,Group b){auto k=[](int x){return x==1?1:x==3?2:x==4?3:4;};return std::make_pair(k(a.kind),a.tile)<std::make_pair(k(b.kind),b.tile);});
    std::array<uint8_t,44> out{};std::copy(concealed.begin(),concealed.end(),out.begin());out[34]=uint8_t(win);out[35]=uint8_t(fixed.size());
    for(size_t i=0;i<fixed.size();++i){auto g=fixed[i];out[36+2*i]=uint8_t(g.kind==1?1:g.kind==3?2:g.kind==4?3:4);out[37+2*i]=uint8_t(g.tile);}return out;
}
inline void unpack(const uint8_t* data,Counts& concealed,int& win,std::vector<Group>& fixed) {
    std::copy(data,data+34,concealed.begin());win=data[34];fixed.clear();if(win>=34||data[35]>4)throw std::runtime_error("invalid payload");
    for(int i=0;i<data[35];++i){int k=data[36+2*i],t=data[37+2*i];if(k<1||k>4||t>=34)throw std::runtime_error("invalid fixed group");fixed.push_back({k==1?1:k==2?3:k==3?4:5,t});}sort_fixed(fixed);
}
struct Counters { uint64_t bases=0,physical=0,contexts=0,decompositions=0,wait_checks=0; };
// Cache restricted to one basis. It never grows with the complete search space.
struct Basis {
    Counts base{};std::vector<Shape> all;std::map<std::string,std::vector<Shape>> fixed_cache;std::map<std::string,bool> wait_cache;
    std::map<std::string,std::vector<Pattern>> pattern_cache;
    std::map<std::string,std::vector<Fans>> plan_cache;
    explicit Basis(Counts c):base(c),all(decompositions(c)){}
    std::string geometry_key(const std::vector<Group>& fixed) const {
        std::vector<std::pair<int,int>> gs;for(auto g:fixed)gs.emplace_back(g.seq()?0:1,g.tile);std::sort(gs.begin(),gs.end());std::string key;for(auto g:gs){key+=char(g.first);key+=char(g.second);}return key;
    }
    const std::vector<Shape>& shapes(const std::vector<Group>& fixed) {
        std::string k;for(auto g:fixed){k+=char(g.kind);k+=char(g.tile);}auto i=fixed_cache.find(k);
        if(i==fixed_cache.end())i=fixed_cache.emplace(k,compatible(all,fixed)).first;return i->second;
    }
    bool unique(const Counts& concealed,int win,const std::vector<Group>& fixed,Counters& stats) {
        std::string key=geometry_key(fixed);key+=char(win);auto i=wait_cache.find(key);if(i!=wait_cache.end())return i->second;
        Counts hand=concealed;--hand[win];bool yes=true;
        for(int t=0;t<34;++t)if(t!=win){++hand[t];++stats.wait_checks;bool ok=winning(hand,int(fixed.size()));--hand[t];if(ok){yes=false;break;}}
        wait_cache.emplace(std::move(key),yes);return yes;
    }
};
template<class Emit> void evaluate_physical(const Rules& rules,Basis& basis,Counts concealed,int win,std::vector<Group> fixed,Counters& stats,Emit emit) {
    sort_fixed(fixed);const auto& shapes=basis.shapes(fixed);if(shapes.empty()||!concealed[win])throw std::runtime_error("unreachable physical state");
    Counts full=concealed;int public_win=0,kans=0;bool closed=true;for(auto g:fixed){add(full,g);kans+=g.kan();closed&=!g.open();if(g.open())public_win+=g.seq()?(win>=g.tile&&win<=g.tile+2):(win==g.tile?4*(g.kan())+3*(!g.kan()):0);}
    for(auto n:full)if(n>4)throw std::runtime_error("physical inventory overflow");Counts hand=concealed;--hand[win];bool unique=basis.unique(concealed,win,fixed,stats);++stats.physical;auto physical=payload(concealed,win,fixed);
    uint64_t wind_trips=0;for(int t=27;t<31;++t)if(full[t]==3)wind_trips|=bit(t);for(auto g:fixed)if(!g.seq()&&g.tile>=27&&g.tile<=30)wind_trips|=bit(g.tile);
    for(int method=0;method<2;++method){auto prepared=prepare(shapes,full,hand,closed,win,bool(method),unique,basis.pattern_cache);
        auto context=[&](int source,int opening,int wall,int external){std::set<int> seen;bool last=public_win+external==3;
            for(int seat=27;seat<=30;++seat){if(opening==1&&seat!=27)continue;if(opening==2&&seat==27)continue;if(opening==3&&(seat==27||(!method&&seat==28)))continue;
                for(int rnd=27;rnd<=30;++rnd){int signature=(bool(wind_trips&bit(seat))?1:0)|(bool(wind_trips&bit(rnd))?2:0)|((seat==rnd&&(wind_trips&bit(seat)))?4:0);if(!seen.insert(signature).second)continue;
                    Event e{method,source,opening,wall,external,seat,rnd,last};auto result=score(rules,prepared,e,basis.plan_cache);++stats.contexts;emit(physical,e,closed,result);
                }
            }
        };
        for(int source=0;source<3;++source){if(source==1&&(!method||!kans))continue;if(source==2&&(method||full[win]!=1))continue;
            for(int wall=0;wall<2;++wall){if(source==2&&wall)continue;if(source==2)context(source,0,wall,3);else {context(source,0,wall,0);int needed=3-public_win;if(needed>0&&needed<=4-full[win])context(source,0,wall,needed);}}
        }
        if(fixed.empty()){if(method)context(0,1,0,0);else context(0,2,0,0);context(0,3,0,0);}
    }
}
} // namespace basis
