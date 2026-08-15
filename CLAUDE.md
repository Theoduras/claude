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
- `seed_demo.py` — 40 demo members, all live-searching and `is_bot=TRUE` so they reply in
  chat. Idempotent; `--reset` to rebuild
- `smoke.py`, `dev.ps1`, `docker-compose.yml` — local dev only, not deployed
- `vastai_client.py` — standalone Vast.ai GPU-rental CLI, **not imported by the app**
- `make_search_avatars.py` — regenerates the four placeholder-avatar PNGs inside
  `static/velvet-searching.lottie` (the `/search/waiting` animation) in the app's
  palette; standalone, **not imported by the app**

## Database

PostgreSQL via `psycopg` + a `ConnectionPool` (`app.py:28-88`). `database_url()` prefers
`DATABASE_URL`; otherwise it assembles one from `DB_USER`/`DB_PASS`/`DB_NAME`/`DB_HOST`,
and switches to a Cloud SQL unix socket when `INSTANCE_CONNECTION_NAME` is set.

`init_db()` (`app.py:348`) creates the schema under an advisory lock and ensures the
admin account. It runs at import time, so importing `app` bootstraps a fresh database.

A shim gives psycopg connections the old sqlite3 shape (`app.py:195`) — `?` placeholders
in query strings are rewritten, so **write `?`, not `%s`**, in `db.execute(...)` calls.

Tables: `users` (+`is_bot`), `profiles`, `matches` (+`status`/`paired_at`/`decision_a`/
`decision_b`/`ended_at`), `searches` (+`lat`/`lng`/`use_*`), `messages`, `photos`.

Starting a search is **two screens**: `/search` picks the connection type and the location
+ radius (carried to screen 2 in `session["search_draft"]`), `/search/criteria` asks which
filters matter as a list of switches. Each switch writes a `searches.use_*` column —
`use_gender`/`use_age`/`use_distance`/`use_physical`/`use_relationship` — read by
`searches_compatible()` via `.get(key, True)`; a switch that is off leaves its panel's inputs
`disabled`, so those fields never reach the server at all. Interests has no `use_*` column of
its own — the stored text *is* the switch: "off" stores `''`, which `searches_compatible()`
reads as "no preference". When it's non-empty it's a real filter (requires the other side to
share at least one stemmed keyword), and it still breaks ties in `try_pair()`'s ranking among
whoever's left.

`relationship_type` (step 1, "What are you looking for?") is a checkbox group, not a radio —
a searcher can want more than one kind of connection — so `searches.relationship_type` is a
CSV like `interests` and `pref_body_types`, and `searches_compatible()` passes it as soon as
the two sides share one type rather than requiring an exact match. `use_relationship` still
exists but is no longer forced TRUE: `save_search()` sets it TRUE at wizard creation because
the step requires at least one type, but from then on it just tracks whether that CSV is
empty (`bool(types)`), the same relationship `use_physical` has with `pref_body_types`.
`/search/waiting`'s recap gives connection type one pill per selected value (`relationship:
<type>` chips), not the single always-present chip gender and age get, and removing every one
of them switches `use_relationship` off — same as clearing the last body-type chip.

`/search/waiting` restates those filters as chips you can edit in place — tap one for a
sheet of alternatives, each priced with a real `searches_compatible()` count
(`search_chips()`/`chip_options()`, `app.py:~2538`). Applying one is a targeted `UPDATE`
(`/search/chips` POST), never `save_search()` — that resets `created_at`, which would
restart both `MIN_SEARCH_SECONDS` (pairing eligibility) and `SEARCH_WIDER_SECONDS` (below)
on every tap. A zero-fit search that's been running `SEARCH_WIDER_SECONDS` (45s) is also
offered a one-tap "Search wider", which drops every optional filter but keeps the
connection type.

`matches.status` is `'active'` by default — pairing now only happens through live search
(`try_pair()`), but the default keeps pre-existing rows a permanent chat, unchanged.
`try_pair()` writes `status='timed'` with `paired_at`,
which kicks off a computed lifecycle (`match_phase()`, `app.py:~2470`): 20s reveal → 5min
timed chat → decision → `active` (both Continue) or `ended` (either Unmatch, or the grace
window lapses). No background job — phases are derived from `paired_at` on each poll.
`send_message()` gates on phase server-side; the browser countdown is cosmetic only.

`photos` (bytea) is visible only to the owner, admins, or a matched user once that match is
`active` — see `can_view_photos()` and `/photo/<id>` (`app.py:~2935`). Demo members
(`is_bot=TRUE`) auto-reply in chat via a canned engine (no LLM) and auto-continue past the
decision phase — see `maybe_bot_reply()`.

`/profile/<id>` is a pinned name over a scrolling stack: a tap/swipe photo carousel with a
segment bar per photo, then one `.pro-card` per section (Looking for, About me, In short,
Interests, Hobbies, and the `wants`/`needs` prompts), plus an owner-only card for the
`pref_*` columns. All of it is Jinja over columns `profiles` already has —
`view_profile()` is untouched — so a new field shows up by adding a card, not a route.

`/profile/edit` stages photo changes and applies them all on Save: the tile strip previews
picked files with `URL.createObjectURL`, an × marks a photo for removal (Undo takes it
back), tapping a tile makes it the main one, and dragging reorders. The browser transcribes
the strip into three hidden fields — `remove_photo_ids`, `photo_order`, `primary_photo_id`
— and rewrites the file input through a `DataTransfer`, since a `FileList` is read-only;
`apply_photo_edits()` (`app.py:~1228`) re-checks every id against ownership and writes
`photos.sort_order`. Reads are `ORDER BY is_primary DESC, sort_order, id` everywhere.

## Route map (`app.py`)

Regenerate with `grep -n "^@app.route" app.py` — line numbers below drift on every edit.

| Area | Routes |
|---|---|
| misc | `/lab`, `/` |
| auth | `/register`, `/login`, `/logout` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/chips` (GET+POST), `/search/status`, `/search/cancel` |
| match lifecycle | `/match/<id>/state`, `/match/<id>/decide`, `/match/<id>/skip-reveal` |
| chat | `/chats`, `/chat/<id>`, `…/messages`, `…/send` |

`/find`, `/find/results`, `/matches` and `/browse` were removed — pairing happens only
through live search now. `create_match()`, `match_score()` and `genders_compatible()`
(the instant-pair and ranking helpers those routes used) went with them.

## Working rule

`app.py` is large. **Never read it whole** — grep for the symbol, then read with
`offset`/`limit` around the hit. Use the table above to jump straight to a feature.

Line numbers drift on every edit. Regenerate the map with:

```bash
grep -n "^@app.route" app.py
```
