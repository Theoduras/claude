# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What's here

Two unrelated projects share this repo:

- **Velvet** (`app.py`, `templates/`, `seed_demo.py`) — a Flask dating-site
  demo. This is the active project; nearly all work happens here.
- **Vast.ai client** (`vastai_client.py`) — a standalone CLI/library for the
  Vast.ai REST API. Unrelated to Velvet; don't couple them.

## Commands

```bash
pip install -r requirements.txt
python app.py                  # dev server on :5000, debug + reloader on
python seed_demo.py            # 20 demo members, all live-searching (re-runnable)
python seed_demo.py --reset    # wipe demo members and their chats, re-add
gunicorn app:app               # production path; skips the __main__ block
```

There is no test suite, linter config, or CI in this repo. Don't claim tests
pass — verify changes by running the app.

## Environment variables

| Var | Default | Effect |
| --- | --- | --- |
| `APP_SECRET_KEY` | random per boot | Sessions survive restarts only if set |
| `APP_ADMIN_PASSWORD` | `admin12345` | Password for the auto-created `admin` user |
| `AUTO_LOGIN` | `0` | `1` bypasses login and browses as admin (dev only) |
| `DATABASE_PATH` | `dating.db` next to `app.py` | SQLite file location |
| `PORT` | `5000` | Bind port |
| `FLASK_DEBUG` | `1` | `0` disables reloader/debugger |

Vast.ai client reads `VAST_API_KEY`. Never hardcode or log it.

## Architecture notes

- **Single-file app.** `app.py` holds config constants, schema, matching
  logic, and all routes. Keep new work in the section it belongs to rather
  than adding modules unless it's genuinely separable.
- **Schema lives in `init_db()`**, run at import time. It's `CREATE TABLE IF
  NOT EXISTS` plus a list of best-effort `ALTER TABLE` migrations wrapped in
  `try/except sqlite3.OperationalError`. Adding a column means appending to
  both the `CREATE` block and that migration list — existing `dating.db`
  files are never rebuilt.
- **Tables:** `users`, `profiles` (1:1 with users), `matches` (enforces
  `user_a < user_b`), `searches` (one row per member currently live-searching),
  `messages`.
- **Matching** is mutual and symmetric — `searches_compatible()` must hold in
  *both* directions (gender preference, age range, radius, relationship goal).
  `try_pair()` is guarded by `SEARCH_LOCK`.
- **Long polling** drives live chat and live search. Both loops re-query on a
  ≤1s tick and use `threading.Condition` (`NEW_MESSAGE`, `SEARCH_EVENT`) only
  as an optimization to wake early.
- **Distances** come from the hardcoded `CITY_COORDS` table (great-circle
  maths, no geocoding service). Unrecognised cities skip distance filtering.
  A new city needs an entry in both `CITY_COORDS` and `CITY_CHOICES`.

## Gotchas

- **`gunicorn -w 2` splits the Condition objects across processes.** A message
  stored in one worker won't wake a long-poll held in another; it degrades to
  the ~1s poll tick rather than breaking. Any new cross-request signalling
  needs the same fallback, or a shared broker.
- **Render's free tier has no persistent disk.** `dating.db` resets on every
  redeploy and after ~15 min idle. Don't design around durable state there.
- **Velvet is a local demo** — default admin password and `AUTO_LOGIN` make it
  unsafe to expose publicly as-is.
- **`create` / `destroy` in the Vast.ai client spend real money and terminate
  real machines.** Test with the read-only `offers` / `instances` commands.

## Design system

All tokens live at the top of `templates/base.html`; `docs/style-guide.html`
is the full reference. The rule that governs new UI: **violet acts, teal
responds** — a violet control changes something about you, a teal one belongs
to the other person or to live state. Headings are serif, controls and labels
are sans, numbers are tabular. The velvet texture is pure CSS (gradients plus
an inline SVG `feTurbulence` grain) — no image files; keep it that way.
