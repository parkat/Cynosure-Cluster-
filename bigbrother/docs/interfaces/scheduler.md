# Scheduler interface

## Purpose
Decouple "deciding which layers run where" from how the decision is made. Halda is one implementation; `StaticPlanScheduler` (loads JSON from disk) is another.

## Required operations

```cpp
class Scheduler {
public:
  virtual ~Scheduler() = default;

  // Produce a plan for the given model + device profiles.
  virtual Result<Plan> Solve(
      const ModelTopology& model,
      std::span<const DeviceProfile> profiles) = 0;

  // Check that a plan is internally consistent and feasible against profiles.
  virtual Result<void> Validate(const Plan& plan,
                                std::span<const DeviceProfile> profiles) const = 0;

  // Human-readable explanation: why these windows? Which constraints were tight?
  virtual std::string Explain(const Plan& plan) const = 0;

  // Solver identity, for plan provenance.
  virtual std::string_view Name() const = 0;
  virtual std::string_view Version() const = 0;
};
```

## Implementations

- `HaldaScheduler` (`src/core/scheduler/halda.cpp`) — ILP-based. See `docs/primitives/halda.md`. Phase 4.
- `StaticPlanScheduler` (`src/core/scheduler/static_plan.cpp`) — loads `plan.json` from disk, `Solve` ignores inputs and returns the loaded plan. `Validate` runs the standard checks. Available from Phase 3.

## Invariants

1. `Solve` is deterministic. Identical inputs (in canonical form) produce byte-identical plans.
2. `Validate(Solve(M, P), P)` always returns Ok. If a solver can't validate its own output, it's a bug.
3. `Explain` never throws; it may return an empty string if the plan was loaded externally and we don't have solver state.
4. `Name()` and `Version()` are written into the plan JSON for provenance.

## Plan structure (referenced)

The `Plan` struct mirrors the JSON in `docs/primitives/halda.md` section 6. The C++ header (Phase 4) defines:

```cpp
struct Plan {
  int schema_version;
  uint64_t epoch;
  std::string model_path;
  int total_layers;
  std::vector<RingNode> ring;
  std::string solver_name;
  std::string solver_version;
  double objective_value;
};

struct RingNode {
  std::string node_id;
  int first_layer;   // inclusive
  int last_layer;    // inclusive
  int gpu_layers;    // 0 ≤ gpu_layers ≤ (last_layer - first_layer + 1)
  DeviceCategory category;  // M1..M4
  std::optional<int> prefetch_depth;  // see docs/primitives/mmap-prefetch.md
};
```

## What `Validate` must check

- Coverage: `∪ ring[i].layers == {0..total_layers-1}`, no gaps, no overlaps.
- Memory: each node's `(weights + KV) ≤ ram + vram` per its profile.
- Disk: `model bytes ≤ disk` on every node.
- GPU layers ≤ window size.
- M2 nodes have `gpu_layers == 0`.
- All `node_id`s in the plan appear in the supplied profile set.
