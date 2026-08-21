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
python check_auth.py      # 66 behaviour checks: auth, CSRF, safety, deletion, widening
python check_bots.py      # demo members never reach a real person's search pool
python check_presence.py  # a search leaves the pool when its browser stops polling
python check_i18n.py      # both languages complete, and they still match each other
python check_pin.py       # every profile and search lands in the one city
python check_landing.py   # the landing page's busyness line is true at every tier
python tools/check_hero_fits.py   # landing hero fits above the buttons (needs a browser)
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
- `templates/velvt.css` — the whole design system, a Jinja template of its own

**The stylesheet is not in the page.** It is 134KB — inlined in `base.html` it was
re-sent on every navigation and could never be cached, which made every page a 142KB
download. `/velvt.<digest>.css` renders `templates/velvt.css` once per process and
serves it `immutable` for a year; the digest is a hash of the rendered bytes, so a
changed colour is a new URL and a stale page's request 302s to the current one. It
stays a *template* rather than a static file because it interpolates `url_for()` for
the wordmark mask. Landing page: 142KB → 5.6KB, or 1.9KB gzipped.

**Responses are gzipped by `compress_response()`**, stdlib rather than a dependency —
nothing in front of the app compresses, so an uncompressed page stayed uncompressed
over the wire. It skips streamed responses (`direct_passthrough`, or a `send_file`
would be buffered into memory), anything already encoded, non-text types and bodies
under 1KB, and sets `Vary: Accept-Encoding` either way.

**Photos carry an ETag**, so a revisit is a 304 with no body rather than up to
`PHOTO_MAX_BYTES` again — six of those to a profile is the heaviest thing the app
serves, and it comes out of Postgres through the app with no CDN in front of it.

**`overflow: hidden` hides bugs, not just content.** `.wiz-fit` clips rather than
scrolls, which is right for a step whose contents are known — but it means a box
whose content outgrows it paints *over* what follows instead of scrolling, and
`document.scrollHeight` never changes. Every check that measured document overflow
called the page clean while the landing lede was drawn across the buttons on a real
phone. `tools/check_hero_fits.py` measures what a person would notice instead: the
hero's content against its own box, the lede inside it, and a hit-test on the first
button. `getBoundingClientRect()` is not enough on its own — it ignores ancestor
clipping, so it reports an overlap for content that is merely scrolled out of sight.

**Height is fluid, not stepped.** A step screen must never scroll, which used to be
held with `@media (max-height: 740px/700px)` blocks — two phones a pixel apart in
height got visibly different type, and every trimmed value had to be restated by hand.
`--fit` and `--fit-tight` in `:root` replace them: rems that shrink continuously with
viewport height (1rem at 740px and above, easing to 0.70/0.52rem at 540px), so
`calc(N * var(--fit))` keeps its full-height value and finds its own trim on the way
down. `--tabbar-h` states the fixed bar's height from the same token, and `main`
reserves exactly that — the old flat 7rem reserve and the flat `-1.25rem` pull-up that
clawed it back were two constants in an unstated relationship, and on a short screen
the pull-up won and slid the wizard's Next row under the bar. `.match` redefines
`--fit-tight` locally with a higher knee, because at full size the reveal does not fit
an 812px phone. One height query survives, in `.match-note.is-aside`: an aside is a
line or it is nothing, and there is no fractional version to ramp to.
**Icons are a registry, not markup.** `templates/_icons.html` holds all 38 glyphs in
`ICONS` (keyed by what they *are* — a heart, a pin, a ruler) and a `SLOTS` map (keyed by
where they *go* — `tab.search`, `card.interests`, `rel.Long-term relationship`). Templates
call `{{ icon("tab.search") }}` and nothing else. They used to carry 28 inline `<svg>`
blocks across six files, several of them an `{% if %}` chain with a branch per option,
which meant an icon had no name to ask for, no list to choose from, and a weight change
meant 28 edits that could silently disagree — `search_start.html` had already invented
half the fix with a dict of path data keyed by relationship type.

