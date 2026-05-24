# Transport interface

## Purpose
Abstract the wire transport so we can swap ZeroMQ for UCX (RDMA) without rewriting ring logic.

## Required operations

```cpp
class Transport {
public:
  virtual ~Transport() = default;
  virtual Result<void> Connect(std::string_view peer_addr) = 0;
  virtual Result<void> Disconnect() = 0;
  virtual Result<void> Send(std::span<const std::byte> payload) = 0;
  virtual Result<std::vector<std::byte>> Recv(std::chrono::milliseconds timeout) = 0;
  virtual TransportStats Stats() const = 0;
};
```

## Implementations
- `zmq/zmq_transport.cpp` — ZeroMQ PUSH/PULL pairs (initial)
- `tcp/tcp_transport.cpp` — raw TCP fallback for debug
- `ucx/ucx_transport.cpp` — RDMA path (Phase 6+, not now)

## Invariants
1. `Send` is fire-and-forget at transport layer; ordering and retransmit are ring-layer concerns.
2. `Recv` returns one complete frame or times out. Partial frames are not exposed.
3. Implementations must be safe to destruct from any thread.

## Notes for implementers

- The PRP wire format (see `docs/primitives/prp.md`) is the *payload* from this interface's perspective. The transport does not parse it.
- `Send` may buffer internally but must not coalesce frames — every `Send` call corresponds to one frame on the wire.
- `Recv` blocks up to `timeout`. On timeout, returns an empty result (not an error). On connection loss, returns an error.
- `TransportStats` includes at minimum: `bytes_sent`, `bytes_received`, `frames_sent`, `frames_received`, `send_errors`, `recv_errors`, `current_send_queue_depth`. Implementations may add more.
- `Connect` is idempotent. Calling it twice on the same `peer_addr` is a no-op.
- Implementations must release any kernel-level resources (sockets, FDs, memory regions) in the destructor even if `Disconnect` was not called.

## What this interface intentionally does NOT cover
- Discovery — `peer_addr` is provided by the coordination layer.
- Authentication — single-network trusted environment; we don't authenticate ring peers in Phase 5.
- Retransmit — frames are best-effort; ring layer handles loss via epoch bumps.
- Backpressure — implementations may bound their send queue; if full, `Send` returns an error and the caller decides.
