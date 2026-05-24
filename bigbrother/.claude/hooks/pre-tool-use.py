#!/usr/bin/env python3
"""Block dangerous operations before they execute."""
import json
import sys

def main():
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool == "Bash":
        cmd = tool_input.get("command", "")
        dangerous = ["rm -rf /", "rm -rf ~", "mkfs", ":(){:|:&};:", "dd if=/dev/zero of=/dev/"]
        for pattern in dangerous:
            if pattern in cmd:
                print(f"BLOCKED: dangerous command pattern '{pattern}'", file=sys.stderr)
                sys.exit(2)

    if tool in ("Edit", "Write"):
        path = tool_input.get("file_path", "")
        if "vendor/llama.cpp" in path:
            print("BLOCKED: vendor/llama.cpp is read-only (CLAUDE.md rule 1)", file=sys.stderr)
            sys.exit(2)

    sys.exit(0)

if __name__ == "__main__":
    main()