Changing which mark a place uses is now one line in `SLOTS`; an empty value draws nothing,
which is how `.pill` carries an icon on interests and none on hobbies without either
template knowing. **The spec lives on the macro, not the drawings**: `ICON_STROKE` (2) and
`ICON_CAP` (round) are emitted on the `<svg>` and inherited by shapes that no longer state
their own, scaled per glyph because a few are drawn on a 20 or 21 box and 2px there would
read heavier than 2px on 24. The Restyler previews all of it and exports the diff.

- `docs/style-guide.html` — velvet-textured design system; `docs/deploy-gcp.md` — Cloud Run
- `docs/launch-readiness.html` — the pre-launch audit these changes came from, with what
  is still outstanding (image scanning, passkeys, selfie verification, stepped
  registration)
- `check_auth.py` — behaviour checks for auth, CSRF, safety and deletion
- `check_retention.py` — behaviour checks for the retention schedule
- `check_onboarding.py` — behaviour checks for the first-search gate and the explainer
- `check_presence.py` — behaviour checks for the search heartbeat and ghost matches
- `check_pin.py` — behaviour checks for the single-city pin
- `check_landing.py` — behaviour checks for the landing page's member/searcher line
- `translations.py` — every user-facing string, `en` + `nl`; `check_i18n.py` and
  `tools/check_translations.py` guard it
- `seed_demo.py` — 40 demo members, all live-searching and `is_bot=TRUE` so they reply in
  chat. Idempotent; `--reset` to rebuild
- `smoke.py`, `dev.ps1`, `docker-compose.yml` — local dev only, not deployed
- `vastai_client.py` — standalone Vast.ai GPU-rental CLI, **not imported by the app**
- `templates/_icons.html` — **every icon in the app, in one place.** See below
- `static/velvt-icon.svg` — the square tab mark; also served as `/favicon.ico`, since
  browsers ask for that whether or not a `<link rel="icon">` tells them to
- `make_search_avatars.py`, `static/velvet-searching.lottie` — **both dead now.** The
  searching animation is hand-rolled CSS: the dotLottie player was fetched from
  unpkg.com, which the app's own CSP forbids, so it never ran in production, and
  vendoring a ~250KB renderer onto the lightest screen in the app was the wrong
  trade. Kept on disk rather than deleted in case the artwork is wanted elsewhere
- `static/velvt-hero.{webm,mp4,webp}` — the two felt characters crossing the gap
  and holding on, behind the landing hero. **It is by far the heaviest thing the
  landing page asks for**: 344KB (VP9+alpha) or 227KB (H.264) against a page that
  is otherwise 5.6KB, so treat any further growth as a real decision. Only one
  video is fetched — the browser takes the first `<source>` it can play — and a
  `prefers-reduced-motion` visit fetches neither, because `landing.html` attaches
  the sources by script rather than in the markup and the 40KB still is the
  layer's own `background`. The background was cut per-frame with u2net
  segmentation, not a chroma key: the original backdrop is a soft pink gradient
  whose warm tones overlap the gold character, so keying punched holes in her.
  **Safari gets the `.mp4`, which is pre-composited on `--ink`** — VP9-alpha is
  not supported there and HEVC-with-alpha cannot be produced off a Mac. That
  file therefore assumes a dark ground, and is the one asset a palette change
  cannot reach

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

**A waiting search is only in the pool while its browser is still there.** Nothing marks
a row cancelled when someone closes the tab, so without a heartbeat the matcher pairs
live people with ghosts — an "it's a match", a five-minute room, and nobody on the other
side. `searches.last_seen` is rewritten by `touch_search()` from every request the
waiting screen makes (`/search/waiting` and both of its polls, `/search/status` and
`/search/chips`), and `SEARCH_ALIVE_SECONDS` (60s, many missed ticks) of silence drops
the row out of *every* pool query at once, because the liveness predicate lives inside
`CANDIDATE_ELIGIBLE_SQL` rather than in each query. Demo members are exempt — they have
no browser to poll with — which is dead weight in production, where `u.is_bot = FALSE`
has already excluded them. `check_presence.py` covers it.

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

