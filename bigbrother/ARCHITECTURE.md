# bigbrother — Architecture

## Overview

bigbrother is a distributed LLM inference engine designed to extract usable throughput from a heterogeneous fleet of salvaged consumer/server hardware: ~30 x86 nodes of mixed vintage, 2× Tesla P100 (16 GB, sm_60), and 3-4× GTX 1060 (6 GB, sm_61), all on a 1 GbE backbone with a 10 GbE DAC link between the two P100 boxes. The system is engineered for the cheap, slow, asymmetric case: nodes drop in and out, RAM is the binding resource, the network is the dominant cost, and there is no shared filesystem.

The headline workload is Llama-3.3-70B at Q4_K_M (~40 GB on disk, ~46 GB live) split across 3-4 nodes with a target steady-state generation rate of 6-8 tok/s. The architecture is also intended to scale up to frontier MoE models when more nodes are online.

## Three-layer design

The system is divided into three layers with explicit interfaces between them.

### 1. Compute layer (`src/compute/`)

Owns model execution on a single node. Wraps llama.cpp via its public C API (`include/llama.h` in the submodule) — see ADR-001. The compute layer is responsible for:

- Loading a subset of model layers (a "shard") into RAM/VRAM
- Running forward passes on hidden-state tensors received from upstream
- Emitting hidden states downstream
- Reporting profiled latencies and memory usage upstream to the scheduler

The compute layer does not know about the ring topology, peer addresses, or the global plan. It is told "run layers L..M on this input" and produces an output.

### 2. Coordination layer (`src/coord/`)

Owns the distributed runtime: ring formation, heartbeats, epoch management, transport, scheduling, plan distribution. Coordination knows about every node but does not know how to run a model. Subdivisions:

- `src/core/scheduler/` — Halda solver: decides which node runs which layers (see `docs/primitives/halda.md`)
- `src/core/ring/` — Piped-Ring Parallelism state machine (see `docs/primitives/prp.md`)
- `src/core/profiler/` — Measures per-device latency/bandwidth for scheduler input
- `src/core/plan/` — Plan representation, JSON I/O, validation
- `src/transport/` — Wire transport abstraction (ZeroMQ now, UCX later) — see ADR-002
- `src/coord/discovery.cpp` — Node discovery via UDP multicast on cluster subnet
- `src/coord/heartbeat.cpp` — Liveness; 250 ms cadence, 3 missed → epoch bump
- `src/coord/ring_manager.cpp` — Lifecycle of the ring, replans on topology change

### 3. API layer (`src/api/`)

Owns external requests. An OpenAI-compatible HTTP server (`/v1/completions`, `/v1/chat/completions`) at port 8080 on the head node accepts requests, packages them as ring jobs, and streams tokens back to the client.

## Why wrap llama.cpp rather than fork it

See ADR-001 for the full rationale. Short version: llama.cpp is ~500K LoC under active development by a healthy upstream. Its public C API (in `include/llama.h`) is small, stable, and exposes everything we need: model loading, KV cache control, token streaming, per-layer execution. By pinning to a known-good commit and depending only on documented entry points, we get upstream kernel improvements for free and pay zero maintenance cost on the parts we don't touch.

We re-implement three things prima.cpp pioneered, as our own first-party modules:

1. **Halda scheduler** — ILP-based layer assignment across heterogeneous devices
2. **Piped-Ring Parallelism (PRP)** — Cross-node pipeline with layer windows, not just micro-batches
3. **mmap prefetch** — Time `madvise(MADV_WILLNEED)` against ring sequence numbers to defeat Linux's eager page reclaim

These three primitives are documented in `docs/primitives/`.

## Halda scheduler (high level)

Halda is an Integer Linear Fractional Program that assigns layer windows and (per-device) GPU layer counts across a heterogeneous fleet. Inputs are per-device profiles (memory budget, compute throughput, link bandwidth) and the model topology (per-layer FLOPs, KV footprint). The objective minimizes per-stage TPOT (time-per-output-token) subject to RAM/VRAM/disk constraints.

The full spec lives in `docs/primitives/halda.md`. We also support a `--static-plan plan.json` bypass mode so we can hand-author plans during early phases before the solver works.

Halda is one implementation of the `Scheduler` interface (see `docs/interfaces/scheduler.md`). A second implementation, `StaticPlanScheduler`, just loads a plan from disk and validates it.

## Piped-Ring Parallelism (high level)

