# optibox integration

bigbrother does not own physical state. Optibox does. This document defines the contract between the two.

## What optibox is

Optibox is a separate project: a Raspberry Pi per cluster node, wired into that node's PSU control / BMC / 12V relay / fan controller / temperature sensors. It exposes an MCP server on `pi-NN.local:8765` for each Pi `NN` and an aggregator endpoint on the head Pi.

bigbrother is a *client* of optibox. We never poke GPIOs or relays directly.

## Endpoints used by bigbrother

| MCP tool | Purpose | When called |
|----------|---------|-------------|
| `read_cpu_temp(node_id)` | Current CPU package temperature, °C | Halda profiler input; thermal-aware replan |
| `read_power_rails(node_id)` | 12V / 5V / 3.3V draw, watts | Diagnostics, eventual power-budget scheduling |
| `power_cycle(node_id)` | Hard power cycle (relay drop, wait, restore) | Recovery from unresponsive node |
| `set_freq_via_bios(node_id, freq_mhz)` | Set CPU frequency via BMC SMBIOS write | Future: thermal/power throttle response |
| `drain_node(node_id, deadline_s)` | Graceful: send SIGTERM, wait, then power-cycle | Planned node removal |

All return JSON. Error responses use HTTP 4xx/5xx and a `{"error":"..."}` body.

## Thermal subscription (push)

For thermal-aware scheduling, bigbrother subscribes to optibox's WebSocket at `ws://pi-head.local:8765/thermal` and receives events of the form:

```json
{
  "node_id": "p100a",
  "ts": 1716576000.123,
  "cpu_temp_c": 78.5,
  "gpu_temp_c": 82.0,
  "throttle_state": "near_limit"   // {nominal, near_limit, throttling, critical}
}
```

`throttle_state` thresholds are set in optibox config, not bigbrother. We just consume the labels.

`headd` reacts to `throttling` and `critical` events:

- `throttling`: log; mark device de-weighted (`compute_m *= 0.85`); kick Halda for next-epoch replan but don't bump the current epoch
- `critical`: bump epoch immediately, exclude the node, call `drain_node`

## Failure recovery flow

When the ring layer reports a node down (3 missed heartbeats):

```
1. headd: "node-X has missed heartbeats"
2. headd → optibox: read_cpu_temp(node-X)
   - if response: node still has BMC alive, likely software issue
   - if timeout: assume hardware down
3. headd → optibox: power_cycle(node-X)
4. headd: bump epoch, exclude node-X, replan
5. wait up to 90s for node-X to rejoin (clusterd auto-starts on boot)
6. if it rejoins: profiler re-runs, next replan considers it again
7. if it doesn't: stays excluded; log to plan/BLOCKED.md (manual)
```

## What we never do

- **Poke GPIOs ourselves.** Even if we could. The Pi is the boundary.
- **Trust a node that's missed heartbeats but `read_cpu_temp` says is fine.** It's a software issue; replan and restart `clusterd`, but don't reuse the node until at least one full epoch has elapsed without a miss.
- **Skip the `drain_node` step.** Hard cycling a node mid-decode loses in-flight work; drain gives `clusterd` a chance to ACK any pending tokens upstream.

## Configuration

`~/.config/bigbrother/optibox.toml` on the head node:

```toml
[optibox]
head_pi_host = "pi-head.local"
head_pi_port = 8765
thermal_ws_path = "/thermal"
request_timeout_ms = 2000
reconnect_backoff_ms = 1000
```

Per-node Pi addresses are looked up via the aggregator's `/nodes` endpoint at startup. If aggregator is unreachable, bigbrother starts in **degraded mode**: no thermal subscription, no power-cycle recovery, no `drain`. Logs a warning and continues.

## Test seam

For local development without real Pis, `BB_OPTIBOX_MOCK=1` makes `headd` use an in-process mock optibox that always returns "nominal" thermals and no-ops on `power_cycle`. Used in `tests/integration/` (Phase 5).
