// Geometry batches with native scoring. No per-physical-state persistent index.
#define main old_structure_generator_main
#include "structure_enumerator.cpp"
#undef main
#include "basis_scorer.hpp"
#include <sstream>

namespace {
using namespace basis;
struct Engine {
    Generator geometry;
    Rules rules;
    std::unordered_set<std::string> known;
    std::ofstream output;
    std::ofstream trace;
    Counters stats;
    int64_t after=-1,cursor=-1;
    uint64_t max_bases=128;
    double seconds=0;
    bool all_results=false;
    int max_fan=-1;
    std::chrono::steady_clock::time_point began=std::chrono::steady_clock::now();
    Engine(const std::string& config):rules(config){}
    void load_known(const std::string& path) {
        if(path.empty())return;std::ifstream f(path,std::ios::binary);char magic[8];f.read(magic,8);
        if(std::string(magic,8)!="MCRK0001")throw std::runtime_error("invalid known key stream");
        char record[89];while(f.read(record,89))known.emplace(record,89);
        if(f.gcount())throw std::runtime_error("truncated known key stream");
    }
    void emit(const std::array<uint8_t,44>& physical,const Event& e,bool closed,const Result& result) {
        if(result.total<8&&!all_results)return;
        if(max_fan>=0 && result.total>max_fan)return;
        auto retain=[&](const Fans& fans,int policy){
            std::string key(reinterpret_cast<const char*>(fans.data()),86);key+=char(policy);key+=char(closed);key+=char(e.method);
            // `all_results` widens the accepted fan range; it must not disable
            // key de-duplication.  Keeping the key stream active is essential
            // for low-fan runs, whose output is otherwise needlessly repeated
            // across geometry batches.
            if(!known.insert(key).second)return;
            output.write(reinterpret_cast<const char*>(physical.data()),44);
            std::array<uint8_t,9> flags{uint8_t(e.method),uint8_t(e.source),uint8_t(e.opening),uint8_t(e.wall),uint8_t(e.external),uint8_t(e.seat),uint8_t(e.round),uint8_t(closed),uint8_t(policy)};
            output.write(reinterpret_cast<const char*>(flags.data()),flags.size());output.write(reinterpret_cast<const char*>(fans.data()),86);
            if(!output)throw std::runtime_error("observation write failed");
        };
        for(const auto& f:result.optimal)retain(f,0);retain(result.canonical,1);
    }
    void physical(Basis& b,basis::Counts concealed,int win,std::vector<basis::Group> fixed) {
        if(trace.is_open()) {
            auto data=payload(concealed,win,fixed);uint64_t rank=stats.physical;
            for(int i=0;i<8;++i)trace.put(char(rank>>(8*i)));
            trace.write(reinterpret_cast<const char*>(data.data()),data.size());
            if(!trace)throw std::runtime_error("physical diagnostic trace write failed");
        }
        evaluate_physical(rules,b,concealed,win,std::move(fixed),stats,[&](const auto& p,const auto& e,bool closed,const auto& r){emit(p,e,closed,r);});
    }
    void basis_record(uint64_t rank,const basis::Counts& base,const std::vector<basis::Group>& groups) {
        if(int64_t(rank)<=after)return;
        Basis b(base);++stats.bases;++stats.decompositions;
        // Declare each group with canonical ordering among equal geometries.
        int max_state=geometry.declarations?(1<<(2*groups.size())):1;
        for(int state=0;state<max_state;++state){auto concealed=base;auto full=base;std::vector<basis::Group> fixed;bool ok=true;int previous=-1;
            for(size_t i=0;i<groups.size();++i){auto g=groups[i];int code=(state>>(2*i))&3;
                if((g.seq()&&code>1)||(i&&g.same(groups[i-1])&&previous>code)){ok=false;break;}previous=code;
                if(!code)continue;if(!g.seq()&&code>=2&&++full[g.tile]>4){ok=false;break;}
                basis::add(concealed,g,-1,true);g.kind=g.seq()?1:code==1?3:code==2?4:5;fixed.push_back(g);
            }
            if(!ok)continue;for(int win=0;win<34;++win)if(concealed[win])physical(b,concealed,win,fixed);
        }
        cursor=int64_t(rank);
        if((max_bases&&stats.bases>=max_bases)||(seconds>0&&std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count()>=seconds))throw Stop{};
    }
    void standard() {
        uint64_t P=geometry.pairs.size();int end=geometry.left_end<0?int(P):std::min(int(P),geometry.left_end);
        if(geometry.left_begin<0||geometry.left_begin>end)throw std::runtime_error("invalid left interval");
        int begin=geometry.left_begin;if(after>=0)begin=std::max(begin,int(uint64_t(after)/(P*34)));
        for(int l=begin;l<end;++l){auto a=geometry.pairs[l];int rb=0;if(after>=0&&uint64_t(after)/(P*34)==uint64_t(l))rb=int(uint64_t(after)/34%P);
            for(int r=rb;r<int(P);++r){auto b=geometry.pairs[r];if(a.b>b.a)continue;basis::Counts base{};bool ok=true;for(int t=0;t<34;++t){int n=a.counts[t]+b.counts[t];if(n>4){ok=false;break;}base[t]=uint8_t(n);}if(!ok)continue;
                std::vector<basis::Group> gs;for(int ai:{a.a,a.b,b.a,b.b}){auto g=geometry.atoms[ai];gs.push_back({g.sequence?0:2,g.tile});}
                for(int pair:geometry.tiles)if(base[pair]<=2){base[pair]+=2;basis_record((uint64_t(l)*P+r)*34+pair,base,gs);base[pair]-=2;}
            }
        }
    }
    void seven_pairs() {
        uint64_t B=geometry.tiles.size();std::array<uint64_t,8> powers{};powers[0]=1;for(int i=1;i<8;++i)powers[i]=powers[i-1]*B;
        basis::Counts c{};std::function<void(int,int,uint64_t)> visit=[&](int depth,int start,uint64_t prefix){
            if(int64_t((prefix+1)*powers[7-depth]-1)<=after)return;
            if(depth==7){basis_record(prefix,c,{});return;}
            for(int i=start;i<int(B);++i){int t=geometry.tiles[i];if(c[t]==4)continue;c[t]+=2;visit(depth+1,i,prefix*B+i);c[t]-=2;}
        };visit(0,0,0);
    }
    void knitted() {
        for(size_t bi=0;bi<geometry.backbones.size();++bi){basis::Counts c{};bool allowed=true;for(int t:geometry.backbones[bi]){++c[t];allowed&=geometry.allowed(t);}if(!allowed)continue;
            for(int p:geometry.tiles)for(size_t ai=0;ai<geometry.atoms.size();++ai){auto a=geometry.atoms[ai];basis::Counts base=c;bool ok=true;for(int t=0;t<34;++t){base[t]+=a.counts[t];ok&=base[t]<=4;}if(!ok||base[p]>2)continue;base[p]+=2;
                basis_record((bi*34+p)*geometry.atoms.size()+ai,base,{{a.sequence?0:2,a.tile}});
            }
        }
    }
    void orphans() {
        basis::Counts base{};for(int t=0;t<34;++t)if(orphan(t)){if(!geometry.allowed(t))return;base[t]=1;}
        for(int t=0;t<34;++t)if(base[t]){++base[t];basis_record(t,base,{});--base[t];}
    }
    void unconnected() {
        for(size_t bi=0;bi<geometry.backbones.size();++bi){std::vector<int> ts(geometry.backbones[bi].begin(),geometry.backbones[bi].end());for(int t=27;t<34;++t)ts.push_back(t);
            for(int i=0;i<16;++i)for(int j=i+1;j<16;++j){basis::Counts c{};bool ok=true;for(int k=0;k<16;++k)if(k!=i&&k!=j){++c[ts[k]];ok&=geometry.allowed(ts[k]);}if(ok)basis_record((bi*16+i)*16+j,c,{});}
        }
    }
    void input(const std::string& path) {
        std::ifstream f(path,std::ios::binary);char magic[8];f.read(magic,8);if(std::string(magic,8)!="MCRN0001")throw std::runtime_error("invalid physical input stream");
        std::array<uint8_t,52> record{};
        while(f.read(reinterpret_cast<char*>(record.data()),record.size())){
            basis::Counts concealed{};int win;std::vector<basis::Group> fixed;unpack(record.data()+8,concealed,win,fixed);auto base=concealed;for(auto g:fixed)basis::add(base,g,1,true);Basis b(base);++stats.bases;++stats.decompositions;physical(b,concealed,win,fixed);
        }if(f.gcount())throw std::runtime_error("truncated physical input stream");
    }
};
}
int main(int argc,char** argv) {
    try {
        std::map<std::string,std::string> a;bool concealed=false,all_results=false;
        for(int i=1;i<argc;++i){std::string k=argv[i];if(k=="--concealed-only"){concealed=true;continue;}if(k=="--all-results"){all_results=true;continue;}if(i+1>=argc)throw std::runtime_error("missing argument");a[k]=argv[++i];}
        auto get=[&](const std::string& k,const std::string& d){return a.count(k)?a[k]:d;};
        if(!a.count("--rules")||!a.count("--output"))throw std::runtime_error("require --rules and --output");Engine e(a["--rules"]);e.geometry.mask=std::stoull(get("--tile-mask",std::to_string((uint64_t(1)<<34)-1)));if(!e.geometry.mask||e.geometry.mask>>34)throw std::runtime_error("invalid tile mask");
        e.geometry.declarations=!concealed;e.geometry.left_begin=std::stoi(get("--left-begin","0"));e.geometry.left_end=std::stoi(get("--left-end","-1"));e.geometry.init();e.after=e.cursor=std::stoll(get("--after","-1"));e.max_bases=std::stoull(get("--max-bases","128"));e.seconds=std::stod(get("--seconds","0"));e.max_fan=std::stoi(get("--max-fan","-1"));e.all_results=all_results;e.load_known(get("--known",""));
        e.output.open(a["--output"],std::ios::binary|std::ios::trunc);if(!e.output)throw std::runtime_error("cannot open observation output");e.output.write("MCRB0001",8);
        if(a.count("--physical-output")){e.trace.open(a["--physical-output"],std::ios::binary|std::ios::trunc);if(!e.trace)throw std::runtime_error("cannot open physical trace");e.trace.write("MCRN0001",8);}
        bool complete=false;
        try {if(a.count("--input"))e.input(a["--input"]);else {std::string family=get("--family","standard");if(family=="standard")e.standard();else if(family=="seven_pairs")e.seven_pairs();else if(family=="knitted")e.knitted();else if(family=="orphans")e.orphans();else if(family=="unconnected")e.unconnected();else throw std::runtime_error("unknown family");}complete=true;}catch(const Stop&){}
        e.output.close();double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-e.began).count();
        std::cout<<"{\"cursor\":"<<e.cursor<<",\"complete\":"<<(complete?"true":"false")<<",\"bases\":"<<e.stats.bases<<",\"physical\":"<<e.stats.physical<<",\"contexts\":"<<e.stats.contexts<<",\"decompositions\":"<<e.stats.decompositions<<",\"wait_checks\":"<<e.stats.wait_checks<<",\"pair_rows\":"<<e.geometry.pairs.size()<<",\"seconds\":"<<elapsed<<"}\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 2;}
}
