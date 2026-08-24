#!/usr/bin/env python3
"""PreCompact hook — archive a structured digest before context is compacted.

Compaction drops detail from context, not from disk. This writes a greppable index
of everything the about-to-be-compacted span contained, so `recall.py` can pull any
of it back later. Nothing is deleted.

Contract: reads the hook payload JSON on stdin, ALWAYS exits 0.
A crashing or slow hook must never block compaction.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/.claude/skills/token-saver"))
try:
    from transcript import ARCHIVE, blocks, iter_entries, text_of
except ImportError:
    sys.exit(0)

MAX_ITEMS = 400        # cap per category so archives stay small
MAX_CMD_LEN = 300
MAX_TEXT_LEN = 600

ERROR_HINTS = ("error", "exception", "traceback", "failed", "fatal",
               "not found", "denied", "refused")


def dedupe(seq, limit):
    seen, out = set(), []
    for x in seq:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        if len(out) >= limit:
            break
    return out


def digest(path, start_line):
    files, commands, errors, decisions, prompts = [], [], [], [], []
    last_line = start_line
    for ln, e in iter_entries(path):
        if ln < start_line:
            continue
        last_line = ln
        etype = e.get("type")

        if etype == "user":
            t = text_of(e).strip()
            # skip tool_result-only turns and system reminders
            if t and not t.startswith("<"):
                prompts.append(t[:MAX_TEXT_LEN])

        for b in blocks(e, "tool_use"):
            name = b.get("name") or ""
            inp = b.get("input") or {}
            if name in ("Read", "Edit", "Write", "NotebookEdit"):
                fp = inp.get("file_path")
                if fp:
                    files.append(f"{name}:{fp}")
            elif name in ("Bash", "PowerShell"):
                cmd = (inp.get("command") or "").replace("\n", " ")[:MAX_CMD_LEN]
                if cmd:
                    commands.append(cmd)
            elif name in ("Grep", "Glob"):
                pat = inp.get("pattern")
                if pat:
                    commands.append(f"{name}: {pat}")

        for b in blocks(e, "tool_result"):
            c = b.get("content")
            txt = c if isinstance(c, str) else json.dumps(c)[:MAX_TEXT_LEN]
            low = txt.lower()
            if b.get("is_error") or any(h in low for h in ERROR_HINTS):
                errors.append(txt.replace("\n", " ")[:MAX_TEXT_LEN])

        if etype == "assistant":
            t = text_of(e).strip()
            if t:
                # first line of each assistant turn is the closest thing to a decision log
                decisions.append(t.split("\n", 1)[0][:MAX_TEXT_LEN])

    return dict(
        files=dedupe(files, MAX_ITEMS),
        commands=dedupe(commands, MAX_ITEMS),
        errors=dedupe(errors, 100),
        decisions=dedupe(decisions, MAX_ITEMS),
        prompts=dedupe(prompts, 100),
        last_line=last_line,
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    path = payload.get("transcript_path")
    session = payload.get("session_id") or "unknown"
    if not path or not os.path.exists(path):
        return

    outdir = os.path.join(ARCHIVE, session)
    os.makedirs(outdir, exist_ok=True)

    # resume from where the previous archive for this session stopped
    prior = sorted(f for f in os.listdir(outdir) if f.endswith(".json"))
    seq = len(prior) + 1
    start = 0
    if prior:
        try:
            with open(os.path.join(outdir, prior[-1]), encoding="utf-8") as fh:
                start = json.load(fh).get("span", [0, 0])[1] + 1
        except (OSError, ValueError, KeyError, IndexError):
            start = 0

    d = digest(path, start)
    rec = {
        "session": session,
        "seq": seq,
        "trigger": payload.get("trigger") or payload.get("matcher") or "auto",
        "ts": datetime.now(timezone.utc).isoformat(),
        "span": [start, d.pop("last_line")],
        "jsonl": os.path.abspath(path),
        "cwd": payload.get("cwd"),
        **d,
    }
    tmp = os.path.join(outdir, f"{seq:04d}.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(outdir, f"{seq:04d}.json"))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — never block compaction
        pass
    sys.exit(0)