**One city, and nobody is asked.** `SINGLE_CITY = "Maastricht"` is the whole switch.
`pinned_place()` applies it server-side at all five entry points that could otherwise
store a location — the profile form, the admin profile form, both search screens and
the search preview — and it *ignores* the form rather than trusting it, because the
field is no longer rendered and anything arriving under that name is a stale draft or
a hand-rolled POST. The value is asserted against `CITY_COORDS` at import, or distance
filtering would silently degrade to "anywhere".

Gone from the UI as a consequence: the profile form's location picker (replaced by a
plain statement of the city — a disabled input would still read as "changeable
later"), the wizard's "Where are you searching?" step, the criteria screen's Distance
switch (it cannot change who fits when everyone shares one set of coordinates), and
the city chip on the waiting screen (true of everyone by construction). The stepper
walks `.wiz-step` in DOM order and sizes its bar from the count, so the wizard
renumbered itself from six steps to five with no other change.

`_location_field.html` and `/api/places` are left intact but unreached, so
`SINGLE_CITY = None` restores the multi-city flow in full. `check_pin.py` posts
Berlin, Vienna and Zurich at every entry point and asserts Maastricht is what lands.

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

## What the landing page claims

`landing_pulse()` builds the one line under the headline from four tiers, tried in
order: people searching this minute (the only tier that earns the pulsing dot),
searches started today, members registered, and — below `MEMBER_COUNT_FLOOR` (25) —
no number at all, just an invitation. **Every tier is a fact.**

A launching product has a thin first week and "3 members" reads worse than saying
nothing, but the fix for a number you don't want to show is to not show it, not to
print a different one: a visitor decides whether to sign up partly on how many people
are already here, so a figure that isn't true is a false answer to the question they
are actually asking — and in the EU that is a misleading commercial practice, not a
growth tactic. `MEMBER_COUNT_FLOOR` therefore governs *when* the true count appears,
never what it says. Demo members are excluded from every tier.

`/admin/members` is where the real figure lives, with demo accounts counted separately
rather than folded in, and every member's profile one click away. `check_landing.py`
holds each tier to the database.

## Languages

Two, `en` and `nl`, in `translations.py` — plain dicts, no gettext and no build step,
because the app is one module with no compile stage and 1,300 words of copy does not
justify an extraction toolchain. `translate()` falls back requested → English → the key
itself, so a gap is a wrong word rather than a 500. Templates get `t()`, `opt_label()`
and `interest_text()` from the context processor; `app.py` has the same `t()` for the
copy it produces itself.

**Adding a third language is a `LANGUAGES` entry and a copied block** — the switcher,
`/lang/<code>` and the validation all read that list. A partial language ships safely.

**Option values are never translated.** `GENDERS`, `SEEKING_OPTIONS`,
`RELATIONSHIP_TYPES`, `BODY_TYPES` and friends are stored in `searches`/`profiles` and
compared as strings by `searches_compatible()` and `SEEKING_MATCHES`. Translating a
stored value would stop a Dutch member matching an English one and nothing would look
broken — so the value stays canonical English and only its *label* is translated, via
`OPTION_LABELS`. `check_i18n.py` pairs a Dutch reader with an English one to hold that.

`current_language()` prefers the session, then `Accept-Language`, then English, so a
Dutch speaker's first visit is already Dutch. The choice survives sign-in and sign-out:
`reset_session_keeping_language()` replaces `session.clear()` there, since clearing it
sent someone who had just chosen Dutch back to English at the moment they committed.
`/lang/<code>` is a plain link (GET) and only ever redirects to a same-site path.

The legal pages, `/settings` and `/admin` are still English only: their copy is long,
and the terms and privacy text is not something to machine-translate without a human
signing it off.

## Route map (`app.py`)

Regenerate with `grep -n "^@app.route" app.py` — line numbers below drift on every edit.

