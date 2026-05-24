# Current phase: 1 — Single-node llama_wrapper

**Status:** Not started. Phase 0 (scaffolding) complete and tagged `v0.0.0-scaffold` at 2026-05-24.

## Goal
Get llama.cpp wrapped behind our own C++ interface and prove a TinyLlama generation runs end-to-end on a single node.

## Next task (first thing to do this phase)
Add `vendor/llama.cpp` as a git submodule, pinned to a deliberately chosen stable release tag. Then write the new ADR recording the pinned SHA.

## Full task list
See `plan/ROADMAP.md` § Phase 1.

## Definition of done
`./build/headd --model models/tiny.gguf --prompt "hello"` prints generated tokens with no crash. Single-node baseline benchmark run and recorded in `plan/handoffs/bench-<date>-single-node-baseline.md`.

## Previous phase
**Phase 0 — Scaffolding.** Completed 2026-05-24 in session 1. See `plan/handoffs/2026-05-24-session-1-scaffold.md`.