The ring is a logical cycle of nodes; layers of the model are partitioned across nodes in contiguous blocks ("layer windows"). A token's forward pass walks the ring once per "round," where each round covers `L / (M · avg_window)` layers per node. Once a node finishes its layers in round k, it streams the hidden state to the next node and immediately begins round k+1 on the next token (or the next request's token).

This decouples model depth from request batching. With careful pipelining, the ring stays busy even when there's only one user with one prompt — which is the regime we care about.

Wire format and failure semantics are in `docs/primitives/prp.md`. Briefly:

- 16-byte header (epoch, sequence, frame_type, length, reserved) + payload + CRC32
- Sequence numbers monotonic within an epoch
- Heartbeats every 250 ms
- 3 missed heartbeats → epoch bump → exclude node → ask scheduler to replan

## Transport abstraction

`src/transport/interface.h` (interface documented in `docs/interfaces/transport.md`) defines the wire contract. Implementations:

- `src/transport/zmq/` — ZeroMQ PUSH/PULL pairs. Initial. Works over any IP network.
- `src/transport/tcp/` — Raw TCP. For debugging when ZMQ misbehaves.
- `src/transport/ucx/` — UCX/RDMA. Phase 6+, not built yet.

Ring code talks to `Transport*` only. Swapping transports is a flag flip.

## Optibox integration

The optibox harness is a separate project that provides out-of-band power/thermal control via Raspberry Pis bolted to each node. It exposes an MCP server at `pi.local:8765` with tools for `read_cpu_temp`, `read_power_rails`, `power_cycle`, `set_freq_via_bios`, and `drain_node`.

bigbrother integrates with optibox at two points:

1. **Scheduler input.** Halda subscribes to thermal telemetry. A node trending toward thermal throttle gets de-weighted in the next solve.
2. **Recovery.** When a node misses heartbeats, the coordination layer may ask optibox to power-cycle it via `drain_node`. Optibox is the authority on physical state; bigbrother is the authority on logical role.

The integration contract is documented in `docs/deployment/optibox-integration.md`.

## Daemons

Two long-lived processes:

- `headd` (head daemon) — Runs on one node (currently p100a). Hosts the API server, owns the global plan, drives the scheduler.
- `clusterd` (cluster daemon) — Runs on every worker. Holds a model shard, services its layer window, reports profiles upstream.

The head can also be a worker (and usually is — we don't waste P100 VRAM).

## Data flow through the ring (4-node case)

```
                  ┌─────────────────────────────────────────┐
                  │                                         │
                  ▼                                         │
  ┌───────┐   ┌───────┐   ┌───────┐   ┌───────┐   ┌───────┐ │
  │ user  │──▶│ headd │──▶│ p100a │──▶│ p100b │──▶│ 1060a │─┘
  │ HTTP  │   │ tokn. │   │ L0-19 │   │ L20-49│   │ L50-79│
  └───────┘   └───────┘   └───────┘   └───────┘   └───────┘
                  ▲                                         ▲
                  │                                         │
                  └─────── streamed tokens back ────────────┘

  Per token:
    1. headd tokenizes prompt + sampling state
    2. ring frame goes p100a → p100b → 1060a (hidden states only)
    3. last node samples next token, streams it back to headd
    4. headd streams to HTTP client (SSE for /v1/completions stream)
    5. headd appends sampled token, kicks ring for next position

  Heartbeats: every 250 ms on UDP 11002, all-to-all gossip.
  Control:    ZMQ ROUTER socket on TCP 11001 per node.
  Data:       ZMQ PULL on TCP 11000 (next-hop), PUSH from prev-hop.
```

`headd` is logically "outside" the ring for control but inside it for data when its node also holds layers (which is the normal case).

## Module placement guide

When adding new code, place it as follows:

| Concern | Directory |
|---|---|
| Pure logic with no I/O (plans, profiles, math) | `src/core/` |
| Wire transport | `src/transport/<name>/` |
| Model execution wrapping llama.cpp | `src/compute/` |
| Coordination state machines (ring, discovery, heartbeat) | `src/coord/` |
| External-facing HTTP/gRPC | `src/api/` |
| Metrics emission | `src/telemetry/` |
| Optibox / hardware integration | `src/optibox/` |
| Long-lived daemon entry points | `src/daemons/<name>/` |

Tests mirror the source tree in `tests/unit/`. Integration tests that spin up multiple processes go in `tests/integration/`. Tests that require >1 physical node go in `tests/cluster/`.
