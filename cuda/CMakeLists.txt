cmake_minimum_required(VERSION 3.24)
project(mahjong_feature_filter LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)

add_executable(mahjong_feature_filter feature_filter.cu)
target_include_directories(mahjong_feature_filter PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
set_target_properties(mahjong_feature_filter PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

add_executable(mahjong_feature_filter_cpu feature_filter_cpu.cpp)
target_include_directories(mahjong_feature_filter_cpu PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
