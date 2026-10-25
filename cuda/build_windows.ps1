$ErrorActionPreference = 'Stop'

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw 'CMake is required'
}
if (-not (Get-Command nvcc -ErrorAction SilentlyContinue)) {
    throw 'CUDA Toolkit nvcc is required for the GPU target'
}

nvcc --version
cmake -S $PSScriptRoot -B (Join-Path $PSScriptRoot '..\build-cuda') `
    -G 'Visual Studio 17 2022' -A x64
cmake --build (Join-Path $PSScriptRoot '..\build-cuda') --config Release --parallel

Write-Host 'Built build-cuda\Release\mahjong_feature_filter.exe'
