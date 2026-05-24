#!/usr/bin/env python3
"""Update STATE.md after a successful commit."""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = payload.get("tool_input", {}).get("command", "")
    if "git commit" not in cmd:
        sys.exit(0)

    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        sys.exit(0)

    state_path = Path("STATE.md")
    if not state_path.exists():
        sys.exit(0)

    content = state_path.read_text()
    today = datetime.now().strftime("%Y-%m-%d")
    content = re.sub(r"Last updated: .*", f"Last updated: {today}", content)
    content = re.sub(r"HEAD commit: .*", f"HEAD commit: {sha}", content)
    state_path.write_text(content)
    sys.exit(0)

if __name__ == "__main__":
    main()
