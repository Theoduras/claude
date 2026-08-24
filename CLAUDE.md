# Velvet

Flask 3 + **PostgreSQL** dating app, server-rendered Jinja. Deps: `flask`, `requests`,
`gunicorn`, `psycopg[binary]`, `psycopg-pool`, `cryptography` — no ORM, no LLM SDK.

The dependency list is deliberately short, so things that usually arrive as a library are
hand-rolled instead: CSRF on `itsdangerous` (a hard Flask dependency, so already
installed — do **not** add it to `requirements.txt`), rate limiting on a Postgres table,
and transactional email as an HTTPS call to Resend through `requests`. Postgres-backed
rate limiting is also the *correct* choice here, not just the dependency-free one: Cloud
Run runs many instances against one database, and an in-process counter would hand an
attacker the whole budget again on every instance they reached.

`cryptography` is the one exception to that instinct, and `webpush.py` says why: Web
Push means ECDH on P-256, HKDF, an AES-GCM seal and an ES256 signature, and those are
not "a library for something you could write in twenty lines" — they are the category
where hand-rolling leaks keys and plaintexts. Everything *above* the primitives is
still ours, at ~150 lines against `pywebpush` and its four transitive dependencies.

## Local development

```powershell
docker compose up -d      # Postgres, once per boot
.\dev.ps1                 # venv + seed + Flask with the reloader
# edit -> save -> refresh the browser. No restart, no git.
python smoke.py           # hit every GET route, report 5xxs
python check_auth.py      # 145 behaviour checks: auth, CSRF, safety, deletion, verification
python check_bots.py      # demo members never reach a real person's search pool
python check_presence.py  # a search leaves the pool when its browser stops polling
python check_i18n.py      # both languages complete, and they still match each other
python check_pin.py       # every profile and search lands in the one city
python check_notifications.py  # who is told what, how often, over which channel
python check_landing.py   # the landing page's busyness line is true at every tier
python check_design.py     # the admin design editor, and what it refuses
python check_content.py    # rewriting words and re-pointing icons from admin
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
- `templates/` — 32 Jinja templates, all extending `base.html`
  (plus `sw.js`, which is a template only because it interpolates `url_for`)
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

**`PHOTO_MAX_BYTES` is 25MB, and what is *stored* is downscaled twice over.** 2MB was
rejecting an ordinary photo from an ordinary phone, so the limit was being enforced
against the camera rather than against anything the app cares about. Accepting 25MB and
keeping it would only have moved the problem into the database, so nothing keeps it:

- **The browser re-encodes before uploading** (`_profile_fields.html`), to
  `PHOTO_UPLOAD_MAX_EDGE` on the long side. A 10.7MB 4032×3024 camera frame leaves as
  1.5MB — 86% of the transfer saved before a byte goes over mobile data. This is also
  what makes a six-photo save possible at all; see the ceiling below.
- **`downscale_photo()` does it again on the way in**, and that one is the guarantee: it
  runs on whatever actually arrives, including from a client that executed none of our
  JavaScript. Same 10.7MB photo, 1.4MB stored.

**It strips EXIF, and that matters more than the pixels.** A phone photo routinely
carries the GPS coordinates of where it was taken. `pinned_place()` puts everyone in one
city deliberately; storing someone's street and handing it to whoever they match with
would undo that quietly, with nothing on screen looking wrong. Orientation is *applied*
before the tag is dropped, or every portrait photo would be stored on its side.
An image that will not decode is stored as it came — it already passed the magic-byte
check and the size cap, and refusing a save because an optimisation failed is the wrong
trade.

**`MAX_CONTENT_LENGTH` is capped by the platform, not by our arithmetic.** The form's own
sum says `PHOTO_MAX_PER_USER * PHOTO_MAX_BYTES` (~151MB), but **Cloud Run refuses an
HTTP/1 request over 32 MiB at the front door**, before it reaches the container, and
answers with its own error rather than ours. So the cap is the smaller of the two, and
six 25MB originals in one request cannot be made to work here by raising a number —
the browser-side re-encode is what makes six photos a few megabytes instead. On Cloud Run
`/tmp` is a tmpfs, so Werkzeug's spill of a body that size is real instance memory: see
the `--memory` note in `docs/deploy-gcp.md`.

A 413 is now a rendered page (`upload_too_large.html`) rather than Werkzeug's bare one —
there was no `errorhandler` at all before, which at a 25MB limit people would actually
have met. `_profile_fields.html` also checks each picked file's size before anything is
sent, because the server's answer cannot arrive until the whole upload has.

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
- `check_auth.py` — behaviour checks for auth, CSRF, safety, deletion and the email gate
- `check_retention.py` — behaviour checks for the retention schedule
- `check_onboarding.py` — behaviour checks for the first-search gate and the explainer
- `check_presence.py` — behaviour checks for the search heartbeat and ghost matches
- `check_pin.py` — behaviour checks for the single-city pin
- `check_notifications.py` — behaviour checks for the notification system
- `webpush.py` — Web Push spoken directly: VAPID and aes128gcm. Run it to mint a key
  pair. Imported by `app.py` and nothing else
- `check_design.py` — behaviour checks for the admin design editor
- `check_content.py` — behaviour checks for the words and icons editors
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
  landing page asks for**: 2.1MB (VP9+alpha) or 227KB (H.264) against a page that
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
  cannot reach.

  **On a phone the `object-fit: cover` crop shows a narrow vertical slice of a
  landscape shot**, and this footage spends its first ~6 of 10 seconds with the
  pair too far apart for either one to be in that slice — mobile was watching
  an empty crop for most of the clip before they finally closed the gap into
  frame. `landing.html`'s script jumps `currentTime` to 6 before playing, mobile
  only (`data-viewport === "mobile"`), trading the empty lead-in for the part
  that was the point. Desktop's `object-fit: contain` shows the whole frame, so
  it plays from the start untouched.

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
picked files with `URL.createObjectURL`, an × marks a photo for removal, tapping a tile
makes it the main one, and dragging reorders. A removed tile collapses out of the strip
rather than sitting there greyed out with an Undo button drawn over it — it stays in the
DOM (the transcript below still needs it, and Undo needs something to bring back), just
out of the flex flow, and a quiet line under the strip carries the one Undo that matters:
how many are gone, and a single tap for the most recent. The browser transcribes
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

## Notifications

Four reasons to interrupt someone — **a new message**, **someone searching you could
match with**, **a reminder**, **a new feature** — and three ways of doing it: an open
tab, a push to a browser that is closed, an email. `NOTIFY_KINDS` and `NOTIFY_CHANNELS`
(`app.py:~410`) are that grid, and `/settings` renders it as one.

**The kinds are the reasons, not the transports.** A single "notifications on/off", or
an email switch with nothing saying what it is about, gives someone the choice between
all of it and none of it — which is how people end up turning everything off. Rows are
what happened, columns are how you hear about it.

**`notifications` is a ledger, and the three channels read from it.** Without it, "did
we tell them?" has three answers that cannot be reconciled — and the in-tab channel
could not exist at all, since a browser tab has nowhere to receive anything and can
only poll. `/notifications` is a *history*, not a fourth channel: turning every switch
off means "do not interrupt me", never "do not tell me".

Two defaults are deliberately off. **Feature announcements are opt-in for mail and
push** — an announcement is marketing however carefully it is written, and mailing it to
people who never asked is what PECR and the ePrivacy Directive are about. **Pool notices
are opt-in for mail** for a plainer reason: they are true for about five minutes, and an
inbox is not a five-minute medium.

`notify()` records the row and starts it moving; the four timestamps on it *are* the
delivery record. `seen_at` is "an open tab raised it", `read_at` is "they opened it",
and `pushed_at`/`emailed_at` mean that channel is finished with the row — delivered,
refused, or not wanted. Nothing is ever mailed to an unconfirmed address, whatever the
preference says.

**Only a chat message is pushed on the request that caused it** (`push_now=True`): one
call, to one person's subscriptions, while the conversation is still happening.
Everything else leaves `pushed_at` NULL for `/tasks/notifications` to drain, because a
search that notifies twelve people must not hold the searcher's request open for twelve
sequential round trips to somebody else's push service.

**Email waits `NOTIFY_EMAIL_DELAY_MINUTES` (15) and is then skipped if it has been
read.** Most notices are read before they are due, which is the point — and three that
are still due become one email, not three.

`NOTIFY_DEDUPE_MINUTES` is what stops it becoming noise: ten messages in one
conversation are one notification (`dedupe_key = message:<match_id>`), and a second
pool notice twenty minutes after the first is nagging.

**The pool notice never names anybody.** It only goes out when the two searches are
mutually compatible by the same `searches_compatible()` the matcher uses — if they
would not be paired, "someone you could match with" is not true — and anyone already
searching is skipped, since the matcher will pair them anyway. Blocked either way,
already in a live match, consent withdrawn, or a demo member: all excluded.
`POOL_NOTICE_MAX_RECIPIENTS` (12) is what keeps it from becoming a broadcast channel.
It hangs off `save_search()` rather than the two screens that call it, so a third entry
point cannot silently fail to tell anyone.

**Web Push is spoken directly, in `webpush.py`.** VAPID (RFC 8292) signs an ES256 JWT
that identifies us to the push service; the payload is sealed with aes128gcm (RFC 8291)
so the service relays bytes it cannot read. `python webpush.py` mints the key pair.
Unset keys mean the push channel is simply off and the other two carry on — the settings
screen says so rather than offering a button that cannot work.

`push_subscriptions.endpoint` is UNIQUE service-wide and is the natural key: signing in
as somebody else on a shared laptop **moves** the subscription rather than leaving the
previous account's notifications arriving on a device that is no longer theirs. A 404 or
410 from a push service means the browser is gone, so the row is deleted rather than
retried forever; anything else is counted, and only `PUSH_FAILURE_LIMIT` consecutive
failures give up on it.

**The unread count is worn in four places and read once.** `unread_badge()` in
`base.html` renders it into the desktop nav, the desktop footer, the tab bar's More
sheet and — the one that matters on a phone, where the other three are hidden or behind
a tap — the More trigger itself. It carries `hidden` at zero rather than drawing a "0",
caps at `99+`, and the same poll that raises the in-tab toasts repaints all four, so a
page left open for ten minutes does not go on claiming a number that has moved. The
count is cached on `g` for the render, and cleared in `load_current_user()` — `g` is
scoped to the *app* context, not the request, so without that a reused app context
(a test client inside `test_request_context`, a CLI command) carries the previous
request's number into the next one.

`/sw.js` is served from the root, not `/static`, so its scope is the whole site — a
worker registered from `/static/` may only control `/static/`, and one that cannot open
the page it is notifying about is no use. It has no fetch handler on purpose: this
worker exists to receive pushes, not to become a second copy of the app's routing.
`/manifest.webmanifest` is there because iOS hands out a push subscription only to a web
app that was added to the home screen.

**Notification text is stored rendered, in English**, the same choice the transactional
email already makes and for the same reason: mail and push leave with no request and no
session, so there is no language to render into.

`check_notifications.py` holds all of it, and pairs every "this goes out" with a "this
stays quiet" — a notifier that tells everybody everything passes any test that only
asks whether something was sent. It also decrypts a real payload the way a browser
would, because if `encrypt()` and the browser ever disagree every push in production is
an undecryptable blob and nothing else would say so.

## The shell (ch.05 of `velvt.css`)

Thirty screens were redrawn against the Velvt Light artifact, and the redraw
turned out to be **eight components rather than thirty layouts**: an app bar, a
docked primary button, a filled field, a flat option row, a switch, a state chip,
a labelled card, and a floating tab pill. ch.05 states them once, at the end of
the file — same specificity, later wins — so the shape each component *used* to
have is still readable in place rather than deleted. It is the same bargain the
admin's design overrides make.

**One app bar, on every screen but the landing page.** The wordmark, centred on
the frame, with an optional chevron in the left flank where a screen is a step
inside a flow. `_shell.html`'s `appbar()` renders it and `base.html` puts it in a
`{% block appbar %}`, so a template overrides it with a chevron, with a title, or
with nothing. The landing page overrides it away — its hero carries the mark
itself — and also sets `{% block shell_class %} is-bare{% endblock %}`, which
drops the tab bar: it is the one screen with nothing to navigate between.

**The phone's top nav is gone.** It was a horizontally scrolling strip of links
running off the right edge of every screen — Search, Chats, Profile,
Notifications and, for an admin, seven more. Every one of them already lives in
the tab bar or its Info sheet. Desktop keeps the full nav, where the links fit
and the tab bar does not exist.

**Three grounds became tokens**, which is exactly why light mode had been
painting dark inputs on a white page: `--field` (the filled well of an input or
a row that reads as one), `--bar` (the tab pill's ground — the one surface that
stays dark in both worlds, so it carries its own `--bar-ink`/`--bar-quiet`), and
`--delight` (the acid yellow of a state that is *running*: the TIMED chip, and
nothing else). A literal cannot have a second answer.

**The velvet stops at four panels in light.** `body`'s pile, folds and nap
already stopped (ch.02); `.card`, `.profile-card`, `.sheet-panel` and
`.veil-card` each carried the same three layers privately, which is why
`/settings` and `/chats` read as purple pages. The dark world keeps all of it.

**`--champagne` is the link hover, and nothing else now.** It is the highlight a
velvet ground needs, so the file had reached for it twice — for emphasis (a
count, a readout, a countdown) and for the focus ring. In light it resolves to
`#8A7C0C`: gold as *text*, right for a link and wrong for a focus ring on a
violet button or for every emphasised number in the app. Both jobs moved to
`--violet`.

