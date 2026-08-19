# Velvet

Flask 3 + **PostgreSQL** dating app, server-rendered Jinja. Deps: `flask`, `requests`,
`gunicorn`, `psycopg[binary]`, `psycopg-pool` — no ORM, no LLM SDK.

The dependency list is deliberately short, so things that usually arrive as a library are
hand-rolled instead: CSRF on `itsdangerous` (a hard Flask dependency, so already
installed — do **not** add it to `requirements.txt`), rate limiting on a Postgres table,
and transactional email as an HTTPS call to Resend through `requests`. Postgres-backed
rate limiting is also the *correct* choice here, not just the dependency-free one: Cloud
Run runs many instances against one database, and an in-process counter would hand an
attacker the whole budget again on every instance they reached.

## Local development

```powershell
docker compose up -d      # Postgres, once per boot
.\dev.ps1                 # venv + seed + Flask with the reloader
# edit -> save -> refresh the browser. No restart, no git.
python smoke.py           # hit every GET route, report 5xxs
python check_auth.py      # 84 behaviour checks: auth, CSRF, safety, deletion, widening, email change
python check_bots.py      # demo members never reach a real person's search pool
```

`smoke.py` proves routes render; `check_auth.py` proves the security-relevant ones
*behave* — session revocation, the age gate, CSRF rejection, blocking, and what account
deletion does to the other person's chat. `check_bots.py` re-runs itself with
`ALLOW_BOT_MATCHES` both ways, since the flag is read at import.

Run all three after touching auth, search eligibility, or anything under `/settings`.
Both check suites cancel waiting searches to control the pool, so re-seed with
`python seed_demo.py` before clicking around afterwards.

**Local iteration does not commit.** Work on disk until the feature is actually
done, then `git add -p` and commit once. Do not push work-in-progress.

`.env` (from `.env.example`) carries `DATABASE_URL`, `APP_SECRET_KEY`, `FLASK_DEBUG`,
`AUTO_LOGIN`, `ALLOW_BOT_MATCHES`, the Resend settings, and pool sizing.

**`FLASK_DEBUG` selects the whole personality.** It defaults to *off*, so anything that
forgets to set it gets production behaviour. With it off: `APP_SECRET_KEY` and
`APP_ADMIN_PASSWORD` must be set or the app refuses to serve and fails `/healthz`
(a misconfigured revision must never replace a working one), `AUTO_LOGIN` is ignored, and
session cookies are `Secure`. Pin `APP_SECRET_KEY` locally too — the dev fallback is
fixed, but changing it logs you out.

**`ALLOW_BOT_MATCHES=1` is local-only.** Without it the seeded demo members are excluded
from every search pool, which is what production needs and what makes local testing
impossible — so `.env.example` turns it on.

`setup.ps1` is first-time bootstrap only (clone + install). Use `dev.ps1` day to day.

## Model and effort

Everyday work: **Opus 5 at `medium`**. `low` for CSS/copy tweaks, `high` for planning
or multi-route refactors, `xhigh` for the search/matching logic. Haiku 4.5 for bulk
mechanical edits. `/fast` doubles cost — only when actively waiting on the browser.

Keep replies concise; prefer the smallest diff that does the job.

## Layout

- `app.py` — **~5,000 lines**, single module: all routes, DB access, and helpers
- `templates/` — 27 Jinja templates, all extending `base.html`
- `docs/style-guide.html` — velvet-textured design system; `docs/deploy-gcp.md` — Cloud Run
- `docs/launch-readiness.html` — the pre-launch audit these changes came from, with what
  is still outstanding (image scanning, security headers, retention purge, passkeys,
  selfie verification, onboarding rework)
- `check_auth.py` — behaviour checks for auth, CSRF, safety and deletion
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

Tables: `users` (+`is_bot`/`email`/`dob`/`status`), `profiles`, `matches`
(+`status`/`paired_at`/`decision_a`/`decision_b`/`ended_at`), `searches`
(+`lat`/`lng`/`use_*`), `messages`, `photos`, `sessions`, `email_tokens`, `blocks`,
`reports`, `admin_actions`, `legal_acceptances`, `consents`, `rate_hits`.

