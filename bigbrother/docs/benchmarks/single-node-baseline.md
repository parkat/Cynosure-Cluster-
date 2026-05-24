# Single-node baseline

## Purpose
Measure raw llama.cpp performance before distribution overhead.

## Prerequisites
- Node with 1× P100 (16GB) + 32GB RAM
- Llama-3.3-70B-Instruct-Q4_K_M.gguf on local SSD
- llama.cpp built with CUDA 12.6

## Protocol
1. Warm cache: `cat <model.gguf> > /dev/null`
2. Warmup: `llama-cli -m <model> -p "hello" -n 50 --gpu-layers 50` (discard)
3. Measurement (3×): `llama-cli -m <model> -p "<canonical prompt>" -n 500 --gpu-layers 50`
4. Record: pp tok/s, tg tok/s, wall time, peak VRAM, peak RAM
5. Median of 3 runs

## Canonical prompt
"Write a 500-word explanation of how a turbocharger works, suitable for a high school student. Be thorough but accessible."

## Output to plan/handoffs/bench-<date>-single-node-baseline.md as a table.

Not implemented yet — Phase 1.