**A radio is not a switch.** `.switch-row` draws checkboxes as toggles by styling
the input itself (`appearance: none`), so it stays a real checkbox to the
keyboard, the screen reader and the form — no extra markup. Radios in the same
class get the option row's check instead, because "one answer out of several"
and "on or off" are different questions and the report screen was asking the
wrong one six times.

**`.switch-track` had no rule at all** before this, so every filter on
`/search/criteria` rendered as a naked browser checkbox beside an empty span.

**`--serif` is still a token and nothing is set in it.** ch.02 moved the headline
off it; ten smaller places kept it (a profile's About text, the sheet title, a
chat name, the edit heading), which meant the app read in two typefaces with no
rule about which said what.

**Two labels differ from their values on purpose.** `OPTION_LABELS` has an `"en"`
block now: "Short-term relationship" and "Friendship" are still the stored values
`searches_compatible()` compares, and "Something casual" and "New friends" are
what the design says on screen. A label is exactly the thing that is allowed to
differ from the value behind it.

**Answering a step is the way forward.** Only the single-choice step advanced on
its own; every other one wanted a tap on Next after the tap that answered it —
two taps for one decision, five times over. The two kinds of step settle
differently, because a multi-select has no single tap that means "done": one
answer out of several moves at `AUTO_PICK_MS` (200ms — the choice is complete
the instant it is made), and a multi-select or a slider moves at
`AUTO_SETTLE_MS` (1300ms) *after you stop*, each further tap cancelling the
pending move and restarting the wait. Next stays: it is the way on for someone
who has answered nothing (interests and body type are both legitimately empty)
or who does not want to wait, and the last step never auto-advances — starting
a search is a deliberate tap. `scheduleAuto()` re-checks everything at the
moment it fires rather than trusting what was true when it was set: the step
may have moved, the last box may have been unticked, and the interest overlay
may be open over the top of it.

