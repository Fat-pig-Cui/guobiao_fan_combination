#include "feature_filter_common.hpp"

#include <cuda_runtime.h>

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

__global__ void classify_kernel(const mcr::Candidate* candidates,
                                mcr::Result* results,
                                uint32_t count, uint64_t required) {
    const uint32_t index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < count) results[index] = mcr::classify(candidates[index], required);
}

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
    std::vector<mcr::Candidate> host_candidates(header.count);
    if (!read_exact(source, host_candidates.data(), host_candidates.size())) return 2;
    std::vector<mcr::Result> host_results(header.count);
    if (header.count == 0) {
        std::ofstream sink(output, std::ios::binary | std::ios::trunc);
        mcr::BatchHeader result_header{{'M','C','R','F'}, mcr::kVersion, 0};
        return sink && write_exact(sink, &result_header) ? 0 : 2;
    }
    mcr::Candidate* device_candidates = nullptr;
    mcr::Result* device_results = nullptr;
    const std::size_t candidate_bytes = sizeof(mcr::Candidate) * host_candidates.size();
    const std::size_t result_bytes = sizeof(mcr::Result) * host_results.size();
    auto fail = [&](const char* message) {
        std::cerr << message << ": " << cudaGetErrorString(cudaGetLastError()) << "\n";
        cudaFree(device_candidates); cudaFree(device_results); return 2;
    };
    if (cudaMalloc(reinterpret_cast<void**>(&device_candidates), candidate_bytes) != cudaSuccess)
        return fail("cudaMalloc candidates");
    if (cudaMalloc(reinterpret_cast<void**>(&device_results), result_bytes) != cudaSuccess)
        return fail("cudaMalloc results");
    if (cudaMemcpy(device_candidates, host_candidates.data(), candidate_bytes,
                   cudaMemcpyHostToDevice) != cudaSuccess) return fail("cudaMemcpy input");
    const int blocks = static_cast<int>((header.count + 255u) / 256u);
    classify_kernel<<<blocks, 256>>>(device_candidates, device_results, header.count, required);
    if (cudaDeviceSynchronize() != cudaSuccess) return fail("kernel");
    if (cudaMemcpy(host_results.data(), device_results, result_bytes,
                   cudaMemcpyDeviceToHost) != cudaSuccess) return fail("cudaMemcpy output");
    cudaFree(device_candidates); cudaFree(device_results);
    std::ofstream sink(output, std::ios::binary | std::ios::trunc);
    mcr::BatchHeader result_header{{'M','C','R','F'}, mcr::kVersion, header.count};
    if (!sink || !write_exact(sink, &result_header)
        || !write_exact(sink, host_results.data(), host_results.size())) return 2;
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: mahjong_feature_filter INPUT OUTPUT REQUIRED_MASK\n";
        return 2;
    }
    uint64_t required = 0;
    try { required = std::stoull(argv[3]); }
    catch (...) { return 2; }
    return run(argv[1], argv[2], required);
}
