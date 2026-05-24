# Four-node 70B — FOUNDATION SUCCESS CRITERION

## Purpose
Demonstrates Phase 5 done.

## Prerequisites
- 4 nodes online: p100a, p100b, 1060a, cpu1
- 10 GbE DAC between p100a/p100b
- Halda has emitted /tmp/plan.json
- Binaries deployed
- GGUF at /opt/models/ on all 4

## Protocol
1. `ssh <node> 'systemctl start bigbrother-clusterd'` on all workers
2. Wait for all heartbeats (timeout 30s)
3. `systemctl start bigbrother-headd` on p100a
4. Warmup: `curl -X POST localhost:8080/v1/completions -d '{"prompt":"hello","max_tokens":50}'` (discard)
5. Measure (3×): same with 500 tokens and canonical prompt
6. Capture Prometheus: per-node util, per-hop latency, KV size

## Success
- Coherent text (manually verified)
- >1 tok/s end-to-end on at least one run
- No OOM
- 500 tokens generated without ring failure

Not implemented yet — Phase 5.