**Login is not the cookie.** The cookie carries an opaque token; `sessions` is the
authority, so logout, password reset and suspension all take effect immediately and on
every device. `current_user()` resolves it once per request into `g` (via the
`load_current_user` before-request hook, which also does the throttled `last_seen_at`
write — it commits, which is why it can't live inside `current_user()` itself). There is
no `session["user_id"]` any more; use `current_uid()`.

`users.status` is `active` / `suspended` / `banned` / `pending_deletion` / `deleted`.
Only `LOGIN_ALLOWED_STATUSES` may hold a session — `pending_deletion` is in that list on
purpose, since a grace period you can't sign in to cancel is not a grace period.

**Changing your email goes through `pending_email`, not straight into `email`.**
`POST /settings/email` requires the current password (like `/settings/password` does) and
writes only `users.pending_email` — `email` and `email_verified_at` stay whatever they
were. The address only takes effect when its owner opens the link sent to it and hits
`GET /settings/email/confirm/<token>`, which is what actually moves `pending_email` into
`email` and stamps `email_verified_at`. That confirm route needs no login, the same as
`/verify/<token>` and `/reset/<token>` — the token is the proof. A notice also goes to the
*old* address (no link, nothing to confirm) so a hijacked session doesn't move the
account's recovery address without its real owner noticing. `pending_email` carries no
uniqueness of its own — two accounts can point it at the same address — so the confirm
route's `UPDATE` (which does hit the unique index on `email`) is wrapped for
`psycopg.errors.UniqueViolation`: whoever confirms first wins the address, the other's
`pending_email` is cleared, nothing corrupts.

**Deleting an account anonymises the row rather than removing it.** Every foreign key into
`users` cascades, so a `DELETE` would take the `matches` with it and erase the *other*
participant's conversation. `purge_due_deletions()` destroys the profile, photos,
searches, sessions, tokens and consents, nulls `messages.sender_id`, and leaves a
numbered tombstone that renders as "Deleted member". Anything joining `profiles` from a
message or a match must therefore be a `LEFT JOIN`.

Three queries select the waiting search pool — `try_pair()`, `_search_pool()` and
`search_preview()` — plus the landing page's count. They all interpolate
`CANDIDATE_ELIGIBLE_SQL` and `NOT_BLOCKED_SQL`. **Keep them in step:** if the preview and
the matcher disagree, the preview promises candidates the matcher then refuses.

`search_blockers()` explains *why* a search isn't matching — a count per filter of who
would fit without it, plus a concrete suggested value for each, every one verified through
a real `searches_compatible()` call. It feeds two screens: the criteria screen's live
preview, and the waiting screen's "loosen one thing" buttons via `widen_options()`. Both
follow the same rule — **offers appear only when nothing fits**, never alongside a
non-zero count.

`POST /search/widen` takes only *which* offer was taken, never a value: it recomputes the
suggestions and applies its own, so the endpoint can't be used to set an arbitrary search
and a stale page can't apply a number that has stopped making sense. It writes one column
with a targeted `UPDATE` — **not `save_search()`**, which resets `created_at` and would
drop the searcher back below `MIN_SEARCH_SECONDS` and to the back of `try_pair()`'s
longest-wait ordering as a penalty for adjusting.

Starting a search is **two screens**: `/search` picks the connection type and the location
+ radius (carried to screen 2 in `session["search_draft"]`), `/search/criteria` asks which
filters matter as a list of switches. Each switch writes a `searches.use_*` column —
`use_gender`/`use_age`/`use_distance`/`use_physical` — read by `searches_compatible()` via
`.get(key, True)`; a switch that is off leaves its panel's inputs `disabled`, so those
fields never reach the server at all. `use_relationship` is always TRUE: it *is* the tile
choice. Interests has no `use_*` column of its own — the stored text *is* the switch: "off"
stores `''`, which `searches_compatible()` reads as "no preference". When it's non-empty it's
a real filter (requires the other side to share at least one stemmed keyword), and it still
breaks ties in `try_pair()`'s ranking among whoever's left.

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

## Route map (`app.py`)

Regenerate with `grep -n "^@app.route" app.py` — line numbers below drift on every edit.

| Area | Routes |
|---|---|
| misc | `/lab` (admin), `/`, `/healthz`, `/tasks/purge-deletions` |
| auth | `/register`, `/login`, `/logout`, `/verify/<token>`, `/verify/resend`, `/forgot`, `/reset/<token>` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| legal | `/terms`, `/privacy`, `/imprint`, `/safety` |
| settings | `/settings`, `…/password`, `…/email`, `…/email/confirm/<token>`, `…/email/cancel`, `…/sessions/<id>/revoke`, `…/sessions/revoke-others`, `…/consent`, `…/export`, `…/delete`, `…/delete/cancel` |
| safety | `/report/<id>`, `/block/<id>`, `/unblock/<id>` |
| moderation | `/admin/reports`, `…/<id>/resolve`, `/admin/users/<id>/reinstate` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/status`, `/search/options`, `/search/widen`, `/search/cancel` |
| match lifecycle | `/match/<id>/state`, `/match/<id>/decide`, `/match/<id>/skip-reveal` |
| chat | `/chats`, `/chat/<id>`, `…/messages`, `…/send` |

Every POST needs a CSRF token: `{{ csrf_token() }}` in a hidden `csrf_token` field, or an
`X-CSRF-Token` header for `fetch` (`window.velvtCsrf()` in `base.html`). A new form
without one fails with a 400, not silently.

`/tasks/purge-deletions` is for a scheduler, not a browser: it authenticates with
`X-Task-Token` against `TASK_TOKEN` and refuses outright when that is unset. Cloud Run
has no background worker, so without something calling this daily, deletions never
actually complete.

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
