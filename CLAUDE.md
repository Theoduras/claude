# Velvet

Flask 3 + SQLite dating app, server-rendered Jinja. Deps: `flask`, `requests` only — no ORM,
no LLM SDK. Run: `python app.py`. Seed demo data: `python seed_demo.py`.

## Layout

- `app.py` — **1,342 lines**, single module: all routes, DB access, and helpers
- `templates/` — 16 Jinja templates, all extending `base.html`
- `dating.db` — SQLite; tables `users`, `profiles`, `matches`, `searches`, `messages`
- `docs/style-guide.html` — velvet-textured design system
- `vastai_client.py` — standalone Vast.ai GPU-rental CLI, **not imported by the app**

## Route map (`app.py`, line numbers approximate — they shift on edit)

| Area | Routes |
|---|---|
| auth | `/register` 293, `/login` 335, `/logout` 358 |
| profile | `/profile/edit` 388, `/profile/<id>` 436, `/admin/profiles/new` 459 |
| search | `/search` 736, `/search/criteria` 762, `/search/waiting` 895, `/search/status` 920, `/search/cancel` 958 |
| find | `/find` 971, `/find/results` 997 |
| matches | `/matches` 1047, `/match/<other_id>` 1106 |
| chat | `/chats` 1138, `/chat/<match_id>` 1164, `…/messages` 1227, `…/send` 1263 |
| browse | `/browse` 1314 |

## Working rule

`app.py` is ~18k tokens. **Never read it whole** — grep for the symbol, then read with
`offset`/`limit` around the hit. Use the table above to jump straight to a feature.
