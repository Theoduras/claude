---
name: token-saver
description: >
  Cuts the tokens THIS agent session burns — context reads, tool calls, thinking depth,
  and reply length. Use whenever the user complains about cost or token usage, asks to
  "be efficient", "save tokens", "go faster", or starts a task with large files, wide
  searches, or many tool calls. Distinct from `token-optimizer`, which governs Claude API
  code you write for others; this one governs your own behavior in the terminal.
  Commands: "/token-saver report" (measure this session), "/token-saver plan" (cost/effort
  options before a task).
---

# Token Saver

Every turn re-sends the whole conversation. Cost is therefore quadratic in what you drag
along, not linear in what you type. Optimize the *context you accumulate*, not the prose.

## The cost model (measured on this machine)

| Line item | Share of weighted spend |
|---|---|
| Cache reads (context re-sent every turn) | 48% |
| Cache writes (new context added) | 34% |
| Output tokens | 18% |

**Implication: one avoided 2k-token file read beats 20 shortened replies.** Trimming prose
is the smallest lever available. Never trade a correct answer for a shorter one.

---

## The 8 rules

### R1 — Never read what you can locate
`Grep` with `output_mode: "files_with_matches"` or `-n` + `-C 2` before `Read`. A full
`Read` of a 1500-line file costs ~20k tokens and is re-sent every turn after. Read with
`offset`/`limit` once you know the line.

❌ `Read(bigfile.py)` then scroll → ✅ `Grep(pattern, -n, -C 3)` → `Read(file, offset=N, limit=60)`

### R2 — Batch independent calls in one block
Independent tool calls in a single assistant block cost one context re-send. Serialized
across N blocks costs N re-sends of the entire conversation. This is the single largest
controllable multiplier.

### R3 — Bound every command's output
Pipe to `head`/`tail`/`Select-Object -First`, add `--quiet`, `-q`, `--no-progress`,
`| Out-Null`. Never `cat` a file to inspect it, never run a test suite in full verbosity
when `--tb=line -q` answers the same question. Uncapped output lands in context permanently.

### R4 — Calibrate effort to the task
`low` for lookups, file edits with a known target, status checks. `medium` for most
implementation. `high`/`xhigh` only for genuine architecture, debugging with unknown cause,
or multi-file refactors. Thinking tokens bill as output and re-enter context.

### R5 — Right-size the model
Haiku 4.5 for greps, renames, file moves, log scans, formatting. Sonnet 5 for standard
implementation. Opus 5 for design, hard debugging, long-horizon agentic work. A Haiku
subagent doing the search and returning 40 lines is ~25× cheaper than Opus reading 12 files.

### R6 — Subagent to isolate, not to parallelize
A subagent's file reads never enter the parent's context — only its final report does.
Delegate wide searches ("find every place X is configured") when you need the conclusion.
Do NOT spawn one for a task you already have context for: each spawn re-derives from a
cold start and usually costs more than doing it inline.

### R7 — Don't re-verify what the tools already confirmed
`Edit`/`Write` error if they fail. Re-reading an edited file to "check" it is pure waste.
Same for restating a plan already agreed, re-listing a directory, or re-grepping to confirm
a match you just saw.

### R8 — Cut the conversation, not the sentence
When context grows past ~60% and the current task is unrelated to earlier work, say so and
suggest `/clear` or a fresh session. One clear beats hundreds of terse replies. Keep
CLAUDE.md and memory files small and stable — they sit in the cached prefix of every turn.

### R9 — Prefer `/clear` + recall over `/compact`
`/clear` costs **zero**. `/compact` reads the entire conversation to summarize it, so it is
itself one of the largest requests in a session. Compact only when continuity genuinely
matters; otherwise clear and pull back what you need:

```bash
python ~/.claude/skills/token-saver/recall.py "<query>"
```

Nothing is lost either way — see Automated controls below.

---

## Automated controls (already installed)

These enforce the rules mechanically rather than relying on the agent remembering them.

