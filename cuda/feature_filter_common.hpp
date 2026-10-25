#pragma once

#include <cstdint>

#ifdef __CUDACC__
#define MCR_HD __host__ __device__
#else
#define MCR_HD
#endif

namespace mcr {

constexpr uint32_t kVersion = 1;
constexpr uint64_t FEATURE_ALL_HONORS = 1ull << 0;
constexpr uint64_t FEATURE_ALL_TERMINALS = 1ull << 1;
constexpr uint64_t FEATURE_ALL_GREEN = 1ull << 2;
constexpr uint64_t FEATURE_NO_HONORS = 1ull << 3;
constexpr uint64_t FEATURE_ONE_NUMBER_SUIT = 1ull << 4;
constexpr uint64_t FEATURE_THREE_NUMBER_SUITS = 1ull << 5;
constexpr uint64_t FEATURE_HAS_WINDS = 1ull << 6;
constexpr uint64_t FEATURE_HAS_DRAGONS = 1ull << 7;
constexpr uint64_t FEATURE_HAS_TERMINALS = 1ull << 8;

#pragma pack(push, 1)
struct BatchHeader {
    char magic[4];       // MCR1
    uint32_t version;
    uint32_t count;
};

struct Candidate {
    uint8_t counts[34];
    uint8_t win;
    uint8_t family;
};

struct Result {
    uint64_t features;
    uint16_t total_tiles;
    uint8_t suit_mask;
    uint8_t passes;
};
#pragma pack(pop)

MCR_HD inline Result classify(const Candidate& candidate, uint64_t required) {
    Result result{};
    bool all_honors = true;
    bool all_terminals = true;
    bool all_green = true;
    bool no_honors = true;
    bool has_winds = false;
    bool has_dragons = false;
    bool has_terminals = false;
    uint8_t suit_mask = 0;
    uint16_t total = 0;
    for (int tile = 0; tile < 34; ++tile) {
        const uint8_t count = candidate.counts[tile];
        if (!count) continue;
        total += count;
        if (tile < 27) {
            all_honors = false;
            if (tile % 9 != 0 && tile % 9 != 8) all_terminals = false;
            if (tile % 9 == 0 || tile % 9 == 8) has_terminals = true;
            suit_mask |= static_cast<uint8_t>(1u << (tile / 9));
            if (tile != 19 && tile != 20 && tile != 21 &&
                tile != 23 && tile != 25) all_green = false;
        } else {
            all_terminals = false;
            if (tile != 32) all_green = false;
            no_honors = false;
            if (tile < 31) has_winds = true;
            else has_dragons = true;
        }
    }
    if (all_honors) result.features |= FEATURE_ALL_HONORS;
    if (all_terminals) result.features |= FEATURE_ALL_TERMINALS;
    if (all_green) result.features |= FEATURE_ALL_GREEN;
    if (no_honors) result.features |= FEATURE_NO_HONORS;
    if (suit_mask && (suit_mask & (suit_mask - 1)) == 0 && no_honors)
        result.features |= FEATURE_ONE_NUMBER_SUIT;
    if ((suit_mask & 0x7u) == 0x7u) result.features |= FEATURE_THREE_NUMBER_SUITS;
    if (has_winds) result.features |= FEATURE_HAS_WINDS;
    if (has_dragons) result.features |= FEATURE_HAS_DRAGONS;
    if (has_terminals) result.features |= FEATURE_HAS_TERMINALS;
    result.total_tiles = total;
    result.suit_mask = suit_mask;
    result.passes = (result.features & required) == required ? 1 : 0;
    return result;
}

}  // namespace mcr
