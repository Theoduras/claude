# Compact instructions

When compacting, do NOT write prose. Emit a single minified JSON object, then stop:

```json
{"goal":"","state":"","decisions":[],"files":[{"p":"","why":""}],
 "commands":[],"errors":[],"open":[],"constraints":[],"archive":"~/.claude/context-archive/<session>/"}
```

Rules:
- `decisions` — choices already made and their reason. These must survive verbatim; re-deciding
  them later is the expensive failure mode.
- `files` — path plus one clause on why it mattered. Paths only, never file contents.
- `open` — what is still unfinished, phrased as an actionable next step.
- `constraints` — user preferences and hard requirements stated earlier in the session.
- Omit anything reconstructible from disk (file contents, command output, tool results).
  The PreCompact hook has already indexed those.

Nothing is lost by compacting: `~/.claude/hooks/archive_context.py` writes a full index before
each compaction. To retrieve any earlier detail rather than re-deriving it:

```
python ~/.claude/skills/token-saver/recall.py "<query>"
```

# Context discipline

Context is ~82% of token spend on this machine; output is ~18%. Optimize what accumulates,
not how much I write. Full rules: `~/.claude/skills/token-saver/SKILL.md`.

- Grep before Read; read with `offset`/`limit`, never whole large files.
- Batch independent tool calls into one block — each extra block re-sends the whole conversation.
- Bound command output (`head`, `-q`, `--quiet`, `Select-Object -First`).
- `/clear` costs nothing; `/compact` is itself a full-context read. Prefer `/clear` + `recall.py`
  when switching to unrelated work.
- Never skip a required verification, guess file contents, or truncate a requested deliverable
  in the name of saving tokens.
