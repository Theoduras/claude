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
- `translations.py` — all user-facing copy, `en` + `nl` (see **Copy and languages**)
- `tools/check_translations.py` — reports missing/unused keys; exits non-zero on a gap
- `docs/style-guide.html` — velvet-textured design system; `docs/deploy-gcp.md` — Cloud Run
- `seed_demo.py` — 40 demo members, `is_bot=TRUE` so they reply in chat. Their `searches`
  rows are `waiting` but they have no browser, so they are **not pairable** unless
  `DEMO_BOTS_ALWAYS_ONLINE=1` (local only — see below). Idempotent; `--reset` to rebuild
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

**One city for now.** `SINGLE_CITY = "Maastricht"` (`app.py`) pins every profile and every
search: `pinned_place()` overrides whatever a form posts, so the location control is not
rendered anywhere — not in `_profile_fields.html`, not as the wizard's location step (the
wizard is 5 steps, not 6), and the criteria screen's Distance switch is hidden too, since
one shared set of coordinates means it can never change who fits. `_location_field.html`
and `/api/places` are intact but unreached; set `SINGLE_CITY = None` to bring all of it
back. Whatever it names must exist in `CITY_COORDS` (asserted at import).

Starting a search is **two screens**: `/search` picks the connection type (and the location
+ radius when multi-city, carried to screen 2 in `session["search_draft"]`),
`/search/criteria` asks which filters matter as a list of switches. Each switch writes a
`searches.use_*` column —
`use_gender`/`use_age`/`use_distance`/`use_physical` — read by `searches_compatible()` via
`.get(key, True)`; a switch that is off leaves its panel's inputs `disabled`, so those
fields never reach the server at all. `use_relationship` is always TRUE: it *is* the tile
choice. Interests has no `use_*` column of its own — the stored text *is* the switch: "off"
stores `''`, which `searches_compatible()` reads as "no preference". When it's non-empty it's
a real filter (requires the other side to share at least one stemmed keyword), and it still
breaks ties in `try_pair()`'s ranking among whoever's left.

**You can only be paired with someone who is online and searching at the same moment.**
`searches.last_seen` is a heartbeat bumped by `/search/status` (the waiting page polls it
every 1.5s) and by loading `/search/waiting`. Every pool query — `try_pair()`,
`_search_pool()`, `search_preview()` and the landing page's "N searching right now" —
filters on `LIVE_SEARCH_CLAUSE`, so a row that hasn't beaten within
`SEARCH_ALIVE_SECONDS` (60s) is treated as gone: not pairable, not counted. Nothing reaps
those rows; they simply stop qualifying, and a returning user is revived by their own next
poll. Seeded demo members have no browser and so are never online — set
`DEMO_BOTS_ALWAYS_ONLINE=1` **locally** to exempt them and test the match lifecycle solo.
With it on, `try_pair()` ranks humans ahead of bots and withholds bots entirely until the
searcher has waited `BOT_FALLBACK_SECONDS`.

Sign-in and sign-up are rate limited via `auth_attempts` (`auth_throttled()`), checked
*before* `check_password_hash` — scrypt costs ~110ms and ~32MB per call, so a refused
attempt has to be cheap or the throttle is itself a DoS.

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

## Copy and languages

**No hardcoded user-facing strings.** Every one lives in `translations.py` and is reached
through `t('some.key')` — the Jinja helper comes from the context processor, the Python
twin sits next to it in `app.py` for flash messages and generated copy. 315 keys, `en` +
`nl` at full parity. `python tools/check_translations.py` lists gaps and dead keys.

`translate()` falls back **requested language → English → the key itself**, so a partial
language ships safely: missing strings read English, a missing key reads as the key.
Adding a language is: append to `LANGUAGES`, copy the `en` block, translate the values.

Headlines are one key containing `\n`; the template splits on it, so each language picks
its own line breaks (English landing is 3 lines, Dutch is 2).

**The option lists are canonical English and must stay that way.** `GENDERS`,
`SEEKING_OPTIONS`, `RELATIONSHIP_TYPES`, `BODY_TYPES`, `FITNESS_LEVELS`, `HAIR_COLORS`,
`EYE_COLORS`, `TATTOO_LEVELS` and the interest keywords are stored in the database and
compared as strings by `searches_compatible()` / `SEEKING_MATCHES`. Translating a stored
value would stop a Dutch member matching an English one. Only *labels* are translated —
`opt_label()` in templates, `opt_label_for()` server-side, `interest_text()` for chips —
and they leave `value="…"` alone. A cross-language pairing test covers this.

Language lives in `session['lang']`, falling back to `Accept-Language`. `/lang/<code>`
sets it and returns to `?next=` (same-site paths only — it is reachable logged out).
`reset_session_keeping_language()` is used instead of `session.clear()` on sign-in and
sign-out, or picking Dutch and then registering would drop you back to English.

There is no mobile/desktop preview toggle any more; the phone layout comes from the real
viewport via one `@media (max-width: 720px)` block.

## Route map (`app.py`)

Regenerate with `grep -n "^@app.route" app.py` — line numbers below drift on every edit.

| Area | Routes |
|---|---|
| misc | `/lab`, `/`, `/lang/<code>` |
| auth | `/register`, `/login`, `/logout` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/status`, `/search/cancel`, `/search/filters/toggle`, `/search/filters/apply` |
| match lifecycle | `/match/<id>/state`, `/match/<id>/decide` |
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
