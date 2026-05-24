# Piped-Ring Parallelism (PRP)

PRP is the data-plane organization for bigbrother: a logical ring of nodes that each own a contiguous block of model layers ("layer window") and pipeline hidden states around the ring. This spec defines the topology, wire format, sequencing, heartbeat, epoch lifecycle, and failure handling. The implementation lives under `src/core/ring/` and `src/transport/`.

## 1. Topology

Nodes are arranged in a single cycle. With `M` nodes the ring has `M` directed edges:

```
node_0 → node_1 → node_2 → ... → node_{M-1} → node_0
```

The plan (see `halda.md`) assigns each node a `[first_layer, last_layer]` interval. The intervals partition `{0..L-1}` exactly. Layer 0 starts on the head node (`headd`), which is also the entry/exit point for user requests.

A token's forward pass requires walking the entire ring **at least** once. With layer-window pipelining we can have multiple tokens in flight at different ring positions — that's what makes the ring stay busy.

### Rounds vs. windows

Let `avg_window = L / M`. With `k` total layer windows in the plan (`k ≥ M`), a single token completes its forward pass in `k / M` "rounds." A round is one full lap around the ring. In the common case `k = M`, one round per token.

The window concept exists for cases where one device has so much capacity it could hold more than `L/M` layers — Halda may then give it two windows split across two ring positions. We don't expect to use this in Phase 5 (single window per device is plenty), but the protocol supports it.

## 2. Wire format

Every data-plane frame has this layout. All integers little-endian.

```
+---------+---------+----------+---------+----------+========+---------+
| epoch   | seq     | frame_t  | length  | reserved | payld  | crc32   |
| u32 LE  | u32 LE  | u16 LE   | u16 LE  | u32 LE   |  N B   | u32 LE  |
+---------+---------+----------+---------+----------+========+---------+
  4 bytes   4 bytes   2 bytes    2 bytes    4 bytes   length    4 bytes
  └──────────────────── 16-byte header ───────────────────┘
```

Field semantics:

- `epoch` — incremented by `headd` on any ring membership change. Receivers reject frames whose epoch ≠ their current epoch.
- `seq` — monotonic per (epoch, sender). Resets to 0 on epoch change.
- `frame_type` — see table below.
- `length` — payload byte count. Must be ≤ 65535. Larger payloads are chunked at the ring layer using `frame_type = HIDDEN_STATE_CONT` (chunk continuation).
- `reserved` — zeroed on send, ignored on receive. Reserved for future flags (compression marker, priority, etc.).
- `payload` — type-specific.
- `crc32` — CRC32 of header || payload, zlib polynomial 0xEDB88320. Computed over everything before the CRC field itself.

### Frame types

| Value | Name              | Payload |
|-------|-------------------|---------|
| 0x01  | HIDDEN_STATE      | fp16 activations for the next layer, shape `[batch, hidden_dim]` |
| 0x02  | KV_REF            | Reference (handle, seq_id, range) to KV cache slice on another node |
| 0x03  | CONTROL           | Plan distribution, epoch bump notification, drain request |
| 0x04  | HEARTBEAT         | (UDP only, port 11002; never seen on the data ring) |
| 0x05  | DRAIN             | Node announces it's leaving cleanly |
| 0x06  | HIDDEN_STATE_CONT | Continuation chunk of a HIDDEN_STATE that exceeded 64 KB |

`HIDDEN_STATE` is the dominant frame type by volume.

## 3. Activation quantization

Phase 5 baseline: fp16 activations. At hidden_dim = 8192 and batch = 1, that's `8192 · 2 = 16384` bytes per token per hop. Sub-millisecond on 1 GbE, sub-microsecond on 10 GbE.

Future: INT8 with per-channel scales, for cases where the ring crosses a 1 GbE edge with high latency. Not in Phase 5. When we add it, it becomes a new `frame_type` value and a plan field declares which the ring is using.

## 4. Sequencing rules

Per (epoch, sender) pair:

- First frame after entering an epoch has `seq = 0`.
- Each subsequent frame has `seq = previous_seq + 1`.
- Receiver tracks `last_seen_seq` per (epoch, sender). Frames with `seq ≤ last_seen_seq` are dropped (duplicates or reorderings).
- Gaps (`seq > last_seen_seq + 1`) increment a `lost_frames` counter; the ring layer decides whether to NACK based on policy. For Phase 2-5 we use a fail-fast policy: any gap → escalate to `headd` for a replan. We can soften this later.

