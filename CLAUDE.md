# Velvet

Flask 3 + **PostgreSQL** dating app, server-rendered Jinja. Deps: `flask`, `requests`,
`gunicorn`, `psycopg[binary]`, `psycopg-pool` — no ORM, no LLM SDK.

## Local development

```powershell
docker compose up -d      # Postgres, once per boot
.\dev.ps1                 # venv + seed + Flask with the reloader
# edit -> save -> refresh the browser. No restart, no git.
python smoke.py           # hit every GET route, report 5xxs
```

**Local iteration does not commit.** Work on disk until the feature is actually
done, then `git add -p` and commit once. Do not push work-in-progress.

`.env` (from `.env.example`) carries `DATABASE_URL`, `APP_SECRET_KEY`, `FLASK_DEBUG`,
`AUTO_LOGIN`, and pool sizing. Pinning `APP_SECRET_KEY` matters: `app.py:46` falls back
to a random key, which logs you out on every reloader restart.

`setup.ps1` is first-time bootstrap only (clone + install). Use `dev.ps1` day to day.

## Model and effort

Everyday work: **Opus 5 at `medium`**. `low` for CSS/copy tweaks, `high` for planning
or multi-route refactors, `xhigh` for the search/matching logic. Haiku 4.5 for bulk
mechanical edits. `/fast` doubles cost — only when actively waiting on the browser.

Keep replies concise; prefer the smallest diff that does the job.

## Layout

- `app.py` — **~3,000 lines**, single module: all routes, DB access, and helpers
- `templates/` — 16 Jinja templates, all extending `base.html`
- `docs/style-guide.html` — velvet-textured design system; `docs/deploy-gcp.md` — Cloud Run
- `seed_demo.py` — 20 demo members, all live-searching and `is_bot=TRUE` so they reply in
  chat. Idempotent; `--reset` to rebuild
- `smoke.py`, `dev.ps1`, `docker-compose.yml` — local dev only, not deployed
- `vastai_client.py` — standalone Vast.ai GPU-rental CLI, **not imported by the app**

## Database

PostgreSQL via `psycopg` + a `ConnectionPool` (`app.py:28-88`). `database_url()` prefers
`DATABASE_URL`; otherwise it assembles one from `DB_USER`/`DB_PASS`/`DB_NAME`/`DB_HOST`,
and switches to a Cloud SQL unix socket when `INSTANCE_CONNECTION_NAME` is set.

`init_db()` (`app.py:348`) creates the schema under an advisory lock and ensures the
admin account. It runs at import time, so importing `app` bootstraps a fresh database.

A shim gives psycopg connections the old sqlite3 shape (`app.py:195`) — `?` placeholders
in query strings are rewritten, so **write `?`, not `%s`**, in `db.execute(...)` calls.

Tables: `users` (+`is_bot`), `profiles`, `matches` (+`status`/`paired_at`/`decision_a`/
`decision_b`/`ended_at`), `searches` (+`lat`/`lng`), `messages`, `photos`.

`matches.status` is `'active'` by default — every `/find` match and pre-existing row is a
permanent chat, unchanged. Only `try_pair()` writes `status='timed'` with `paired_at`,
which kicks off a computed lifecycle (`match_phase()`, `app.py:~2470`): 20s reveal → 5min
timed chat → decision → `active` (both Continue) or `ended` (either Unmatch, or the grace
window lapses). No background job — phases are derived from `paired_at` on each poll.
`send_message()` gates on phase server-side; the browser countdown is cosmetic only.

`photos` (bytea) is visible only to the owner, admins, or a matched user once that match is
`active` — see `can_view_photos()` and `/photo/<id>` (`app.py:~2935`). Demo members
(`is_bot=TRUE`) auto-reply in chat via a canned engine (no LLM) and auto-continue past the
decision phase — see `maybe_bot_reply()`.

## Route map (`app.py`)

Regenerate with `grep -n "^@app.route" app.py` — line numbers below drift on every edit.

| Area | Routes |
|---|---|
| misc | `/lab`, `/` |
| auth | `/register`, `/login`, `/logout` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/status`, `/search/cancel`, `/search/filters/toggle`, `/search/filters/apply` |
| find | `/find`, `/find/results` |
| matches | `/matches`, `/match/<other_id>`, `/match/<id>/state`, `/match/<id>/decide` |
| chat | `/chats`, `/chat/<id>`, `…/messages`, `…/send` |
| browse | `/browse` |

## Working rule

`app.py` is large. **Never read it whole** — grep for the symbol, then read with
`offset`/`limit` around the hit. Use the table above to jump straight to a feature.

Line numbers drift on every edit. Regenerate the map with:

```bash
grep -n "^@app.route" app.py
```
