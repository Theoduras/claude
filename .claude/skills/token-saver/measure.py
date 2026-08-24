#!/usr/bin/env python3
"""Measure real token spend per Claude Code session from transcript JSONL.

Units: raw tokens and % of the 5-hour rolling limit.

The 5h limit is opaque, so it is CALIBRATED from your own history: the busiest
5-hour window you have ever run is treated as ~100%. Override with:
    set TOKEN_SAVER_5H_BUDGET=250000000      (Windows)
    export TOKEN_SAVER_5H_BUDGET=250000000   (bash)

Usage:
  python measure.py                 # all sessions, newest first
  python measure.py --last 10       # only last N sessions
  python measure.py --compare N     # baseline (older) vs treatment (newest N)
  python measure.py --calibrate     # show busiest 5h windows -> the budget basis
  python measure.py --session <id>
"""
import argparse, glob, json, os, sys
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = os.path.expanduser("~/.claude/projects")
WINDOW = timedelta(hours=5)

# Weighting used only to compare cheap vs expensive tokens against a limit.
# Cache reads are ~1/10 the weight of fresh input; output is heaviest.
WEIGHT = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}


def parse_ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def scan(path):
    """Return (totals, events) for one transcript. events = [(ts, raw, weighted)]."""
    t = dict(input=0, cache_write=0, cache_read=0, output=0,
             turns=0, tools=0, mtime=os.path.getmtime(path))
    events = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return None, []
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            if not u:
                continue
            parts = {
                "input": u.get("input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "output": u.get("output_tokens", 0),
            }
            for k, v in parts.items():
                t[k] += v
            t["turns"] += 1
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    t["tools"] += 1
            ts = parse_ts(d.get("timestamp"))
            if ts:
                events.append((ts, sum(parts.values()),
                               sum(parts[k] * WEIGHT[k] for k in parts)))
    return (t, events) if t["turns"] else (None, [])


def load():
    out, all_ev = [], []
    for f in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        t, ev = scan(f)
        if t:
            t["id"] = os.path.splitext(os.path.basename(f))[0]
            t["raw"] = t["input"] + t["cache_write"] + t["cache_read"] + t["output"]
            t["weighted"] = sum(t[k] * WEIGHT[k] for k in WEIGHT)
            out.append(t)
            all_ev += ev
    return sorted(out, key=lambda x: x["mtime"], reverse=True), sorted(all_ev)


def windows(events):
    """Max weighted load over any 5h rolling window, plus the top windows."""
    peaks, j, cur = [], 0, 0.0
    for i, (ts, _raw, w) in enumerate(events):
        cur += w
        while events[j][0] < ts - WINDOW:
            cur -= events[j][2]
            j += 1
        peaks.append((cur, ts))
    return sorted(peaks, reverse=True)


def budget(events):
    env = os.environ.get("TOKEN_SAVER_5H_BUDGET")
    if env:
        return float(env), "env TOKEN_SAVER_5H_BUDGET"
    if events:
        peak = windows(events)[0][0]
        return peak, "calibrated: busiest observed 5h window"
    return 1.0, "unknown"


def fmt(n):
    n = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            return f"{n/div:.1f}{suf}"
    return f"{n:.0f}"


def agg(group):
    a = defaultdict(float)
    for s in group:
        for k in ("input", "cache_write", "cache_read", "output",
                  "turns", "tools", "raw", "weighted"):
            a[k] += s[k]
    a["sessions"] = len(group)
    return a


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--last", type=int)
    p.add_argument("--compare", type=int, metavar="N")
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--session")
    a = p.parse_args()

    ss, events = load()
    if not ss:
        sys.exit("no transcripts found under " + ROOT)
    B, basis = budget(events)

    if a.calibrate:
        print(f"5h budget basis: {basis}")
        print(f"budget = {fmt(B)} weighted tokens per 5h window\n")
        print("busiest distinct 5h windows:")
        seen = []
        for w, ts in windows(events):
            if all(abs((ts - t).total_seconds()) > WINDOW.total_seconds() for t in seen):
                seen.append(ts)
                print(f"  {ts:%Y-%m-%d %H:%M}  {fmt(w):>8} weighted  {w/B*100:5.1f}%")
            if len(seen) >= 8:
                break
        return

    if a.session:
        ss = [s for s in ss if s["id"].startswith(a.session)]

    if a.compare:
        treat, base = ss[:a.compare], ss[a.compare:]
        if not base:
            sys.exit("not enough sessions for a baseline")
        T, Bs = agg(treat), agg(base)
        pairs = [("weighted/turn", T["weighted"] / T["turns"], Bs["weighted"] / Bs["turns"]),
                 ("raw/turn",      T["raw"] / T["turns"],      Bs["raw"] / Bs["turns"]),
                 ("out/turn",      T["output"] / T["turns"],   Bs["output"] / Bs["turns"]),
                 ("tools/turn",    T["tools"] / T["turns"],    Bs["tools"] / Bs["turns"])]
        print(f"BASELINE  sessions={int(Bs['sessions'])} turns={int(Bs['turns'])}")
        print(f"TREATMENT sessions={int(T['sessions'])} turns={int(T['turns'])}\n")
        print(f"{'metric':<14}{'baseline':>12}{'treatment':>12}{'delta':>10}")
        for name, t, b in pairs:
            d = (t - b) / b * 100 if b else 0
            print(f"{name:<14}{fmt(b):>12}{fmt(t):>12}{d:>+9.1f}%")
        bp = Bs["weighted"] / Bs["turns"] / B * 100
        tp = T["weighted"] / T["turns"] / B * 100
        print(f"\n%5h-limit per turn: baseline {bp:.3f}%  ->  treatment {tp:.3f}%  "
              f"({(tp-bp)/bp*100:+.1f}%)")
        print(f"turns per 5h window: baseline {100/bp:.0f}  ->  treatment {100/tp:.0f}")
        return

    if a.last:
        ss = ss[:a.last]
    print(f"{'session':<10}{'turns':>6}{'tools':>6}{'cache_rd':>10}{'cache_wr':>10}"
          f"{'out':>8}{'raw':>9}{'wtd':>9}{'%5h':>8}{'%5h/turn':>10}")
    for s in ss:
        pct = s["weighted"] / B * 100
        print(f"{s['id'][:8]:<10}{s['turns']:>6}{s['tools']:>6}"
              f"{fmt(s['cache_read']):>10}{fmt(s['cache_write']):>10}{fmt(s['output']):>8}"
              f"{fmt(s['raw']):>9}{fmt(s['weighted']):>9}{pct:>7.1f}%{pct/s['turns']:>9.3f}%")
    A = agg(ss)
    print("-" * 96)
    print(f"TOTAL {int(A['sessions'])} sessions  {int(A['turns'])} turns  "
          f"raw {fmt(A['raw'])}  weighted {fmt(A['weighted'])}  "
          f"{A['weighted']/A['turns']/B*100:.3f}% of 5h limit per turn  "
          f"({100/(A['weighted']/A['turns']/B*100):.0f} turns per window)")
    print(f"budget basis: {basis} = {fmt(B)} weighted tokens / 5h")


if __name__ == "__main__":
    main()