There is no per-frame ACK at the wire level. Liveness is detected via heartbeats on a separate channel.

## 5. Heartbeats

- **Channel:** UDP on port 11002.
- **Cadence:** every 250 ms, all-to-all (each node sends to every other node).
- **Payload:** `{epoch, sender_node_id, monotonic_timestamp_ns}`. ~32 bytes.
- **Failure detection:** 3 consecutive misses (≈ 750 ms) → declare peer down.

Heartbeats are intentionally on UDP, not on the data ring, for two reasons:
1. A stalled data pipe (e.g. waiting on a slow GPU) must not look like a dead node.
2. UDP avoids head-of-line blocking that affects TCP-based ZeroMQ sockets.

The trade-off is that we may occasionally see false-positive failures during a network blip. The cost of a spurious epoch bump is one replan (sub-second on small clusters), so we accept it.

## 6. Epoch lifecycle

```
   ┌──────────┐  3 missed hb     ┌──────────┐  scheduler.replan OK    ┌──────────┐
   │  ACTIVE  │ ───────────────▶ │ DEGRADED │ ──────────────────────▶ │  REPLAN  │
   └──────────┘                  └──────────┘                         └──────────┘
        ▲                              │                                    │
        │                              │ optibox.drain succeeded            │ plan distributed
        │                              ▼                                    ▼ + acked
        │                       ┌──────────┐                          ┌──────────┐
        └────────────────────── │  IDLE    │ ◀──────────────────────  │ ACTIVE'  │
                  manual start  └──────────┘                          └──────────┘
```

Transitions:

- **ACTIVE → DEGRADED:** any node reports 3 missed heartbeats from a peer.
- **DEGRADED → REPLAN:** `headd` confirms the dead peer (consulting optibox if available), bumps `epoch`, kicks Halda for a new plan.
- **REPLAN → ACTIVE:** new plan distributed via CONTROL frames; all surviving workers ACK; ring resumes at the new epoch.
- **DEGRADED → IDLE:** if too few nodes remain to make progress, headd parks the ring.

Only `headd` bumps the epoch. Workers report failures and apply plans; they do not unilaterally renumber the world.

## 7. Failure handling

| Symptom | Diagnosis | Response |
|---------|-----------|----------|
| 3 missed heartbeats from one peer | Node likely down | Bump epoch, exclude peer, replan |
| CRC mismatch on incoming frame | Wire corruption (or bug) | Drop frame, increment `crc_fail` counter, continue |
| `seq` gap | Lost frame | Escalate to headd for replan (Phase 5 policy; revisit later) |
| `epoch` mismatch | Stale frame from a prior epoch | Drop silently |
| Payload `length` > 65535 | Malformed | Drop frame, log error, optionally bump epoch if persistent |
| Transport `Send` blocks > 5s | Slow peer or buffer overflow | Tear down connection, treat as missed heartbeat |

## 8. Layer-window pipelining (the why)

A naive layer-parallel ring stalls each node for `(M-1) · per_node_latency` per token. Pipelining tokens — having node 0 start token T+1 while node M-1 finishes T — recovers most of the lost throughput. The effective TPOT is bounded below by `max_m per_node_latency_m + ring_latency`, not by the sum.

This works as long as:
- KV cache is consistent across nodes (each node owns the KV slices for its layers)
- The sampling step at the end of the ring can keep up
- Network bandwidth doesn't become the binding constraint

On 1 GbE with fp16 activations, the third condition holds easily. On 10 GbE the picture is even better.

## 9. Validation

A new ring implementation must pass:

- `tests/unit/ring_frame_test.cpp` — header parsing, CRC, length-bound checks (Phase 2)
- `tests/integration/two_node_ring_test.sh` — 1000 dummy tensors localhost, no losses (Phase 2 deliverable)
- `tests/cluster/ring_chaos_test.sh` — periodically kill -9 a worker, ring must recover (Phase 5+)

## References
- prima.cpp paper: https://arxiv.org/abs/2504.08791
- @docs/interfaces/transport.md
- @.claude/skills/ring-protocol/SKILL.md
