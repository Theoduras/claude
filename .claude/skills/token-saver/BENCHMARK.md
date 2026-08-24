# Token Saver — Benchmark

Everything here is measured from your own transcripts in `~/.claude/projects/**/*.jsonl`,
not estimated. Units are **tokens** and **% of the 5-hour rolling limit**.

Reproduce with:

```bash
python ~/.claude/skills/token-saver/measure.py --last 10
```

---

## How the 5h limit is defined

The real 5h limit is not published, so it is **calibrated from your history**: the busiest
5-hour rolling window you have ever run is treated as 100%. Override anytime:

```bash
set TOKEN_SAVER_5H_BUDGET=20000000
```

Tokens are weighted before comparison, because a cache read is not the same as an output
token:

| Token type | Weight | Why |
|---|---|---|
| cache_read | 0.1 | cheapest; re-sent context |
| input | 1.0 | fresh input |
| cache_write | 1.25 | fresh input + cache premium |
| output | 5.0 | most expensive, and re-enters context next turn |

**Calibrated budget on this machine: 13.5M weighted tokens per 5h window**
(peak observed 2026-06-09 19:52). Second and third busiest windows landed at 85.6% and
82.7% of that, which is what you'd expect if the peak really was a limit ceiling.

---

## Baseline (before the skill)

22 sessions, 6,176 turns, 821.6M raw tokens.

| Metric | Baseline |
|---|---|
| Raw tokens / turn | 132,966 |
| Output tokens / turn | 945 |
| Tool calls / turn | 0.45 |
| **% of 5h limit / turn** | **0.185%** |
| **Turns available per 5h window** | **~541** |

### Where the tokens actually go

| Line item | Share of weighted spend |
|---|---|
| Cache reads (context re-sent every turn) | 48.1% |
| Cache writes (new context added) | 33.8% |
| Output tokens | 17.8% |
| Fresh input | 0.3% |

**82% of your spend is context, 18% is what I write.** This is why the skill targets file
reads, tool-call batching, and command output — not reply brevity. Halving my prose would
move ~9% of total spend at absolute best; avoiding one unnecessary 20k-token file read
saves that much on its own and keeps saving it every subsequent turn.

### Worst observed sessions (the ones the skill targets)

| Session | Turns | Cache read | %5h/turn | Note |
|---|---|---|---|---|
| `645b343f` | 569 | 106.7M | 0.229% | 130% of a full 5h window in one session |
| `d249728d` | 338 | 34.3M | 0.146% | 49% of a window |
| `b92e60e5` | 449 | 78.3M | — | long-horizon, no `/clear` |

Common factor: long sessions with no context reset. Cache-read cost grows with every turn
because the entire history is re-sent, so a 500-turn session pays for early turns 500 times.
That is rule R8's entire justification.

---

## Measuring the improvement

After running some sessions with the skill active:

```bash
python ~/.claude/skills/token-saver/measure.py --compare 3
```

Newest 3 sessions = treatment, everything older = baseline. Output:

```
metric            baseline   treatment     delta
weighted/turn        ...         ...      -XX.X%
raw/turn             ...         ...      -XX.X%
out/turn             ...         ...      -XX.X%
tools/turn           ...         ...      -XX.X%

%5h-limit per turn: baseline 0.185%  ->  treatment X.XXX%  (-XX.X%)
turns per 5h window: baseline 541  ->  treatment XXX
```

---

## Expected gains per rule

Ranked by leverage against the 82/18 split above. These are targets to verify with
`--compare`, not measured results yet.

| Rule | Mechanism | Expected effect on %5h/turn |
|---|---|---|
| R2 batch tool calls | removes a full context re-send per avoided round-trip | −15 to −30% |
| R1 grep before read | avoids permanent 5–20k context additions | −10 to −25% |
| R8 clear stale context | resets the quadratic cache-read growth | −20 to −40% on long sessions |
| R3 bound command output | keeps junk out of context permanently | −5 to −15% |
| R6 subagent isolation | reads never enter parent context | −10 to −20% on wide searches |
| R5 model right-sizing | Haiku for mechanical work | limit-share, not token count |
| R4 effort calibration | fewer thinking tokens (18% bucket) | −3 to −8% |
| R7 no re-verification | drops redundant round-trips | −2 to −5% |

Realistic stacked target: **35–50% fewer weighted tokens per turn**, i.e. roughly
**541 → 850–1000 turns per 5h window**. Long unmanaged sessions are where most of it comes
from.

---

---

## Context-size distribution (the actual lever)

Measured across 6,199 turns, **817.1M context tokens re-sent**:

| Percentile | Context size |
|---|---|
| p50 | 117k |
| p75 | 175k |
| p90 | **251k** |
| p99 | 372k |
| max | 394k |

| Context bucket | Turns |
|---|---|
| 0–50k | 965 |
| 50–100k | 1,643 |
| 100–150k | 1,467 |
| 150–200k | 841 |
| 200–250k | 642 |
| 250–300k | 381 |
| 300–350k | 150 |
| 350k+ | 108 |

### Savings by autocompact threshold

Excess = context tokens above the cap, summed over every turn.

| Cap | Excess removed | % of all context | Turns affected |
|---|---|---|---|
| 300k | 10.9M | 1.3% | 4.2% |
| 250k | 32.0M | 3.9% | 10.3% |
| **200k (chosen)** | **81.6M** | **10.0%** | **20.7%** |
| 150k | 162.2M | 19.9% | 34.2% |
| 100k | 304.7M | 37.3% | 57.9% |

200k was chosen over 150k because compaction is itself a full-context read; firing on 34% of
turns instead of 21% spends much of the extra 10% on the compactions themselves.

---

## Rejected: cache-miss optimization

**Do not re-investigate this.** Hypothesis was that cache expiry (>1h idle → full context
reprocessed at write rates) was a major cost.

Measured: **24 events across all 22 sessions, 3.7M tokens rewritten = 0.45% of total spend.**

Not worth a setting, a hook, or a habit change. `ENABLE_PROMPT_CACHING_1H=1` was still set as
zero-cost insurance for the usage-credit case, where TTL would otherwise drop to 5 minutes.

---

## Post-change comparison slot

Baseline frozen at the numbers above (22 sessions, pre-2026-08-10). After ~5 sessions with the
automated controls active:

```bash
python ~/.claude/skills/token-saver/measure.py --compare 5
```

| Metric | Baseline | After | Delta |
|---|---|---|---|
| %5h limit / turn | 0.185% | _tbd_ | _tbd_ |
| Turns per 5h window | 541 | _tbd_ | _tbd_ |
| Context tokens / turn | 132,966 | _tbd_ | _tbd_ |

Expected from the autocompact change alone: ~10%. Expected with JSON compaction + recall
replacing re-derivation: ~20–25%.

---

## Honest caveats

- Sessions are not a controlled experiment. A hard debugging session costs more than a
  rename regardless of technique, so `--compare` across few sessions is noisy. Use ≥5
  sessions per group before believing a number.
- The `%5h` figure is only as good as the calibration. If you have never actually hit the
  limit, the calibrated budget understates the real ceiling and all percentages read high.
- Token weights approximate relative cost; they are not Anthropic's limit accounting.
- Per-turn cost naturally rises within a session even with perfect technique — the context
  is genuinely larger. Compare like-for-like session lengths where you can.
