# Halda — heterogeneous-device layer assignment

Halda is the bigbrother scheduler. It decides which layers of a given model run on which device of a heterogeneous cluster, and within a single device, how those layers split between GPU and CPU. The name and formulation come from the prima.cpp paper (arXiv 2504.08791), which we re-implement here as a first-party module rather than vendor.

This document is the formal spec. The implementation lives in `src/core/scheduler/halda.cpp` (Phase 4). Until then, plans are hand-authored JSON consumed by the `StaticPlanScheduler`.

## 1. The problem

We have:

- A transformer model with `L` layers. For each layer `l ∈ {0..L-1}` we know:
  - `f_l` — FLOPs per token at layer `l`
  - `k_l` — bytes added to the KV cache per token at layer `l`
  - `w_l` — weight bytes for layer `l` (depends on quantization)
- A set of devices `m ∈ {1..M}`. For each device:
  - `ram_m` — total CPU RAM available (bytes)
  - `vram_m` — total GPU VRAM available (bytes), 0 if no GPU
  - `disk_m` — local model storage available (bytes); the whole GGUF must mmap from disk
  - `compute_cpu_m` — measured CPU FLOPS for this layer kind
  - `compute_gpu_m` — measured GPU FLOPS, 0 if no GPU
  - `link_in_m`, `link_out_m` — measured bandwidth to the prev/next ring node (bytes/sec)
- A target topology (ring; PRP; see `prp.md`)
- A target context length `C` (max tokens per request)

We want to find:

- `w_m ∈ ℤ⁺` for each device — the **layer window**, i.e. how many contiguous layers device `m` owns. `Σ_m w_m = L`.
- `n_m ∈ {0..w_m}` for each device — how many of `m`'s layers run on its GPU. The remaining `w_m - n_m` run on its CPU.

Subject to:

