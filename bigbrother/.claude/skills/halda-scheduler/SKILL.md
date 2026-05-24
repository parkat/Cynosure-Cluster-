---
name: halda-scheduler
description: When working on the scheduler, profiler inputs, or plan emission.
---

# Halda scheduler

## When this applies
- Editing `src/core/scheduler/halda.cpp` or related solver code
- Adding new constraints (RAM, VRAM, link bandwidth, thermal)
- Changing `src/core/profiler/` outputs the solver consumes
- Producing or validating plan JSON

## Core invariants
1. **Halda is one Scheduler, not the only one.** A `StaticPlanScheduler` reads a hand-written JSON. The interface (`docs/interfaces/scheduler.md`) is the contract; Halda is one implementation.
2. **Plans are versioned.** Every emitted plan carries a schema version and an epoch. Workers reject plans for stale epochs.
3. **Profiles are inputs, not outputs.** Halda never measures. The profiler measures; Halda solves.
4. **Determinism matters.** Given identical profile inputs and model topology, two Halda runs must produce byte-identical plan JSONs. We use HiGHS with a fixed seed and a fixed variable ordering.
5. **Halda must fail loudly on infeasibility.** Returning a bad plan is worse than returning an error. The CLI must exit non-zero and print which constraint was tight.

## Problem statement (informal)

Given:
- A model with `L` layers, per-layer FLOPs `f_l`, per-layer KV bytes `k_l`
- `M` devices, each with `(ram_m, vram_m, disk_m, compute_m, link_m)`
- A target topology (ring or static partition)

Find:
- `w_m` — number of contiguous layers assigned to device `m` (the "layer window")
- `n_m` — of those `w_m`, how many run on GPU (vs CPU) on that device

Minimize per-stage TPOT (time-per-output-token), modeled as:

```
TPOT_per_stage(m) = L · (a · w_m + b · n_m + c) / w_m  +  κ
```

where `a` reflects layer compute cost, `b` reflects GPU↔CPU spill cost, `c` is a fixed per-stage overhead, and `κ` is link-bandwidth overhead.

Subject to:
- Σ w_m = L (cover the whole model)
- KV(w_m) ≤ ram_m for CPU layers
- KV(n_m) · per_layer_kv ≤ vram_m
- Activations(w_m) ≤ link_bw_m · token_budget

## Dependencies
- HiGHS ≥ 1.9.0 (open-source MIP/LP solver, MIT-equivalent license)
- Built as a system library or vendored — we'll decide in Phase 4. Pin the version in CMakeLists when we do.

## Device categorization (sets M1–M4)
- **M1:** GPU-only devices (no usable CPU compute). Unused on Linux x86; here for future heterogeneity.
- **M2:** CPU-only devices (no GPU). Some of our 30 nodes are M2.
- **M3:** Hybrid devices where the GPU holds part of the model and CPU holds the rest. P100 and 1060 nodes are M3.
- **M4:** Hybrid devices where the GPU acts only as a compute proxy and the CPU owns weights. Useful when VRAM < single-layer footprint. Rare for us.

The solver reduces the joint `(w_m, n_m)` problem to a per-`k` family of ILPs (one for each layer-window count `k`) and picks the best `k`. This makes each sub-ILP small and fast.

## Failure modes and handling

| Failure | Handling |
|---------|----------|
| Node disconnects mid-profile | Drop that profile; re-solve with M-1 devices |
| Thermal throttle reported by optibox | De-weight `compute_m` by reported %; re-solve |
| Infeasible (model too big) | Exit non-zero; print which constraint was tight, suggest quantization |
| Solver timeout (HiGHS > 30s) | Abort solve; fall back to last known good plan; log warning |

## `--static-plan plan.json` bypass

For Phase 1-3 (and any future debugging), `headd --static-plan plan.json` skips Halda entirely and loads a hand-authored plan. Same JSON schema, same validation. This is how we got two-node Llama-3.2-1B running in Phase 3 before the solver existed.

## Common mistakes
- Treating per-layer FLOPs as constant — they're not. Attention layers cost more than FFN layers at long context. Profile per-layer.
- Forgetting KV-cache memory — KV grows linearly with context; at 32K context on 70B that's ~10 GB of KV alone.
- Letting Halda solve over a non-fixed variable order — HiGHS will return different optima with the same input. Always sort devices by ID before passing in.
- Skipping validation — plans must round-trip through `Plan::Validate()` before headd accepts them.

## References
- @docs/primitives/halda.md — formal spec
- @docs/interfaces/scheduler.md — interface contract
- arXiv 2504.08791 — prima.cpp paper (section 4)
- https://highs.dev — HiGHS solver docs
