# mmap prefetch — defeating Linux page reclaim during pipelined inference

## 1. The problem

llama.cpp loads model weights via `mmap()` of the GGUF file. On a node with plenty of RAM the kernel keeps everything resident; we pay one disk-read cost on first access per page and then run from page cache. Good.

On nodes where RAM is tight relative to model size — which is most of our fleet, by design — the kernel reclaims pages we haven't touched recently. By the time the next ring round walks back to layer N on that node, layer N's pages have been evicted and we eat a major page fault. At ring scale this is the difference between 6 tok/s and 0.6 tok/s.

The naive fix is `mlock()`. It works but it's an all-or-nothing hammer: either the whole layer block stays locked (defeating the purpose of having an LRU) or we lock a subset and the rest pages out unpredictably. `mlock` also requires root or `CAP_IPC_LOCK`, which complicates deployment.

The right fix is **timed prefetch**: tell the kernel which pages we'll need *just before we need them*, using `madvise(MADV_WILLNEED)`. The kernel asynchronously reads them in, and they're warm in page cache by the time we access them.

The catch: if we issue `MADV_WILLNEED` too early, the kernel might page them back out before use (especially under memory pressure). Too late and we still take the fault. The trick is timing the `madvise` call against the **ring sequence number** — we know exactly which layer is coming because PRP makes the schedule explicit.

This is the "prefetch-release conflict" from the prima.cpp paper. The fix lives in `src/core/profiler/` (which determines the right prefetch depth per node) and `src/compute/` (which issues the `madvise` calls). The spec here describes the protocol.

## 2. The basic loop

Per ring node, per layer-window:

```
on each frame arrival (HIDDEN_STATE, sequence S):
    layer_index = current_window_first + (S mod window_size)
    target = layer_index + prefetch_depth
    if target ∈ this node's window:
        madvise(weights[target].addr, weights[target].bytes, MADV_WILLNEED)
    run forward pass for layer_index
    if S - prefetch_depth > 0:
        # pages we already used; let the kernel reclaim them naturally
        madvise(weights[layer_index - some_lag].addr, ..., MADV_DONTNEED)
```

`prefetch_depth` is the per-node knob. It's the number of layers ahead we hint to the kernel. Too small and we under-prefetch; too large and pages get evicted before use.

## 3. The knobs

| Knob | Meaning | Typical |
|------|---------|---------|
| `prefetch_depth` | Layers ahead to hint | 2–5 |
| `release_lag` | Layers behind before we `MADV_DONTNEED` | 8–16 |
| `trigger_frame` | Which frame_type kicks prefetch (HIDDEN_STATE only) | HIDDEN_STATE |
| `enabled` | Master switch | true |

These are per-node, set in the plan JSON (additive field, opt-in). Profiler measures the optimum per node in Phase 4.

## 4. Why this works on Linux

`MADV_WILLNEED` queues a read-ahead operation on the file backing the mmap. The kernel walks the page tables, finds missing pages in the requested range, and issues async reads into the page cache. The cost is amortized across the read-ahead window — much cheaper than synchronous on-demand faulting.

`MADV_DONTNEED` tells the kernel the pages can be reclaimed cheaply. On Linux, for file-backed mmaps, the pages stay in the page cache but are demoted on the LRU. The next access still pays nothing if they're still in cache; it pays a fault if reclaim happened. This means we can be aggressive with `DONTNEED` without much risk.

## 5. Verification

We can confirm prefetch is working via `/proc/self/stat` field 9 (major faults) and field 11 (minor faults). A correctly-tuned node sees major faults concentrated at startup (initial mmap touch) and near zero during steady-state inference.

Diagnostic:

```bash
# Run a 500-token generation, watch faults
cat /proc/$(pgrep clusterd)/stat | awk '{print "majf="$12, "minf="$10}'
```

A node with no prefetch sees major faults growing as the ring goes around. A correctly-tuned node sees a flat count after warmup. Phase 1 baseline must record the no-prefetch number for comparison.

## 6. Portability

Linux only. macOS has `madvise` with different semantics. Windows is irrelevant. We assert Linux at daemon startup; if someone tries to run `clusterd` on a non-Linux platform, we exit with a clear error.

## 7. Common mistakes

- **Calling `madvise` on a non-page-aligned range.** Linux requires page alignment for the start; length is rounded up. Use `posix_memalign`-equivalent math.
- **Issuing prefetch on every frame regardless of type.** Only `HIDDEN_STATE` advances layer pointers. Prefetching on CONTROL or HEARTBEAT does nothing useful and costs syscall overhead.
- **Forgetting `MADV_DONTNEED`.** Without explicit release hints, working set grows until the kernel reclaims under pressure — and that's the failure mode we're trying to avoid.
- **Tuning `prefetch_depth` on a hot system.** Profile on a cold node. Other load distorts the measurement.

## 8. Phase plan for this primitive

- Phase 1: not implemented. Single-node baseline runs without any madvise hints.
- Phase 2: still not implemented. Localhost ring; no memory pressure.
- Phase 3: optional. Hand-author `prefetch_depth = 2` in the static plan if Llama-3.2-1B on a tight node needs it.
- Phase 4: profiler measures the optimum per node; Halda emits it in plans.
- Phase 5: required. 70B on tight RAM nodes will not hit target tok/s without this.

## References
- prima.cpp paper: https://arxiv.org/abs/2504.08791 (section on prefetch-release conflict)
- `man 2 madvise`
- @docs/primitives/prp.md
