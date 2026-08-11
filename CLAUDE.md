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

- `app.py` — **1,852 lines**, single module: all routes, DB access, and helpers
- `templates/` — 16 Jinja templates, all extending `base.html`
- `docs/style-guide.html` — velvet-textured design system; `docs/deploy-gcp.md` — Cloud Run
- `seed_demo.py` — 20 demo members, all live-searching. Idempotent; `--reset` to rebuild
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

Tables: `users`, `profiles`, `matches`, `searches`, `messages`.

## Route map (`app.py`)

| Area | Routes |
|---|---|
| misc | `/lab` 440, `/` 447 |
| auth | `/register` 454, `/login` 495, `/logout` 518 |
| profile | `/profile/edit` 883, `/profile/<id>` 957, `/admin/profiles/new` 980 |
| search | `/search` 1266, `/search/criteria` 1292, `/search/waiting` 1425, `/search/status` 1450, `/search/cancel` 1479 |
| find | `/find` 1492, `/find/results` 1518 |
| matches | `/matches` 1568, `/match/<other_id>` 1627 |
| chat | `/chats` 1659, `/chat/<id>` 1685, `…/messages` 1741, `…/send` 1767 |
| browse | `/browse` 1814 |

## Working rule

`app.py` is ~18k tokens. **Never read it whole** — grep for the symbol, then read with
`offset`/`limit` around the hit. Use the table above to jump straight to a feature.

Line numbers drift on every edit. Regenerate the map with:

```bash
grep -n "^@app.route" app.py
```
