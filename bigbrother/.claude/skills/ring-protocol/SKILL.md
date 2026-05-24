---
name: ring-protocol
description: When changing ring framing, sequence rules, heartbeats, or epoch handling.
---

# Ring protocol (PRP wire format)

## When this applies
- Editing anything under `src/core/ring/`, `src/transport/`, `src/coord/ring_manager.cpp`
- Adding new frame types
- Changing heartbeat or epoch semantics

## Core invariants
1. **Frames are atomic.** A frame is delivered in full or not at all. Transports do not expose partial frames.
2. **Sequence numbers are monotonic within an epoch.** Receivers reject frames with seq ≤ last_seen_seq for the current epoch.
3. **Sequence resets on epoch bump.** New epoch ⇒ seq starts at 0.
4. **CRC is verified before any other processing.** A bad CRC = silently drop and increment counter; don't ACK, don't NACK.
5. **Heartbeats run on a separate channel.** UDP 11002. They do not consume sequence numbers.
6. **Epoch bumps come from the head daemon only.** Workers detect failures and report; only `headd` declares a new epoch.

## Wire format

```
+---------+---------+----------+---------+----------+========+---------+
| epoch   | seq     | frame_t  | length  | reserved | payld  | crc32   |
| u32 LE  | u32 LE  | u16 LE   | u16 LE  | u32 LE   |  N B   | u32 LE  |
+---------+---------+----------+---------+----------+========+---------+
  4 bytes   4 bytes   2 bytes    2 bytes    4 bytes   length    4 bytes
  └──────────────────── 16-byte header ───────────────────┘
```

- `length` is the size of `payload` in bytes (not including the trailing CRC).
- `length` max is 65535 bytes. Larger payloads must be chunked at the ring layer.
- `crc32` is computed over header + payload (not over the CRC field itself), using the standard zlib polynomial (0xEDB88320).
- All multi-byte ints are little-endian.

## Frame types

| Value | Name          | Purpose |
|-------|---------------|---------|
| 0x01  | HIDDEN_STATE  | Activations flowing forward through the ring |
| 0x02  | KV_REF        | Reference to KV cache slice (not the slice itself) |
| 0x03  | CONTROL       | Plan distribution, replan triggers, epoch bumps |
| 0x04  | HEARTBEAT     | Liveness probe; carried on UDP 11002, not on the data ring |
| 0x05  | DRAIN         | Node announces it's leaving the ring cleanly |

## Timing
- **Heartbeat cadence:** 250 ms.
- **Failure detection:** 3 missed heartbeats (≈750 ms) → declare peer down.
- **Replan budget:** new plan must be on every surviving node ≤ 2 s after epoch bump. If not, the ring stalls and headd retries.

## Epoch state machine

```
   ┌──────────┐  3 missed hb     ┌──────────┐
   │  ACTIVE  │ ───────────────▶ │ DEGRADED │
   └──────────┘                  └──────────┘
        ▲                              │
        │ scheduler.replan ok          │ ask headd
        │                              ▼
        │                       ┌──────────┐
        └────────────────────── │ REPLAN   │
                                └──────────┘
```

On entering REPLAN: headd increments epoch, recomputes plan excluding the dead node, broadcasts plan via CONTROL frames, waits for ack, returns to ACTIVE.

## Common mistakes
- Trusting `length` before verifying CRC — a corrupt length lets an attacker (or a flaky NIC) cause OOM. Bound-check first, then CRC, then trust.
- Using a sequence number from a stale epoch — always check `epoch == current_epoch` first.
- Doing replan work on a worker — only headd decides the plan; workers apply it.
- Sending HEARTBEAT on the data ring — they go on a separate UDP socket precisely so a stuck data pipe doesn't cause false failovers.

## References
- @docs/primitives/prp.md — full PRP spec
- @docs/interfaces/transport.md — transport contract
- @DECISIONS.md — ADR-002 (ZeroMQ initial)
- arXiv 2504.08791 — prima.cpp paper