| Area | Routes |
|---|---|
| misc | `/lab` (admin), `/`, `/healthz` + `/-/health`, `/how-matching-works`, `/lang/<code>`, `/robots.txt`, `/tasks/purge-deletions` |
| auth | `/register`, `/login`, `/logout`, `/verify/<token>`, `/verify/resend`, `/forgot`, `/reset/<token>` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| legal | `/terms`, `/privacy`, `/imprint`, `/safety`, `/faq` |
| settings | `/settings`, `…/password`, `…/sessions/<id>/revoke`, `…/sessions/revoke-others`, `…/consent`, `…/export`, `…/delete`, `…/delete/cancel` |
| safety | `/report/<id>`, `/block/<id>`, `/unblock/<id>` |
| moderation | `/admin/members`, `/admin/reports`, `…/<id>/resolve`, `/admin/users/<id>/reinstate` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/chips` (GET+POST), `/search/status`, `/search/cancel` |
| match lifecycle | `/match/<id>/state`, `/match/<id>/decide`, `/match/<id>/skip-reveal` |
| chat | `/chats`, `/chat/<id>`, `…/messages`, `…/send` |

Every POST needs a CSRF token: `{{ csrf_token() }}` in a hidden `csrf_token` field, or an
`X-CSRF-Token` header for `fetch` (`window.velvtCsrf()` in `base.html`). A new form
without one fails with a 400, not silently.

Before a first search can start, `profile_completeness()` requires name, age, gender,
seeking and one photo — `PROFILE_REQUIRED` — and `/search` bounces to `/profile/edit`
naming what is missing. Everything in `PROFILE_OPTIONAL` only feeds the strength meter.
Both lists live in one place so the meter can never nag about something the gate does
not enforce, or vice versa.

The first GET of `/search` also redirects once to `/how-matching-works`, which explains
the 20s reveal / 5min chat / mutual decision before it happens rather than during.
Acknowledging is a POST — a GET would let a half-loaded page count as read — and it
sets `users.match_intro_seen_at`, on the account rather than the session so a second
device does not see it again.

`/tasks/purge-deletions` is for a scheduler, not a browser: it authenticates with
`X-Task-Token` against `TASK_TOKEN` and refuses outright when that is unset. Cloud Run
has no background worker, so without something calling this daily, deletions never
actually complete.

That one call does two jobs — `purge_due_deletions()` finishes accounts past their
grace period, then `purge_expired_data()` enforces the retention schedule. The
schedule is the block of `*_RETENTION_DAYS` constants near `DELETION_GRACE_DAYS`
(`app.py:~247`), and each one carries the reasoning for its number:

| What | Kept | Why not longer |
|---|---|---|
| ended matches + their messages | 90 days | over for both sides; only recent history |
| cancelled/matched searches | 7 days | working state — the pairing lives in `matches` |
| exact `searches.lat/lng` | 30 days | then rounded to ~1km, not deleted |
| resolved reports | 365 days | the record of a moderation decision |
| `rate_hits` | 2 days | operational, outlives no window |
| `security_events` | 90 days | holds IP addresses; not exempt for being useful |

`security_event()` records login success/failure, password changes and resets, reports
filed, admin actions, CSRF rejections and rate-limit hits — to the `security_events`
table *and* as a single-line JSON object, which is what Cloud Logging picks up as a
structured payload. It swallows its own failures on purpose: an audit trail that can
take a request down with it makes the service less reliable and no more accountable.

Writing to a table as well as the log is what makes `check_login_failure_spike()`
possible — failures are counted service-wide, not per-IP, because the rate limiter
already covers one address hammering one account and the pattern it cannot see (many
addresses, many accounts, each under the limit) is the one worth an alert. It fires
once and then stays quiet for `SPIKE_ALERT_COOLDOWN_MINUTES`.

An ended match with an **unresolved** report against it is never purged, whatever its
age — expiring the evidence would answer the complaint by losing it. `check_retention.py`
covers that case, and pairs every "this goes" check with a "this stays" control.

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