**Two English strings were hard-coded in the wizard** and are not any more: the
step counter was assembled in the script, and "Start searching" was printed by
`.wiz-next.is-final::after` in the stylesheet. Both are real strings carried on
the element.

Known and not fixable in CSS: the landing hero footage crops its own subject, and
the Safari `.mp4` is pre-composited on `--ink`, so on a white page Safari shows a
dark ground behind the characters until that file is remade on a Mac.

## Design tokens, editable without a deploy

`/admin/design` edits the stylesheet's `:root` live. The names and their
defaults are **read out of `templates/velvt.css`** (`_parse_root_tokens()`),
never restated in `app.py` — a second list would be a second source of truth,
and it fails silently in the worst direction: a token renamed in the file would
still be offered, saved happily, and paint nothing.

**Only what differs is stored.** `design_tokens` holds the changed rows and
nothing else, so an empty table *is* the shipped design and Reset is a
`DELETE`. Storing the whole palette instead would fork it: a colour edited in
the file would go on being overridden by a stale copy of its old value, with
nothing on screen explaining why the deploy did nothing.

The overrides are **appended** to the sheet rather than merged into `:root` —
same specificity, later wins — so the file's own value stays visible above
them, and "what did the admin change?" is answerable by reading the CSS.

`_render_stylesheet()` hashes the overrides with the body, so a saved colour is
a new digest and a new URL: a browser holding the `immutable` sheet for a year
fetches the new one. `design_overrides()` caches per instance for
`DESIGN_CACHE_SECONDS` (10) — `css_digest()` runs on every page render, so it
cannot be a query per page, but Cloud Run runs many instances and only the one
that took the save knows immediately.

