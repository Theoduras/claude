# Velvet

Flask 3 + PostgreSQL dating app, server-rendered Jinja. Deps: `flask`, `requests`, `psycopg`,
`gunicorn` — no ORM, no LLM SDK. Needs a reachable Postgres: `DATABASE_URL`, else the `DB_*`
parts (default `postgres:postgres@127.0.0.1:5432/velvet`). Run: `python app.py`. Seed demo
data: `python seed_demo.py`.

## Layout

- `app.py` — **1,852 lines**, single module: all routes, DB access, and helpers
- `templates/` — 16 Jinja templates, all extending `base.html`
- PostgreSQL — tables `users`, `profiles`, `matches`, `searches`, `messages`
- `docs/style-guide.html` — velvet-textured design system
- `vastai_client.py` — standalone Vast.ai GPU-rental CLI, **not imported by the app**

## Route map (`app.py`, line numbers approximate — they shift on edit)

| Area | Routes |
|---|---|
| auth | `/register` 454, `/login` 495, `/logout` 518 |
| profile | `/profile/edit` 883, `/profile/<id>` 957, `/admin/profiles/new` 980 |
| search | `/search` 1266, `/search/criteria` 1292, `/search/waiting` 1425, `/search/status` 1450, `/search/cancel` 1479 |
| find | `/find` 1492, `/find/results` 1518 |
| matches | `/matches` 1568, `/match/<other_id>` 1627 |
| chat | `/chats` 1659, `/chat/<match_id>` 1685, `…/messages` 1741, `…/send` 1767 |
| browse | `/browse` 1814 |

## Working rule

`app.py` is ~18k tokens. **Never read it whole** — grep for the symbol, then read with
`offset`/`limit` around the hit. Use the table above to jump straight to a feature.
