#!/usr/bin/env python3
"""SessionStart(matcher=compact) hook — inject a pointer to the archive, not its contents.

Keeps post-compaction context tiny while telling the agent that nothing was lost and
exactly how to retrieve it. Budget: ~200 tokens.
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/skills/token-saver"))
try:
    from transcript import ARCHIVE
except ImportError:
    sys.exit(0)

RECALL = "~/.claude/skills/token-saver/recall.py"


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    session = payload.get("session_id") or ""
    outdir = os.path.join(ARCHIVE, session)
    if not os.path.isdir(outdir):
        return
    entries = sorted(f for f in os.listdir(outdir) if f.endswith(".json"))
    if not entries:
        return

    files, spans, n = set(), [], 0
    for f in entries:
        try:
            with open(os.path.join(outdir, f), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        n += 1
        spans.append(rec.get("span"))
        for entry in rec.get("files", []):
            _, _, p = entry.partition(":")
            if p:
                files.add(os.path.basename(p))

    top = sorted(files)[:12]
    ctx = (
        f"CONTEXT ARCHIVE: {n} pre-compaction digest(s) for this session at {outdir} "
        f"(turn spans {spans}). Compaction summarized the context, but NOTHING was lost — "
        f"the full transcript is on disk and indexed.\n"
        f"Files touched earlier: {', '.join(top)}"
        f"{' …' if len(files) > len(top) else ''}\n"
        f"Before saying you lack earlier context, retrieve it:\n"
        f"  python {RECALL} \"<query>\"\n"
        f"Do NOT re-read or re-derive files listed above — recall them instead."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": ctx}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)
