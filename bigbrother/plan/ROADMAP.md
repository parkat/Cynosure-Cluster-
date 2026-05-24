# Roadmap — bigbrother foundation

## Phase 0 — Scaffolding ✅ (when this session ends)

Directory structure, CLAUDE.md, planning docs, subagents, skills, hooks.

## Phase 1 — Single-node llama_wrapper [ ]

Tasks:
- [ ] Add vendor/llama.cpp submodule at pinned commit
- [ ] CMakeLists.txt with BUILD_SHARED_LIBS=ON for llama.cpp
- [ ] src/compute/llama_wrapper.{h,cpp}
- [ ] src/daemons/headd/main.cpp (load + generate + stdout)
- [ ] tests/unit/llama_wrapper_test.cpp using TinyLlama 1.1B Q4_0
- [ ] tests/fixtures/ download script
- [ ] scripts/bootstrap-dev.sh
- [ ] Run single-node baseline benchmark

Deliverable: `./build/headd --model models/tiny.gguf --prompt "hello"` prints tokens.

## Phase 2 — Transport + ZMQ ring [ ]

Tasks:
- [ ] Finalize docs/primitives/prp.md
- [ ] src/transport/interface.h
- [ ] src/transport/zmq/zmq_transport.{h,cpp}
- [ ] src/core/ring/ring_state.{h,cpp}
- [ ] src/coord/ring_manager.cpp
- [ ] tests/integration/two_node_ring_test.sh

Deliverable: 1000 random tensors ring-pass on localhost, no losses.

## Phase 3 — Static plan + manual sharding [ ]

Tasks:
- [ ] src/core/plan/plan.{h,cpp}
- [ ] src/core/plan/plan_io.cpp (JSON)
- [ ] src/compute/layer_dispatch.cpp (hardest task — partial model loading)
- [ ] Hand-written 2-node plan for Llama-3.2-1B
- [ ] tests/cluster/two_node_7b.sh

Deliverable: Coherent text across 2 real nodes.

## Phase 4 — Profiler + Halda [ ]

Tasks:
- [ ] src/core/profiler/profiler.cpp
- [ ] src/core/scheduler/halda.cpp (HiGHS-linked)
- [ ] tests/unit/halda_test.cpp
- [ ] tools/plan_inspector.py

Deliverable: Halda plan ≥ hand-written plan on Phase 3.

## Phase 5 — Four-node 70B [ ]  ← FOUNDATION DONE

Tasks:
- [ ] src/coord/discovery.cpp
- [ ] src/coord/heartbeat.cpp
- [ ] src/api/openai_server.cpp
- [ ] deploy/ansible/ playbook
- [ ] scripts/flash-node.sh
- [ ] Run four-node-70b benchmark

Deliverable: Llama-3.3-70B coherent text via /v1/completions on cluster.

## Beyond foundation
Speculative decoding, 10 GbE RDMA, telemetry polish, multi-LoRA, MoE scheduling, optibox thermal integration, SSE4.1 kernels.
