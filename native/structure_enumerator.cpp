// Exact finite physical generators. No fan tests and no heuristic pruning.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Counts = std::array<uint8_t, 34>;
struct Atom { int tile; bool sequence; Counts counts{}; };
struct Pair { int a, b; Counts counts{}; };
struct Stop {};

struct Generator {
    uint64_t mask = (uint64_t(1) << 34) - 1;
    int64_t after = -1, cursor = -1;
    uint64_t limit = 4096, emitted = 0, joins = 0;
    int left_begin = 0, left_end = -1;
    bool declarations = true;
    std::string family = "standard";
    std::ofstream output;
    std::vector<int> tiles;
    std::vector<Atom> atoms;
    std::vector<Pair> pairs;
    std::vector<std::array<int, 9>> backbones;

    bool allowed(int t) const { return (mask >> t) & 1; }
    void init() {
        for (int t = 0; t < 34; ++t) if (allowed(t)) {
            tiles.push_back(t);
            Atom trip{t, false, {}}; trip.counts[t] = 3; atoms.push_back(trip);
            if (t < 27 && t % 9 <= 6 && allowed(t+1) && allowed(t+2)) {
                Atom seq{t, true, {}};
                for (int u = t; u <= t+2; ++u) seq.counts[u] = 1;
                atoms.push_back(seq);
            }
        }
        if (tiles.empty()) throw std::runtime_error("empty tile mask");
        for (int a = 0; a < int(atoms.size()); ++a)
            for (int b = a; b < int(atoms.size()); ++b) {
                Pair p{a,b,{}}; bool ok = true;
                for (int t = 0; t < 34; ++t) {
                    int n = atoms[a].counts[t] + atoms[b].counts[t];
                    if (n > 4) { ok = false; break; }
                    p.counts[t] = uint8_t(n);
                }
                if (ok) pairs.push_back(p);
            }
        std::array<int, 3> perm{0,1,2};
        do {
            std::array<int, 9> b{}; int i = 0;
            for (int s = 0; s < 3; ++s)
                for (int r = perm[s]; r < 9; r += 3) b[i++] = s*9+r;
            backbones.push_back(b);
        } while (std::next_permutation(perm.begin(), perm.end()));
    }

    // Portable little-endian: uint64 cursor; 34 concealed counts including win;
    // uint8 win; uint8 fixed count; four (kind,tile) slots. 52 bytes total.
    void emit(uint64_t rank, const Counts& concealed,
              std::vector<std::pair<uint8_t,uint8_t>> fixed) {
        if (int64_t(rank+33) <= after) return;
        std::sort(fixed.begin(), fixed.end());
        for (int w = 0; w < 34; ++w) if (concealed[w]) {
            uint64_t r = rank + w;
            if (int64_t(r) <= after) continue;
            std::array<uint8_t, 52> record{};
            for (int i = 0; i < 8; ++i) record[i] = uint8_t(r >> (8*i));
            std::copy(concealed.begin(), concealed.end(), record.begin()+8);
            record[42] = uint8_t(w); record[43] = uint8_t(fixed.size());
            for (size_t i = 0; i < fixed.size(); ++i) {
                record[44+2*i] = fixed[i].first; record[45+2*i] = fixed[i].second;
            }
            output.write(reinterpret_cast<const char*>(record.data()), record.size());
            if (!output) throw std::runtime_error("failed writing native batch");
            cursor = int64_t(r); ++emitted;
            if (limit && emitted >= limit) throw Stop{};
        }
    }

    void declared(uint64_t rank, const Counts& base, const std::vector<int>& gs,
                  int state, int pair) {
        Counts full = base, concealed = base;
        if (pair >= 0) {
            if (full[pair]+2 > 4) return;
            full[pair] += 2; concealed[pair] += 2;
        }
        std::vector<std::pair<uint8_t,uint8_t>> fixed;
        int prev = -1;
        for (size_t i = 0; i < gs.size(); ++i) {
            const Atom& a = atoms[gs[i]];
            int code = (state >> (2*i)) & 3;
            if (a.sequence && code > 1) return;
            if (i && gs[i] == gs[i-1] && prev > code) return;
            prev = code;
            if (!code) continue;
            if (!a.sequence && code >= 2 && ++full[a.tile] > 4) return;
            for (int t = 0; t < 34; ++t) concealed[t] -= a.counts[t];
            fixed.emplace_back(uint8_t(a.sequence ? 1 : code+1), uint8_t(a.tile));
        }
        emit(rank, concealed, fixed);
    }

    void standard() {
        const uint64_t P = pairs.size(), row_stride = 34*256*34;
        if (!P) return;
        int end = left_end < 0 ? int(P) : std::min(left_end, int(P));
        if (left_begin < 0 || left_begin > end) throw std::runtime_error("invalid left interval");
        int begin = left_begin;
        if (after >= 0) begin = std::max(begin, int(uint64_t(after)/(P*row_stride)));
        for (int l = begin; l < end; ++l) {
            const Pair& a = pairs[l];
            int rbegin = 0;
            if (after >= 0 && uint64_t(after)/(P*row_stride) == uint64_t(l))
                rbegin = int((uint64_t(after)/row_stride)%P);
            for (int r = rbegin; r < int(P); ++r) {
                const Pair& b = pairs[r];
                if (a.b > b.a) continue;
                ++joins;
                Counts base{}; bool ok = true;
                for (int t = 0; t < 34; ++t) {
                    int n = a.counts[t]+b.counts[t];
                    if (n > 4) { ok = false; break; }
                    base[t] = uint8_t(n);
                }
                if (!ok) continue;
                const uint64_t prefix = (uint64_t(l)*P+r)*row_stride;
                for (int pair : tiles) {
                    if (base[pair]+2 > 4 || int64_t(prefix+(pair+1)*256*34-1) <= after) continue;
                    for (int state = 0; state < (declarations ? 256 : 1); ++state) {
                        uint64_t rank = prefix+(pair*256+state)*34;
                        if (int64_t(rank+33) <= after) continue;
                        declared(rank, base, {a.a,a.b,b.a,b.b}, state, pair);
                    }
                }
            }
        }
    }