**Values are validated, admin or not**, because they land in a stylesheet
served to every visitor: anything that could close the declaration and open a
new rule (`;{}<>@`, comment markers) is refused, and 200 characters is the cap.
That is the whole attack, and it is also how a typo silently destroys the sheet
from that point on.

`DESIGN_LOCKED` keeps `--fit`, `--fit-tight`, `--tabbar-h` and `--nap` out of
the editor — the height curve, the bar height derived from it, and an embedded
texture. A colour picker has nothing useful to say about any of them and a bad
value breaks every layout at once.

**The screen picker previews real routes, not reproductions.** `DESIGN_PREVIEW`
is a list of GET paths that render for a signed-in admin, shown in an iframe;
the Restyler had to rebuild all 30 screens inside the tool, but here the app
*is* the preview, so no screen can go quietly out of date. It cost one header:
`X-Frame-Options` is `SAMEORIGIN` and the CSP's `frame-ancestors` is `'self'`
rather than `'none'`. The difference between those and `DENY`/`'none'` is only
whether our own pages may frame our own pages — a cross-origin frame is still
refused.

**The inspector answers "what does this element paint with?"** — a question an
element cannot be asked directly, since its colours come from CSS rules rather
than from anything stored on it. Each token is resolved once per screen against
a hidden probe element, giving a computed value per token; the clicked
element's own computed background/text/border are then looked up in that map.
A colour matching no token is a literal in the stylesheet, and is reported as
one rather than silently ignored. Clicks in the frame are swallowed
(`preventDefault`) — the preview is for looking at, and a click that followed a
link or submitted a form would navigate away or change real data.