| Control | Location | Effect |
|---|---|---|
| `autoCompactWindow: 200000` | `~/.claude/settings.json` | Caps context at 200k. Removes 10.0% of all context tokens re-sent; fires on the worst 20.7% of turns. |
| `crossSessionInbound: "hold"` | `~/.claude/settings.json` | Idle sessions no longer re-send full context per inbound cross-session message. |
| `ENABLE_PROMPT_CACHING_1H=1` | `~/.claude/settings.json` `env` | Keeps the 1h cache TTL when drawing on usage credits (otherwise drops to 5 min). |
| Compact instructions | `~/.claude/CLAUDE.md` | Compaction emits minified JSON (`goal/decisions/files/open/constraints`) instead of prose — same facts, ~40–60% fewer tokens, greppable. |
| `PreCompact` hook | `~/.claude/hooks/archive_context.py` | Before every compaction, writes a structured index (files, commands, errors, decisions, prompts + JSONL line span) to `~/.claude/context-archive/<session>/NNNN.json`. Always exits 0 so it can never block compaction. |
| `SessionStart(compact)` hook | `~/.claude/hooks/inject_archive_pointer.py` | Injects a ~200-token pointer to the archive, not its contents. |
| `recall.py` | this folder | Searches archives, then falls back to scanning raw transcripts. Makes compaction non-lossy in practice. |
| `PreToolUse(Bash)` hook | `~/.claude/hooks/cap_output.py` | Appends `\| head -200` to a narrow allowlist of noisy read-only commands (`cat`, `git log`, `pytest`, `docker logs`, …). Skips anything with a pipe, redirect, chain, or existing bound. Enforces R3 automatically. |

**The invariant: compaction removes detail from context, never from disk.** Full transcripts
live in `~/.claude/projects/**/*.jsonl` permanently. Before claiming you lack earlier context,
run `recall.py` — re-deriving what is already archived is the expensive failure mode.

```bash
python ~/.claude/skills/token-saver/recall.py --list
```

```bash
python ~/.claude/skills/token-saver/recall.py --show <session> <line>
```

All eight controls are installed and tested. `cap_output.py` required
`Write(C:\Users\jeffr\.claude\hooks\**)` in `permissions.allow`, since a hook that rewrites
shell commands otherwise reads as injection to the permission classifier.

### Installing on another machine

`SKILL.md` alone is only advice — the measured savings come from the hooks and settings above.
`install.py` deploys all of it. It is stdlib-only, idempotent, and **merges** into
`settings.json` rather than overwriting: existing hooks, permissions, and marketplaces survive,
every write is backed up first, and an existing `autoCompactWindow` you set deliberately is kept
(with a warning) rather than clobbered.

```bash
python ~/.claude/skills/token-saver/install.py --dry-run
```

```bash
python ~/.claude/skills/token-saver/install.py
```

Copy the whole `token-saver/` folder to the new machine's `~/.claude/skills/` and run it — the
hooks ship in `payload/hooks/` and are copied out to `~/.claude/hooks/` with the absolute path of
whichever Python runs the installer. Restart Claude Code afterwards so the hooks load. Flags:
`--home PATH` to target a non-default Claude home, `--uninstall` to remove only what it added
(archives and transcripts are left on disk).

The `payload/` folder is the source of truth for the deployed copies. Edit a hook there, not in
`~/.claude/hooks/`, or the next install will overwrite your change.

---

## Anti-rules — never do these to save tokens

- Skip a verification step that was actually required, then report success.
- Guess at file contents instead of reading them.
- Truncate a deliverable the user asked for in full.
- Drop the safety confirmation on an irreversible or outward-facing action.

Efficiency is about avoiding *waste*, never about doing less of the job.

---

## `/token-saver plan`

Before a non-trivial task, emit a 2–3 row table and pick one:

| # | Model / effort | Approach | Est. %5h limit | Est. duration |
|---|---|---|---|---|
| 1 | Haiku / low | mechanical, known target | <0.5% | <1 min |
| 2 | Sonnet / medium | standard implementation | 0.5–3% | 1–3 min |
| 3 | Opus / high | design or unknown-cause debugging | 3–15% | 3–10 min |

Estimate as `turns × 0.185%` of the 5h limit (this machine measured mean), adjusted for model family.
Recommend the cheapest row that can actually finish the job, and say why.

## `/token-saver report`

Run the measurement script and report real numbers:

```bash
python ~/.claude/skills/token-saver/measure.py --last 10
```

```bash
python ~/.claude/skills/token-saver/measure.py --compare 3
```

`--compare N` treats the newest N sessions as the treatment group and everything older as
the baseline, printing the % delta in cost/turn, output/turn, and tools/turn. See
[BENCHMARK.md](BENCHMARK.md) for the methodology and the recorded baseline.
