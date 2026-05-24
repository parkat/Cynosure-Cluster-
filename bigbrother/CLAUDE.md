# bigbrother — heterogeneous LLM inference cluster

## What this is
Distributed inference engine on 30+ salvaged x86 nodes + 2× Tesla P100 + GTX 1060s.
Custom layer over llama.cpp's public C API. Target: 6-8 tok/s on Llama-3.3-70B.

## Read these BEFORE starting any non-trivial work
- @plan/CURRENT_PHASE.md — what we're working on now
- @plan/ROADMAP.md — the full phase plan
- @STATE.md — current cluster reality
- @DECISIONS.md — architectural decisions (don't relitigate)

## Read these IF the task touches them
- @docs/primitives/halda.md — for scheduler work
- @docs/primitives/prp.md — for transport work
- @docs/interfaces/*.md — for any cross-module API
- @ARCHITECTURE.md — for new module placement

## Hard rules (never violate)
1. Never modify vendor/llama.cpp/. Wrap it via include/llama.h only.
2. Never commit a benchmark result without showing the command that produced it.
3. Update plan/CURRENT_PHASE.md when you finish a task. This is how state persists.
4. Update STATE.md when cluster state changes.
5. Append to DECISIONS.md when you make an architectural choice. Don't edit old entries.
6. Run /handoff at end of session to write plan/handoffs/<date>-session-N.md.
7. Skill files live in .claude/skills/. Read SKILL.md before working in a domain.

## Conventions
- C++ 20, clang-format google style with 4-space indent.
- Python 3.11+, ruff + black.
- Tests required for src/core/* (pure logic). Optional for src/transport/* (I/O).
- All scripts in scripts/ must work from any directory.

## Subagent usage
- Heavy research (>20 file reads or web search) → spawn researcher subagent
- Multi-step debug across logs → spawn debugger subagent
- PR review → spawn reviewer subagent
- Focused implementation in a clean context → spawn implementer subagent
- Running benchmark protocols from docs/benchmarks/ → spawn benchmarker subagent
- Implementation (focused work, main session) → do it inline, don't spawn

## When stuck
1. Check plan/BLOCKED.md
2. Check DECISIONS.md
3. Search past handoffs in plan/handoffs/
4. Ask the human via /handoff with a specific question

## /compact policy
When summarizing this conversation:
- Preserve all file paths touched and reason for each change
- Keep exact commands that worked (for runbooks)
- Keep exact error messages and their fixes
- Discard exploration that didn't lead anywhere
