#!/usr/bin/env python3
"""Retrieve detail that compaction dropped from context but left on disk.

This is what makes compaction non-lossy: the archive index points at exact JSONL line
ranges, so any earlier turn can be pulled back on demand instead of being re-derived.

Usage:
  python recall.py "runpod pod id"            # search archives + transcripts
  python recall.py "auth" --session 6a1b19b8  # one session
  python recall.py --list                     # what is archived
  python recall.py --show 6a1b19b8 412        # print turns around a line number
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcript import ARCHIVE, find_transcript, iter_entries, text_of  # noqa: E402

FIELDS = ("files", "commands", "errors", "decisions", "prompts")


def archives(session=None):
    if not os.path.isdir(ARCHIVE):
        return
    for sid in sorted(os.listdir(ARCHIVE)):
        if session and not sid.startswith(session):
            continue
        d = os.path.join(ARCHIVE, sid)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    yield sid, json.load(fh)
            except (OSError, ValueError):
                continue


def cmd_list():
    n = 0
    for sid, rec in archives():
        n += 1
        counts = " ".join(f"{k}={len(rec.get(k, []))}" for k in FIELDS)
        print(f"{sid[:8]}  #{rec.get('seq')}  lines {rec.get('span')}  "
              f"{rec.get('ts', '')[:16]}  {counts}")
    if not n:
        print("no archives yet — they are written by the PreCompact hook on first compaction")


def cmd_show(session, line, radius):
    path = find_transcript(session)
    if not path:
        sys.exit(f"no transcript for session {session}")
    lo, hi = max(0, line - radius), line + radius
    for ln, e in iter_entries(path):
        if ln < lo:
            continue
        if ln > hi:
            break
        t = text_of(e).strip()
        if t:
            print(f"--- line {ln} [{e.get('type')}]\n{t[:2000]}\n")


def cmd_search(query, session, full):
    rx = re.compile(query, re.I)
    hits = 0
    for sid, rec in archives(session):
        matched = {k: [v for v in rec.get(k, []) if rx.search(v)] for k in FIELDS}
        if not any(matched.values()):
            continue
        hits += 1
        print(f"\n=== {sid[:8]} #{rec.get('seq')} lines {rec.get('span')} "
              f"({rec.get('ts', '')[:16]})")
        for k, vals in matched.items():
            for v in vals[:20 if full else 5]:
                print(f"  [{k}] {v}")
        print(f"  -> full turns: python recall.py --show {sid[:8]} <line>  "
              f"(span {rec.get('span')})")

    if not hits:
        # fall back to scanning transcripts directly — archives only cover compacted spans
        print(f"no archive match for /{query}/ — scanning transcripts directly")
        for root, _d, files in os.walk(os.path.expanduser("~/.claude/projects")):
            for f in files:
                if not f.endswith(".jsonl"):
                    continue
                if session and not f.startswith(session):
                    continue
                for ln, e in iter_entries(os.path.join(root, f)):
                    t = text_of(e)
                    if t and rx.search(t):
                        hits += 1
                        print(f"{f[:8]}:{ln} [{e.get('type')}] "
                              f"{t.strip()[:300].replace(chr(10), ' ')}")
                        if hits >= (200 if full else 30):
                            print("... truncated; narrow the query or pass --full")
                            return
    if not hits:
        print("no matches")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="?")
    p.add_argument("--session")
    p.add_argument("--list", action="store_true")
    p.add_argument("--show", nargs=2, metavar=("SESSION", "LINE"))
    p.add_argument("--radius", type=int, default=3)
    p.add_argument("--full", action="store_true")
    a = p.parse_args()

    if a.list:
        cmd_list()
    elif a.show:
        cmd_show(a.show[0], int(a.show[1]), a.radius)
    elif a.query:
        cmd_search(a.query, a.session, a.full)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
