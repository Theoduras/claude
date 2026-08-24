"""Shared Claude Code transcript (JSONL) parsing.

Used by measure.py, recall.py, and the hooks in ~/.claude/hooks/.
Keep this dependency-free (stdlib only) — hooks run in whatever Python is on PATH.
"""
import json
import os
from datetime import datetime

PROJECTS = os.path.expanduser("~/.claude/projects")
ARCHIVE = os.path.expanduser("~/.claude/context-archive")


def parse_ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def iter_entries(path):
    """Yield (line_no, dict) for each parseable JSONL line. Never raises."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError:
                continue


def usage_of(entry):
    return (entry.get("message") or {}).get("usage")


def blocks(entry, kind):
    """Yield content blocks of a given type from an entry's message."""
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    for b in content:
        if isinstance(b, dict) and b.get("type") == kind:
            yield b


def text_of(entry):
    """Flatten an entry's message content to plain text."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text") or "")
    return "\n".join(out)


def find_transcript(session_id):
    """Locate a transcript JSONL by (possibly partial) session id."""
    for root, _dirs, files in os.walk(PROJECTS):
        for f in files:
            if f.endswith(".jsonl") and f.startswith(session_id):
                return os.path.join(root, f)
    return None
