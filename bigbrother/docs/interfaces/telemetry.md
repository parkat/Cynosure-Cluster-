# Telemetry interface

## Purpose
Expose enough numbers — fast enough — that Halda can replan on changing conditions and humans can diagnose performance regressions. Prometheus-compatible format because that's what the optibox harness already speaks.

## Required operations

```cpp
class Telemetry {
public:
  virtual ~Telemetry() = default;

  // Counters monotonically increase.
  virtual Counter& counter(std::string_view name, std::span<const Label> labels) = 0;

  // Gauges can go up or down.
  virtual Gauge& gauge(std::string_view name, std::span<const Label> labels) = 0;

  // Histograms record distributions (latencies, sizes).
  virtual Histogram& histogram(std::string_view name,
                               std::span<const double> bucket_bounds,
                               std::span<const Label> labels) = 0;

  // Serve /metrics for Prometheus scrape.
  virtual void ServeOn(uint16_t port) = 0;
};
```

A single process holds one `Telemetry`. `counter`/`gauge`/`histogram` return references; updates are lock-free.

## Standard metrics (every clusterd emits these)

| Name | Type | Labels | What |
|------|------|--------|------|
| `bb_tokens_total` | Counter | `node`, `direction={in,out}` | Tokens crossing this node |
| `bb_ring_hop_seconds` | Histogram | `node`, `peer` | Per-hop latency for HIDDEN_STATE frames |
| `bb_kv_bytes` | Gauge | `node` | KV cache size on this node |
| `bb_heartbeats_missed_total` | Counter | `node`, `peer` | Missed heartbeats per peer |
| `bb_epoch` | Gauge | `node` | Current epoch (sanity check that all nodes agree) |
| `bb_crc_failures_total` | Counter | `node`, `peer` | CRC mismatches on incoming frames |
| `bb_layer_fwd_seconds` | Histogram | `node`, `gpu={0,1}` | Per-layer forward pass latency |
| `bb_page_faults_total` | Counter | `node`, `kind={major,minor}` | mmap fault counters |

## Emission rules

1. **Per-token, per-node, per-hop.** The histogram buckets must be tight enough to see millisecond differences.
2. **No allocation in the hot path.** Metric handles are looked up once at startup and cached.
3. **No serialization unless scraped.** Prometheus pulls on `/metrics` — no push.
4. **Labels are bounded cardinality.** `peer` is bounded by ring size; `node` is constant. Never use a label whose cardinality grows with traffic.

## Convention

- Port `9090` per node serves `/metrics` over plain HTTP (cluster subnet is trusted).
- Names are `bb_<noun>_<unit>` (`bb` for bigbrother). Units in the name (`_seconds`, `_bytes`, `_total` for counters).
- Histograms ship with sensible buckets per metric; do not let callers pick arbitrary bounds at runtime.

## Phase plan
- Phase 1-4: stub `Telemetry` impl writes to stderr in debug builds, no-op otherwise.
- Phase 5: real Prometheus exposition.
- Beyond: grafana dashboards live in `tools/grafana/`.