- **VRAM:** `n_m · avg_layer_weight + n_m · k_avg · C ≤ vram_m`
- **RAM:**  `(w_m - n_m) · avg_layer_weight + w_m · k_avg · C + reserve ≤ ram_m`
- **Disk:** `total_model_bytes ≤ disk_m` (every node must be able to mmap the full GGUF; we don't shard the file)
- **Coverage:** `Σ_m w_m = L`
- **Non-negative:** `w_m ≥ 1`, `n_m ≥ 0`

Minimizing per-stage TPOT.

## 2. The objective

We model the time-per-output-token for one stage `m` as:

```
TPOT_m = (a · w_m + b · n_m + c) / compute_m  +  κ_m
```

where:
- `a` is the compute cost coefficient per layer (token-pass cost at `m`'s layer kind, divided by `compute_m`)
- `b` is the additional cost incurred per GPU-on-CPU-platform layer (PCIe round-trip, kernel launch overhead)
- `c` is a fixed per-stage overhead (sampling, packing, framing)
- `κ_m` is the network cost of sending one activation block downstream:
  `κ_m = activation_bytes(w_m) / link_out_m`

The whole-ring TPOT is bounded below by `max_m TPOT_m`. We minimize the maximum:

```
minimize  T
subject to TPOT_m ≤ T   for all m
           (plus constraints above)
```

This is the standard min-max formulation; with linear `TPOT_m` it's an MILP.

## 3. Reduction to per-k ILPs

Solving for `w_m` and `n_m` jointly is expensive. Halda decomposes:

- For each candidate **window count** `k ∈ {k_min..k_max}` (where `k_min = ⌈M⌉` and `k_max = L`), fix that we'll use `k` distinct windows.
- For each `k`, solve a smaller MILP that just decides which device gets which window.
- Pick the `k` whose optimal objective is best.

`k_min = M` when every device gets at least one layer. We rarely want fewer windows than devices (it strands hardware), and rarely more (it bloats network traffic from extra ring hops).

In practice the search space for `k` is small (M..M+2), so this is cheap.

## 4. Device categorization (M1–M4)

Halda partitions devices into four categories to apply category-specific constraints:

- **M1 — Pure GPU.** GPU is the only compute. `compute_cpu_m = 0`. Unused on our Linux x86 fleet but kept in the model for completeness.
- **M2 — Pure CPU.** No GPU. `vram_m = 0`, `n_m = 0` forced. Several of our 30 nodes are M2 (anything without a Pascal card).
- **M3 — Hybrid, GPU primary.** Both compute paths are real. GPU holds `n_m` layers, CPU holds the rest. P100 and 1060 nodes are M3. **This is our common case.**
- **M4 — Hybrid, CPU primary.** GPU exists but VRAM is too small to hold even one full layer at the target quant. The GPU is used as a compute proxy by streaming weights from CPU. We expect this rarely; it's slow.

Categorization happens in the profiler based on measured VRAM vs. quoted `avg_layer_weight`. The scheduler reads the category as input.

## 5. Inputs from the profiler

`src/core/profiler/` runs a one-shot calibration pass per device (Phase 4) and writes a JSON like:

```json
{
  "node_id": "p100a",
  "category": "M3",
  "ram_bytes": 34359738368,
  "vram_bytes": 17179869184,
  "disk_bytes": 1099511627776,
  "compute_cpu_flops": 1.2e11,
  "compute_gpu_flops": 9.3e12,
  "link_in_bytes_per_sec": 1.18e9,
  "link_out_bytes_per_sec": 1.18e9,
  "measured_at_epoch": 7,
  "git_sha": "<sha>"
}
```

Halda consumes one profile per device per solve.

## 6. Outputs — the Plan

Halda emits a `plan.json` with this shape (validated by `src/core/plan/plan_io.cpp`):

```json
{
  "schema_version": 1,
  "epoch": 7,
  "model": {"path": "/opt/models/llama-3.3-70b-q4km.gguf", "L": 80},
  "ring": [
    {"node_id": "p100a", "layers": [0, 23], "gpu_layers": 23, "category": "M3"},
    {"node_id": "p100b", "layers": [24, 49], "gpu_layers": 26, "category": "M3"},
    {"node_id": "1060a", "layers": [50, 65], "gpu_layers": 16, "category": "M3"},
    {"node_id": "cpu1",  "layers": [66, 79], "gpu_layers": 0,  "category": "M2"}
  ],
  "solver": "halda",
  "solver_version": "1.0.0",
  "highs_seed": 0,
  "objective_value": 0.142
}
```

`layers` is `[first, last]` inclusive. `gpu_layers` is `n_m`; the first `gpu_layers` of `[first..last]` are on GPU, remainder on CPU.

## 7. Determinism

Two Halda runs on the same input must produce byte-identical JSON. Required:

- Sort device list by `node_id` before passing into HiGHS.
- HiGHS seed pinned (`highs_seed: 0`).
- All floating-point profile values rounded to 6 significant digits before solver input.
- JSON written with sorted keys, no trailing whitespace.

The unit test in `tests/unit/halda_test.cpp` (Phase 4) asserts byte-equality across two solver invocations on the same fixture.

## 8. Failure modes

| Failure | Halda's response |
|---------|------------------|
| Node disconnects mid-profile | Profile collection drops that node; Halda solves with M-1 |
| Thermal throttle reported by optibox | `compute_m` is multiplied by `(1 - throttle_pct)` before solve |
| Solver returns infeasible | Halda exits non-zero, prints the tight constraint (RAM/VRAM/disk/coverage), suggests "try lower quant" |
| HiGHS runs > 30 s | Solver is aborted; previous plan is reused; warning logged; if no previous plan, exits non-zero |
| Plan validation fails | Halda's own bug — emit a coredump, exit non-zero, do not silently produce a malformed plan |

## 9. `--static-plan` bypass

For Phase 1-3 and any debugging, `headd --static-plan plan.json` skips Halda entirely. The static plan must conform to the same schema and pass the same `Plan::Validate()` check. This is the only mode available until Phase 4 completes.

`tools/plan_inspector.py` (Phase 4) will pretty-print a plan and highlight any constraint violations relative to a profile set.

## 10. Future work

- **Speculative decoding.** Halda needs to assign a draft model to one node in addition to the main model. New variable `s_m ∈ {0,1}` per device.
- **Multi-LoRA.** Each LoRA adds memory pressure; Halda needs to know which LoRAs are active.
- **MoE.** Mixture-of-Experts means per-token routing — Halda's per-layer FLOPs become expected per-layer FLOPs over expert distribution.
- **10 GbE asymmetry.** When p100a↔p100b have 10 GbE and everything else has 1 GbE, `link_m` is not a per-device scalar — it's a per-edge value. Halda's objective needs to know the actual ring edge bandwidths, not just the source's outbound.

None of this lives in Phase 4's Halda. We get the basics working first, then iterate.

## References
- prima.cpp paper: https://arxiv.org/abs/2504.08791
- HiGHS solver: https://highs.dev
- @docs/interfaces/scheduler.md — `Scheduler` interface contract
- @DECISIONS.md — ADR-001 (wrap not fork)
