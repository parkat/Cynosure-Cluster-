#!/usr/bin/env python3
"""Inject current project state at session start."""
import json
import os
import subprocess
import sys
from pathlib import Path

def read(path, max_lines=None):
    try:
        p = Path(path)
        if not p.exists():
            return None
        text = p.read_text()
        if max_lines:
            text = "\n".join(text.splitlines()[:max_lines])
        return text
    except Exception:
        return None

def main():
    repo_root = Path.cwd()
    while not (repo_root / ".claude").exists() and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    os.chdir(repo_root)

    sections = []

    current = read("plan/CURRENT_PHASE.md")
    if current:
        sections.append(f"## Current phase\n\n{current}")

    state = read("STATE.md", max_lines=40)
    if state:
        sections.append(f"## Cluster state\n\n{state}")

    handoff_dir = Path("plan/handoffs")
    if handoff_dir.exists():
        handoffs = sorted([h for h in handoff_dir.glob("*.md") if h.name != ".gitkeep"], reverse=True)[:3]
        if handoffs:
            sections.append("## Recent handoffs")
            for h in handoffs:
                sections.append(f"### {h.name}\n\n{read(h, max_lines=30)}")

    try:
        status = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=3)
        log = subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True, timeout=3)
        sections.append(f"## Git\n\n```\n{status.stdout}\n```\n\n```\n{log.stdout}\n```")
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(sections),
        }
    }
    print(json.dumps(output))
    sys.exit(0)

if __name__ == "__main__":
    main()