    void seven_pairs() {
        // A tile can supply two pairs. Prefix intervals permit direct resume.
        const uint64_t B = tiles.size();
        std::array<uint64_t, 9> powers{}; powers[0] = 1;
        for (int i = 1; i < 9; ++i) powers[i] = powers[i-1]*B;
        Counts counts{};
        std::function<void(int,int,uint64_t)> visit = [&](int depth, int start, uint64_t prefix) {
            // The last radix is the actual winning tile (34, not B).
            uint64_t high = (prefix+1)*powers[7-depth]*34-1;
            if (int64_t(high) <= after) return;
            if (depth == 7) { emit(prefix*34, counts, {}); return; }
            for (int i = start; i < int(B); ++i) {
                int t = tiles[i]; if (counts[t] == 4) continue;
                counts[t] += 2; visit(depth+1, i, prefix*B+i); counts[t] -= 2;
            }
        };
        visit(0,0,0);
    }

    void orphans() {
        const std::vector<int> ts{0,8,9,17,18,26,27,28,29,30,31,32,33};
        for (int t : ts) if (!allowed(t)) return;
        Counts base{}; for (int t : ts) base[t] = 1;
        for (size_t i = 0; i < ts.size(); ++i) {
            Counts c = base; ++c[ts[i]]; emit(i*34,c,{});
        }
    }

    void unconnected() {
        for (size_t bi = 0; bi < backbones.size(); ++bi) {
            std::vector<int> ts(backbones[bi].begin(),backbones[bi].end());
            for (int t = 27; t < 34; ++t) ts.push_back(t);
            for (int i = 0; i < 16; ++i) for (int j = i+1; j < 16; ++j) {
                Counts c{}; bool ok = true;
                for (int k = 0; k < 16; ++k) if (k != i && k != j) {
                    if (!allowed(ts[k])) { ok = false; break; }
                    ++c[ts[k]];
                }
                if (ok) emit(((bi*16+i)*16+j)*34,c,{});
            }
        }
    }

    void knitted() {
        for (size_t bi = 0; bi < backbones.size(); ++bi) {
            Counts backbone{}; bool ok = true;
            for (int t : backbones[bi]) { ++backbone[t]; if (!allowed(t)) ok = false; }
            if (!ok) continue;
            for (int pair : tiles) for (size_t ai = 0; ai < atoms.size(); ++ai) {
                Counts base = backbone; ok = true;
                for (int t = 0; t < 34; ++t) {
                    base[t] += atoms[ai].counts[t];
                    if (base[t] > 4) ok = false;
                }
                if (!ok) continue;
                for (int state = 0; state < (declarations ? 4 : 1); ++state) {
                    uint64_t rank = (((bi*34+pair)*atoms.size()+ai)*4+state)*34;
                    if (int64_t(rank+33) <= after) continue;
                    declared(rank,base,{int(ai)},state,pair);
                }
            }
        }
    }
};

int main(int argc, char** argv) {
    try {
        Generator g; std::string path;
        for (int i = 1; i < argc; ++i) {
            std::string a = argv[i];
            if (a == "--concealed-only") { g.declarations = false; continue; }
            if (i+1 == argc) throw std::runtime_error("missing argument: "+a);
            std::string v = argv[++i];
            if (a == "--family") g.family = v;
            else if (a == "--output") path = v;
            else if (a == "--tile-mask") g.mask = std::stoull(v);
            else if (a == "--after") g.after = std::stoll(v);
            else if (a == "--max-records") g.limit = std::stoull(v);
            else if (a == "--left-begin") g.left_begin = std::stoi(v);
            else if (a == "--left-end") g.left_end = std::stoi(v);
            else throw std::runtime_error("unknown argument: "+a);
        }
        if (path.empty() || g.mask == 0 || g.mask >> 34) throw std::runtime_error("invalid output or tile mask");
        g.output.open(path, std::ios::binary | std::ios::trunc);
        if (!g.output) throw std::runtime_error("cannot open output");
        g.output.write("MCRN0001",8); g.cursor = g.after; g.init();
        bool complete = false; auto start = std::chrono::steady_clock::now();
        try {
            if (g.family == "standard") g.standard();
            else if (g.family == "seven_pairs") g.seven_pairs();
            else if (g.family == "orphans") g.orphans();
            else if (g.family == "unconnected") g.unconnected();
            else if (g.family == "knitted") g.knitted();
            else throw std::runtime_error("unknown family");
            complete = true;
        } catch (const Stop&) {}
        g.output.close();
        double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        std::cout << "{\"records\":" << g.emitted << ",\"cursor\":" << g.cursor
                  << ",\"complete\":" << (complete ? "true" : "false")
                  << ",\"atoms\":" << g.atoms.size() << ",\"pairs\":" << g.pairs.size()
                  << ",\"join_checks\":" << g.joins << ",\"seconds\":" << elapsed << "}\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 2; }
}