**`design_palettes` is the Restyler's saved states.** A palette is the whole
override set under a name, so a direction can be parked instead of being the
thing you were too nervous to overwrite. Restoring **replaces** rather than
merges — a restore that kept whatever happened to be live alongside it would
land on a design nobody made — and every restored value goes back through
`design_value_ok()` and the known-token filter, so a palette cannot smuggle in
what the form would have refused.

**Two worlds, one set of names.** `:root` is dark and `:root[data-mode="light"]`
restates only the 17 colours that differ; everything structural falls through,
so a radius is one decision rather than two. `<html data-mode>` picks which
paints, from `app_settings['design_mode']`, and **both worlds are always in the
stylesheet** — switching mode does not change a byte of it, so it costs no
digest and no refetch. Overrides are per mode (`design_tokens.mode`), because
the same token has a different right answer in each. The editor edits a mode
independently of the live one: designing light before switching to it is the
normal order.

**A visitor can choose for themselves.** `/mode/<mode>` is the language
switcher's twin — a plain GET link, a same-site redirect back to the page you
were reading, and the choice stored in the visitor's own session — and the Info
sheet renders both as a labelled pair of segmented controls. `design_mode()`
reads the session first and the admin's `app_settings` value second, the same
order `current_language()` uses; `reset_session_keeping_prefs()` carries both
across sign-in and sign-out, since neither is privileged and dropping them
resets someone at the moment they commit. It costs nothing: both worlds are
always in the stylesheet, so this changes one attribute on `<html>` and not a
byte of CSS. `design_mode()` is guarded with `has_request_context()` — it is
called by `css_digest()` and the check suites with no request in flight, and
before the visitor's choice existed it was safe to call anywhere.

