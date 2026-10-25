// Runtime sampling only: invoke the unchanged production Engine on uniformly
// sampled complete bases. These sparse results are not enumeration checkpoints.
#include "basis_sampler_engine.hpp"
#include <random>
#include <iomanip>

namespace {
struct Stratum {
    std::string id, family;
    int left_begin=0, left_end=0;
    uint64_t population=0;
    std::vector<uint64_t> ranks;
    void see(uint64_t rank, size_t n, std::mt19937_64& rng) {
        ++population;
        if(ranks.size()<n)ranks.push_back(rank);
        else { auto j=std::uniform_int_distribution<uint64_t>(0,population-1)(rng);
            if(j<n)ranks[j]=rank; }
    }
};
void inventory(size_t n,uint64_t seed,int width) {
    Generator g;g.init();uint64_t P=g.pairs.size();std::mt19937_64 rng(seed);
    std::vector<Stratum> ss;
    for(int l=0;l<int(P);l+=width) {
        Stratum s; s.id="standard-"+std::to_string(l);s.family="standard";
        s.left_begin=l;s.left_end=std::min(l+width,int(P));ss.push_back(s);
    }
    for(int l=0;l<int(P);++l)for(int r=0;r<int(P);++r) {
        auto a=g.pairs[l],b=g.pairs[r];if(a.b>b.a)continue;
        Counts c{};bool ok=true;
        for(int t=0;t<34;++t){int k=a.counts[t]+b.counts[t];if(k>4){ok=false;break;}c[t]=k;}
        if(ok)for(int p=0;p<34;++p)if(c[p]<=2)ss[l/width].see((uint64_t(l)*P+r)*34+p,n,rng);
    }
    size_t qi=ss.size();for(int d=0;d<4;++d){Stratum s;s.id="seven_pairs-"+std::to_string(d);s.family="seven_pairs";ss.push_back(s);}
    Counts c{};
    std::function<void(int,int,uint64_t)> visit=[&](int depth,int start,uint64_t rank){
        if(depth==7){int d=std::count(c.begin(),c.end(),4);ss[qi+d].see(rank,n,rng);return;}
        for(int t=start;t<34;++t)if(c[t]<4){c[t]+=2;visit(depth+1,t,rank*34+t);c[t]-=2;}
    };visit(0,0,0);
    Stratum knitted;knitted.id=knitted.family="knitted";
    for(size_t bi=0;bi<g.backbones.size();++bi)for(int p=0;p<34;++p)for(size_t ai=0;ai<g.atoms.size();++ai){
        Counts base{};for(int t:g.backbones[bi])++base[t];bool ok=true;
        for(int t=0;t<34;++t){base[t]+=g.atoms[ai].counts[t];ok&=base[t]<=4;}
        if(ok&&base[p]<=2)knitted.see((bi*34+p)*g.atoms.size()+ai,n,rng);
    }ss.push_back(knitted);
    Stratum disconnected;disconnected.id=disconnected.family="unconnected";
    for(size_t bi=0;bi<g.backbones.size();++bi)for(int i=0;i<16;++i)for(int j=i+1;j<16;++j)
        disconnected.see((bi*16+i)*16+j,n,rng);
    ss.push_back(disconnected);
    Stratum orphans;orphans.id=orphans.family="orphans";
    for(int t=0;t<34;++t)if(orphan(t))orphans.see(t,n,rng);ss.push_back(orphans);
    std::cout<<"{\"seed\":"<<seed<<",\"samples_per_stratum\":"<<n<<",\"pair_rows\":"<<P<<",\"strata\":[";
    bool first=true;for(auto& s:ss){if(!s.population)continue;if(!first)std::cout<<',';first=false;
        std::sort(s.ranks.begin(),s.ranks.end());
        std::cout<<"{\"id\":\""<<s.id<<"\",\"family\":\""<<s.family<<"\",\"left_begin\":"<<s.left_begin<<",\"left_end\":"<<s.left_end<<",\"population\":"<<s.population<<",\"ranks\":[";
        for(size_t i=0;i<s.ranks.size();++i){if(i)std::cout<<',';std::cout<<s.ranks[i];}std::cout<<"]}";
    }std::cout<<"]}\n";
}
void sampled_record(Engine& e,const std::string& family,uint64_t rank) {
    basis::Counts base{};std::vector<basis::Group> groups;auto& g=e.geometry;
    auto add_atom=[&](int ai){auto a=g.atoms[ai];for(int t=0;t<34;++t)base[t]+=a.counts[t];groups.push_back({a.sequence?0:2,a.tile});};
    if(family=="standard") {
        int p=rank%34;uint64_t q=rank/34;auto a=g.pairs.at(q/g.pairs.size()),b=g.pairs.at(q%g.pairs.size());
        for(int ai:{a.a,a.b,b.a,b.b})add_atom(ai);base[p]+=2;
    } else if(family=="seven_pairs") {
        uint64_t q=rank;for(int i=0;i<7;++i){base[q%34]+=2;q/=34;}
    } else if(family=="knitted") {
        int ai=rank%g.atoms.size();uint64_t q=rank/g.atoms.size();
        for(int t:g.backbones.at(q/34))++base[t];base[q%34]+=2;add_atom(ai);
    } else if(family=="unconnected") {
        int j=rank%16;uint64_t q=rank/16;int i=q%16;
        std::vector<int> ts(g.backbones.at(q/16).begin(),g.backbones.at(q/16).end());
        for(int t=27;t<34;++t)ts.push_back(t);for(int k=0;k<16;++k)if(k!=i&&k!=j)++base[ts[k]];
    } else if(family=="orphans") {for(int t=0;t<34;++t)if(orphan(t))base[t]=1;++base.at(rank);}
    else throw std::runtime_error("unknown sample family");
    e.basis_record(rank,base,groups);
}
}
int main(int argc,char** argv) {
    try {
        std::map<std::string,std::string> a;for(int i=1;i<argc;i+=2){if(i+1>=argc)throw std::runtime_error("missing option value");a[argv[i]]=argv[i+1];}
        if(a.count("--inventory")){inventory(std::stoull(a.at("--samples")),std::stoull(a.at("--seed")),std::stoi(a.at("--rows")));return 0;}
        Engine e(a.at("--rules"));e.geometry.init();e.max_bases=0;e.load_known(a.count("--known")?a.at("--known"):"");
        e.output.open(a.at("--output"),std::ios::binary|std::ios::trunc);e.output.write("MCRB0001",8);
        std::istringstream ranks(a.at("--ranks"));uint64_t rank;std::vector<double> times;
        auto began=std::chrono::steady_clock::now();
        while(ranks>>rank){auto start=std::chrono::steady_clock::now();sampled_record(e,a.at("--family"),rank);times.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count());}
        e.output.close();double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();
        std::cout<<std::setprecision(12)<<"{\"bases\":"<<e.stats.bases<<",\"physical\":"<<e.stats.physical<<",\"contexts\":"<<e.stats.contexts<<",\"seconds\":"<<elapsed<<",\"per_base_seconds\":[";
        for(size_t i=0;i<times.size();++i){if(i)std::cout<<',';std::cout<<times[i];}std::cout<<"]}\n";return 0;
    }catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';return 2;}
}
