#!/usr/bin/env python3
"""PreToolUse(Bash) hook — bound unbounded command output.

Uncapped command output enters context permanently and is re-sent on every subsequent
turn, so a single unbounded `git log` costs far more than the one turn it appears in.
This enforces token-saver rule R3 mechanically.

Behavior: appends `| head -N` to a narrow allowlist of known-noisy read-only commands.
On any ambiguity it emits `{}` and leaves the command exactly as written. It never
blocks, never denies, and never alters command semantics beyond truncating stdout.
"""
import json
import re
import sys

CAP = 200

# Narrow allowlist: read-only inspection commands that routinely dump unbounded output.
NOISY = re.compile(
    r"^\s*(cat|grep|rg|find|ls|git\s+log|git\s+diff|git\s+show|git\s+status|"
    r"npm\s+ls|pip\s+list|pytest|jest|go\s+test|cargo\s+test|docker\s+logs|"
    r"journalctl|dmesg|env|printenv)\s", re.I)

# Leave alone: anything with redirection, pipes, chaining, or an existing bound.
SKIP = re.compile(r"(\||>|<|&&|\|\||;|`|\$\(|head\b|tail\b|--quiet|\s-q\b|"
                  r"Select-Object|--max-count|-m\s*\d)", re.I)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("{}")
        return

    cmd = ((payload.get("tool_input") or {}).get("command") or "")
    if not cmd or "\n" in cmd or SKIP.search(cmd) or not NOISY.match(cmd):
        print("{}")
        return

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": {"command": f"{cmd.rstrip()} | head -{CAP}"},
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — a broken hook must never block a command
        print("{}")
    sys.exit(0)