**Light is the shipped default**, because it is the design the artifact is
actually showing; one click in `/admin/design` changes it, and the dark world
is in the stylesheet either way.

The light values are the light column of the Restyler's own palette **plus the
one token edited in the artifact** (`--canvas` → `#FFFFFF`, which makes the
card surface a shade darker than the page rather than lighter — deliberate, and
what the artifact renders). Where the app and the artifact do not map 1:1 the
choice was settled by reading how the token is used, not by taste:
`--violet-deep` ends the velvet gradient, so it is `velvet-3`; `--champagne` is
a text and focus-ring colour nearly everywhere it appears, so it is
`delight-deep` rather than the acid yellow, which is unreadable doing that job
on white. The artifact's light column has no accent family at all, so
`--teal-crest` and `--teal-deep` are derived from `live` rather than borrowed
from `success`, which is a different job. **Where a name encodes a
dark role, the light answer inverts the role rather than the colour**:
`--violet-deep` is a ground behind violet content, so on a light page it is a
pale wash. `--champagne` is the light on the pile, invisible as a pale gold on
near-white, so it becomes gold-as-text. `--shade` is `#242424`, not black — on
a light ground pure black reads as a hole rather than as lift.

**None of that was possible while 192 colours were literals.**
`tools/tokenise_css.py` rewrote them into `color-mix()` over the palette; until
then a second palette would have repainted the tokens and left every literal
painting the first design underneath. `tools/check_css_tokens.py` proves the
rewrite in a real browser, because "color-mix against transparent
premultiplies" is a claim about a browser, not something Python can assert —
and it compares **numerically**, since Chromium serialises a color-mix result
as `color(srgb ...)` and a literal as `rgba(...)`, so a string comparison calls
every replacement a failure. A fully transparent literal is the one exception
and uses `rgb(from var(--x) r g b / 0)`: `rgba(11, 7, 19, 0)` and `transparent`
look identical alone but interpolate differently, and the difference is the
grey seam at the top of every scrim. 38 near-palette colours are deliberately
left as literals — snapping them to the nearest token would be a design change
smuggled in as a refactor.

`check_design.py` covers it, pairing every "this is applied" with a "this is
refused", asserting every previewable path renders, and that an override in one
world never leaks into the other.

## Words and icons, editable without a deploy

Same rule as the design tokens, twice more. **`copy_overrides` and `icon_slots`
hold only what differs**, so an empty table is exactly what shipped and a
string edited in `translations.py` still reaches the site unless someone
deliberately overrode that one key. Typing the shipped wording back into
`/admin/copy` **deletes** the row rather than storing an identical copy —
otherwise the first save would freeze that string against every future edit to
the file.

`say()` wraps `translate()` and is what `t()` and the template context now
call. It falls through to `translate()` whenever there is no override, so a
language with none behaves exactly as before, and it keeps `translate()`'s
`.format()` guard — an admin-written string is precisely where a typo'd
placeholder comes from, and that must degrade to unformatted text rather than
500 a page.

`/admin/icons` re-points a slot at a glyph. **The value can only ever be a name
in `_icons.html`'s `ICONS`**, checked on the way in and again in the macro, so
the table cannot introduce markup — the worst a wrong choice does is draw the
wrong picture. `_icon_registry()` parses `ICONS` and `SLOTS` out of the
template rather than restating them, so a glyph renamed there disappears from
the picker instead of lingering as an option that draws nothing. Two slots ship
empty on purpose (`pill.chip`, `pill.seeking`) and "— nothing —" stays a valid
choice.

The macro reads its override from a **Jinja global**, not the template context:
`base.html` imports `icon` with `{% from ... import icon %}`, which does not
carry context, so a context processor cannot reach inside it.

All three editors — tokens, words, icons — read from **one cached snapshot on
the same TTL**. Three independent caches expiring at three different moments
would show a page with the new words and the old icons for a few seconds.

