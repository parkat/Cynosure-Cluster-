---
name: benchmark-protocol
description: When running benchmarks or recording results in plan/handoffs/.
---

# Benchmark protocol

## When this applies
- Running anything from `docs/benchmarks/`
- Recording a result in `plan/handoffs/bench-*.md`
- Adding a new benchmark protocol

## Core invariants
1. **Warmup is mandatory.** 50 tokens discarded before measurement. Cold cache numbers are not real numbers.
2. **Measure 500 tokens.** Shorter runs are noisy; longer runs invite throttling artifacts.
3. **Median of 3 runs.** Single runs lie. Mean of 3 lies less but still hides one bad apple. Median is the rule.
4. **Capture the command verbatim.** The result file must include the exact command line, environment, and git SHA that produced it. Without this, the number is unverifiable and worthless (CLAUDE.md rule 2).
5. **No flag-tuning mid-protocol.** If a run fails or surprises you, stop and document. Do not iterate on flags inside a benchmark session — that's a different activity (tuning).

## Result file format

`plan/handoffs/bench-YYYY-MM-DD-<name>.md`:

```markdown
# Benchmark: <name>
Date: YYYY-MM-DD
Operator: claude / human / both
Git SHA: <full sha>
llama.cpp SHA: <from vendor/llama.cpp HEAD>
Hardware: <node list>

## Command
```
<exact command, one per line if multi-step>
```

## Environment
- CUDA: <output of nvcc --version>
- Driver: <output of nvidia-smi --query-gpu=driver_version>
- Kernel: <uname -r>
- Relevant env vars: GGML_*, OMP_*, etc.

## Results

| Run | pp tok/s | tg tok/s | Wall | Peak VRAM | Peak RAM | Notes |
|-----|----------|----------|------|-----------|----------|-------|
| 1   |          |          |      |           |          |       |
| 2   |          |          |      |           |          |       |
| 3   |          |          |      |           |          |       |
| **median** | | | | | | |

## Observations
<bullets, only facts, no speculation>

## Failures (if any)
<exact error output>
```

## Standard canonical prompt (use unless protocol says otherwise)

> "Write a 500-word explanation of how a turbocharger works, suitable for a high school student. Be thorough but accessible."

This prompt is in `docs/benchmarks/single-node-baseline.md`. It's chosen because:
- Long enough that prefill (`pp`) matters
- Open-ended enough that the model can't short-circuit
- Identical between runs (no RNG in the prompt itself)

## Common mistakes
- Running with a hot model loaded from a prior session and forgetting to flush — first-run numbers will look better than they are. Restart the daemon between runs.
- Not draining concurrent jobs — anything else competing for the GPU corrupts the measurement.
- Mean instead of median — one slow run skews the mean badly when sample size is 3.
- Forgetting `--gpu-layers` — defaults differ across llama.cpp versions and silently change what you measured.
- Recording `tok/s` without distinguishing prefill (`pp`) from generation (`tg`). They are very different numbers.

## References
- @docs/benchmarks/baseline-targets.md — what success looks like per phase
- @docs/benchmarks/single-node-baseline.md — single node protocol
- @docs/benchmarks/four-node-70b.md — foundation success criterion
