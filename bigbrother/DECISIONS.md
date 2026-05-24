# Architectural Decision Records

Append-only. Never edit past entries. Format: ADR-NNN — Title — Date — Status.

---

## ADR-001 — Wrap llama.cpp via public C API, do not fork the codebase — 2026-05-24 — Accepted

**Context:** prima.cpp shows the value of distributed inference but has a fragile upstream (Gitee, single team, account-suspension risk). Forking prima.cpp inherits ~20K LoC of research code. Forking llama.cpp directly is ~500K LoC we have to maintain.

**Decision:** Use llama.cpp as a git submodule, integrate via its public C API in `include/llama.h`. Our code lives in `src/`. Re-implement prima.cpp's three valuable contributions (Halda scheduler, PRP ring, mmap prefetch) as our own modules.

**Consequences:** We can pin to known-good llama.cpp commits and bump on our schedule. We benefit from upstream kernel work for free. Integration surface is the documented C API.

---

## ADR-002 — ZeroMQ as initial ring transport, abstracted behind src/transport/interface.h — 2026-05-24 — Accepted

**Context:** Need a transport for the PRP ring. Options: ZeroMQ, raw TCP, gRPC, UCX.

**Decision:** ZeroMQ for v0. Abstract behind `src/transport/interface.h` so UCX can swap in later when 10GbE/RDMA hardware is online.

**Consequences:** Fast initial development. Migration path to RDMA exists.

---

## ADR-003 — CUDA toolchain pinned to 12.6 for Pascal support — 2026-05-24 — Accepted

**Context:** CUDA 13 deprecated Pascal (sm_60). cuDNN 9.11+ dropped Pascal. PyTorch 2.8 CUDA 12.8/12.9 wheels removed CC 5.x/6.x/7.x. Our 2× P100s are CC 6.0.

**Decision:** Pin CUDA to 12.6 across the cluster. Bake binaries with CUDA 12.6 toolchain into deployment image.

**Consequences:** No newer CUDA features. P100 stays supported through 2027+.