`check_content.py` covers both, pairing each "the override is honoured" with a
"the shipped value is what you get without one".

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
| misc | `/lab` (admin), `/`, `/healthz` + `/-/health`, `/how-matching-works`, `/lang/<code>`, `/robots.txt`, `/tasks/purge-deletions`, `/tasks/notifications` |
| auth | `/register`, `/login`, `/logout`, `/verify/<token>`, `/verify/pending`, `/verify/resend`, `/verify/email`, `/forgot`, `/reset/<token>` |
| profile | `/profile/edit`, `/profile/<id>`, `/admin/profiles/new`, `/photo/<id>` |
| legal | `/terms`, `/privacy`, `/imprint`, `/safety`, `/faq` |
| settings | `/settings`, `…/password`, `…/sessions/<id>/revoke`, `…/sessions/revoke-others`, `…/consent`, `…/notifications`, `…/export`, `…/delete`, `…/delete/cancel` |
| safety | `/report/<id>`, `/block/<id>`, `/unblock/<id>` |
| moderation | `/admin/members`, `/admin/reports`, `…/<id>/resolve`, `/admin/users/<id>/reinstate`, `/admin/announce`, `/admin/design`, `/admin/copy`, `/admin/icons` |
| notifications | `/notifications`, `…/feed`, `…/seen`, `/push/subscribe`, `/push/unsubscribe`, `/sw.js`, `/manifest.webmanifest` |
| search | `/search`, `/search/criteria`, `/api/places`, `/search/preview`, `/search/waiting`, `/search/chips` (GET+POST), `/search/status`, `/search/cancel` |
| match lifecycle | `/match/<id>/state`, `/match/<id>/decide`, `/match/<id>/skip-reveal` |
| chat | `/chats`, `/chat/<id>`, `…/messages`, `…/send` |

Every POST needs a CSRF token: `{{ csrf_token() }}` in a hidden `csrf_token` field, or an
`X-CSRF-Token` header for `fetch` (`window.velvtCsrf()` in `base.html`). A new form
without one fails with a 400, not silently.

**A confirmed address is the door, not a nag.** `require_verified_email()` holds a
signed-in account on `/verify/pending` until it follows the link, because the address is
how someone gets back in after a lost password and how all four notification kinds reach
them at all — an account that never confirmed one is an account we cannot contact, and on
a dating app it is also the cheapest thing between a throwaway address and a real
person's inbox.

`VERIFY_GATE_EXEMPT` is the allowlist, and every entry on it is a way *out*: confirm,
resend, correct a typo, sign out, read what you agreed to, delete the account. **A gate
with no exits is a locked account** — and the address someone typed wrong is exactly the
address that cannot receive the link telling them so, which is why `/verify/email` exists
at all. It moves the row to the new address *unconfirmed*, so correcting a typo is not a
way past the gate. `/settings` is on the list because it is account administration rather
than the app: no matching, no chat, nobody else's profile, and erasure does not wait on a
mail provider.

`awaiting_verification()` excludes three groups, each of which would otherwise be locked
out of an account it can never open: deployments with no `RESEND_API_KEY` (no link can be
sent, so the gate would be a wall — this is what keeps local development working),
accounts with no address at all (the admin, the seeded demo members, admin-created
profiles — none was ever mailed a link), and admins (locking the one account that can fix
a broken mail setup behind that same mail setup is a trap with no floor).

The shell drops back to its signed-out shape while the gate holds — `awaiting_verification`
is in the context processor for exactly that. Every in-app link would bounce off the gate,
and a nav whose every item returns you to the page you are on reads as a broken app rather
than as a step you have not finished. The in-tab notification poll is off for the same
reason: `/notifications/feed` is behind the gate.

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

**There are two such endpoints now, and one shared secret.** `/tasks/notifications`
wants calling every few minutes: it drains the queued mail and the queued pushes and
raises the scheduled reminders. Separate from the daily purge because the cadences
genuinely differ, not because it was easier — mail that waits a day is not a
notification, and a deletion purge does not want running every five minutes.

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
| notifications | 60 days | a receipt for something that still exists elsewhere |
| push subscriptions | 180 days | aged from the last *successful* push, not creation |

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
