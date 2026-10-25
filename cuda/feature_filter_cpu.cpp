#include "feature_filter_common.hpp"

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

template <typename T>
bool read_exact(std::ifstream& stream, T* value, std::size_t count = 1) {
    stream.read(reinterpret_cast<char*>(value), sizeof(T) * count);
    return static_cast<bool>(stream);
}

template <typename T>
bool write_exact(std::ofstream& stream, const T* value, std::size_t count = 1) {
    stream.write(reinterpret_cast<const char*>(value), sizeof(T) * count);
    return static_cast<bool>(stream);
}

int run(const std::string& input, const std::string& output, uint64_t required) {
    std::ifstream source(input, std::ios::binary);
    mcr::BatchHeader header{};
    if (!source || !read_exact(source, &header) || std::string(header.magic, 4) != "MCR1"
        || header.version != mcr::kVersion) {
        std::cerr << "invalid MCR1 input\n";
        return 2;
    }
    std::vector<mcr::Candidate> candidates(header.count);
    if (!read_exact(source, candidates.data(), candidates.size())) return 2;
    std::vector<mcr::Result> results(header.count);
    for (uint32_t i = 0; i < header.count; ++i)
        results[i] = mcr::classify(candidates[i], required);
    std::ofstream sink(output, std::ios::binary | std::ios::trunc);
    mcr::BatchHeader result_header{{'M','C','R','F'}, mcr::kVersion, header.count};
    if (!sink || !write_exact(sink, &result_header)
        || !write_exact(sink, results.data(), results.size())) return 2;
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: mahjong_feature_filter_cpu INPUT OUTPUT REQUIRED_MASK\n";
        return 2;
    }
    uint64_t required = 0;
    try { required = std::stoull(argv[3]); }
    catch (...) { return 2; }
    return run(argv[1], argv[2], required);
}
