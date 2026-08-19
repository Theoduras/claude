"""Dating website — Flask app with login, registration, and profiles.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser. Register an account,
fill in your profile, and browse other members.

Data lives in PostgreSQL, so the app is stateless and can be scaled out
across many instances (see docs/deploy-gcp.md). Point DATABASE_URL at your
database, or set DB_USER/DB_PASS/DB_NAME plus either DB_HOST or
INSTANCE_CONNECTION_NAME (Cloud SQL). Set APP_SECRET_KEY to keep sessions
valid across restarts and across instances.

An admin account is created automatically on startup (username "admin",
password from APP_ADMIN_PASSWORD, default "admin12345"). Anyone can
register an account and log in. Set AUTO_LOGIN=1 to skip the login page
during local development and browse as admin automatically.
"""

import gzip
import hashlib
import json
import math
import mimetypes
import os
import re
import secrets
import time
from datetime import date, datetime as dt, timedelta, timezone

import requests
import psycopg
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

from translations import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    LANGUAGE_CODES,
    LANGUAGE_SHORT,
    interest_label,
    normalize_language,
    option_label,
    translate,
)

# Debug is opt-in. The safe default has to be the production one: a
# deployment that simply forgets to set anything must not inherit the
# developer's conveniences -- a throwaway secret key, the auto-login
# shortcut, tracebacks rendered into the browser.
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") not in ("0", "false", "no")
IS_PRODUCTION = not FLASK_DEBUG

# Set when production is missing a secret it must supply itself. The app
# still starts -- gunicorn binds the port before forking, so a worker that
# dies on import looks like a successful deploy with every request 503ing
# and the real reason nowhere in sight (the same trap startup() documents).
# Instead every request is refused with the cause, and /healthz reports it.
CONFIG_ERROR = None


def _required_secret(name, dev_fallback):
    """Read a secret that production must set explicitly.

    Falling back is worse than refusing to serve. A generated
    APP_SECRET_KEY means each gunicorn worker signs cookies with a
    different key, so users are logged out at random depending on which
    worker answers -- an outage that looks like a bug in login. A default
    APP_ADMIN_PASSWORD means a publicly reachable administrator account
    whose password is published in this repository.
    """
    global CONFIG_ERROR
    value = os.environ.get(name)
    if value:
        return value
    if IS_PRODUCTION:
        CONFIG_ERROR = (
            f"{name} is not set. It has a fallback for local development only, "
            "which is unsafe in production, so the app is refusing to serve. "
            "Set it, or set FLASK_DEBUG=1 if this really is a dev machine."
        )
        return secrets.token_hex(32)  # never actually used to serve a request
    return dev_fallback


# Flask types static files from the stdlib's table, which is seeded from
# /etc/mime.types -- and the slim runtime image has no entry for .webp, so in
# production the hero still went out as application/octet-stream while it was
# image/webp on a dev box with a fuller mime database. Nothing broke (nosniff
# only enforces the type for scripts and stylesheets, so the image decoder
# sniffs it anyway), but the correct type should not depend on which packages
# the base image happens to carry. State it here instead.
mimetypes.add_type("image/webp", ".webp")

app = Flask(__name__)
# Flask defaults static files to no-cache, which costs a revalidation round
# trip per asset per navigation -- for the wordmark and the search animation
# that is two, on every page. An hour is short enough that replacing an asset
# in place still lands the same day, and these are the only assets not served
# from a content-addressed URL.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
app.secret_key = _required_secret("APP_SECRET_KEY", "dev-only-insecure-key")


@app.before_request
def refuse_when_misconfigured():
    """Fail closed, loudly, on every route but the health check.

    Registered first so it runs before anything else can act on a request.
    """
    if CONFIG_ERROR and request.path not in HEALTH_PATHS:
        return Response(f"Server misconfigured: {CONFIG_ERROR}\n", status=503,
                        mimetype="text/plain")


def database_url():
    """Build the Postgres conninfo from the environment.

    DATABASE_URL wins if set. Otherwise the parts are assembled with
    make_conninfo, which quotes every value. Pasting them into a URL by hand
    does not: a password containing "/" silently swallows the user, the
    dbname and the port, and a base64 password hits that about half the time.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    parts = {
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASS", "postgres"),
        "dbname": os.environ.get("DB_NAME", "velvet"),
    }

    instance = os.environ.get("INSTANCE_CONNECTION_NAME")
    if instance:
        socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
        return make_conninfo(**parts, host=f"{socket_dir}/{instance}")

    return make_conninfo(
        **parts,
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("DB_PORT", "5432"),
    )


# Each instance keeps a deliberately small pool: Cloud Run multiplies it by
# the number of running instances, and that product is what exhausts a
# Cloud SQL instance's connection limit.
POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN", 1))
POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX", 5))

POOL = ConnectionPool(
    conninfo=database_url(),
    min_size=POOL_MIN_SIZE,
    max_size=POOL_MAX_SIZE,
    max_idle=1800,  # recycle idle connections after 30 min
    kwargs={"row_factory": dict_row},
    open=False,
)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = _required_secret("APP_ADMIN_PASSWORD", "admin12345")
# Ignored outside debug: on a public deployment this logs every anonymous
# visitor in as the administrator.
AUTO_LOGIN = (
    os.environ.get("AUTO_LOGIN", "0") not in ("0", "false", "no") and not IS_PRODUCTION
)

# --- sessions -----------------------------------------------------------
SESSION_LIFETIME_DAYS = 30
# How stale last_seen_at may get before it is rewritten. Without this the
# session table takes a write on literally every request.
SESSION_TOUCH_AFTER = timedelta(minutes=5)
# Who may hold a session. 'pending_deletion' is deliberately allowed: the
# grace period is worthless if you cannot log back in to cancel.
LOGIN_ALLOWED_STATUSES = ("active", "pending_deletion")

# --- accounts -----------------------------------------------------------
# NIST SP 800-63B-4 keeps 8 as the floor and recommends more; length is what
# buys security, so there are deliberately no composition rules and no
# forced rotation to go with it.
PASSWORD_MIN_LENGTH = 8
MIN_SIGNUP_AGE = 18
MAX_PLAUSIBLE_AGE = 120
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

VERIFY_TOKEN_HOURS = 48
RESET_TOKEN_HOURS = 1

# SP 800-63B-4 asks for new passwords to be screened against known-breached
# ones. Have I Been Pwned's range API is queried by the first five hex digits
# of the password's SHA-1 and answers with every suffix sharing that prefix,
# so the password -- and even its full hash -- never leaves this process.
HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT_SECONDS = 2.5
# How many appearances in a breach corpus is too many. 1 would reject
# passwords that leaked once in a decade of dumps; the point is to catch the
# ones attackers actually guess first.
HIBP_MAX_APPEARANCES = 10


def breach_count(password):
    """How many times this password appears in HIBP's corpus.

    Returns None when the answer is unknown -- the service is down, slow, or
    unreachable. Callers treat that as "allow": an outage at Have I Been
    Pwned must never become an outage here, and refusing to let someone set
    a password because a third party is unavailable is a worse failure than
    letting one weak password through.
    """
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        resp = requests.get(
            HIBP_RANGE_URL + prefix,
            timeout=HIBP_TIMEOUT_SECONDS,
            headers={"Add-Padding": "true", "User-Agent": "velvt-password-check"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        app.logger.warning("breach screening unavailable: %s", exc)
        return None
    for line in resp.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            try:
                return int(count)
            except ValueError:
                return None
    return 0


def password_problem(password, confirm=None):
    """The one place a new password is judged, so the rules cannot drift
    between registration, reset and change. Returns a message, or None if
    the password is acceptable.

    No composition rules and no rotation, per SP 800-63B-4 -- length and
    "has this one already leaked" are what actually carry.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if confirm is not None and password != confirm:
        return "Passwords do not match."
    seen = breach_count(password)
    if seen is not None and seen > HIBP_MAX_APPEARANCES:
        return ("That password has appeared in a public data breach, so it is "
                "one attackers try first. Please choose a different one.")
    return None

# --- privacy and deletion -----------------------------------------------
# Long enough to undo a decision made in anger, short enough to still be a
# deletion. The account is unreachable to everyone else from the moment it
# is requested either way.
DELETION_GRACE_DAYS = 14

# --- retention -----------------------------------------------------------
# GDPR Article 5(1)(e): personal data is kept no longer than it is needed
# for what it was collected for. Every number here is a decision about what
# "needed" means, written down so it can be argued with rather than left to
# whatever the database happens to still hold.
#
# Enforced by purge_expired_data(), which the same scheduler that finishes
# deletions calls -- see /tasks/purge-deletions.

# An ended match is over: neither side can open it, write to it, or see it.
# The conversation is kept a while because "we matched and it ended" is
# still recent history to the people in it, and because a report filed
# afterwards needs the messages to be judgeable at all.
ENDED_MATCH_RETENTION_DAYS = 90

# A finished search is working state, not history. Cancelled and matched
# rows have already done their job; the pairing they produced lives in
# `matches`. These carry precise coordinates, which is the most sensitive
# thing the app stores.
RESOLVED_SEARCH_RETENTION_DAYS = 7

# A live search keeps its exact lat/lng because distance filtering needs
# them. Once it is old enough that nothing is filtering on it any more,
# the coordinates are rounded to ~1km (2 decimal places) rather than kept
# to the metre. Coarsening beats deleting here: the row stays useful for
# the "where were people searching" question without remaining a record of
# where one identifiable person stood.
COORDINATE_COARSEN_DAYS = 30
COORDINATE_PLACES = 2

# Rate-limit counters are operational data with no reason to outlive their
# own window.
RATE_HIT_RETENTION_DAYS = 2

# Security events record IP addresses, so they cannot be kept indefinitely
# just because they are useful. A quarter is long enough to investigate an
# incident that surfaced weeks after it happened.
AUTH_EVENT_RETENTION_DAYS = 90

# A resolved report is kept longer than the content it describes: it is the
# record of a moderation decision, and the DSA expects those to be
# accountable after the fact.
RESOLVED_REPORT_RETENTION_DAYS = 365

# The GDPR Article 9 consent. Gender plus who you are seeking makes sexual
# orientation inferable, which is special category data and needs explicit
# consent on top of the Article 6 basis.
CONSENT_SENSITIVE = "sensitive_profile"

# Bumped whenever the documents change: acceptance is recorded per version,
# because "they agreed at some point" is not an answer once the text moves.
TERMS_VERSION = "2026-08-15"
PRIVACY_VERSION = "2026-08-15"
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@velvt.example")

# Shared secret for the scheduled-task endpoint. Unset means the endpoint
# refuses to run at all, which is the right default for something that
# permanently erases accounts.
TASK_TOKEN = os.environ.get("TASK_TOKEN", "").strip()

# --- safety -------------------------------------------------------------
# Offered on the report form. Ordered by how urgently a moderator should
# look, not alphabetically -- the top of this list is what gets triaged
# first.
REPORT_REASONS = [
    ("underage", "They appear to be under 18"),
    ("harassment", "Harassment, threats or abuse"),
    ("sexual", "Unwanted sexual content"),
    ("scam", "Scam, spam or asking for money"),
    ("fake", "Fake profile or someone else's photos"),
    ("other", "Something else"),
]
REPORT_REASON_KEYS = {key for key, _ in REPORT_REASONS}

# What a moderator can do with a report, and how it reads back in the log.
ADMIN_ACTIONS = {
    "dismiss": "dismissed, no action taken",
    "warn": "noted, account left active",
    "suspend": "account suspended",
    "ban": "account banned",
}

# --- CSRF ---------------------------------------------------------------
# Hand-rolled on itsdangerous, which Flask already depends on, rather than
# pulling in Flask-WTF and WTForms for one hidden field -- the forms in this
# app are hand-written HTML and there is nothing for WTForms to do.
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_MAX_AGE_SECONDS = 60 * 60 * 12
# Neither caller is a browser with a session: the Cloud Run startup probe,
# and the scheduler that drives the deletion purge (which authenticates with
# a shared secret of its own instead).
# The health check answers on two paths for one reason: Google's frontend
# swallows the literal /healthz before it reaches the container, so that path
# works for Cloud Run's startup probe (which dials the container directly) and
# 404s for anything asking through velvt.nl. /-/health is the same handler on a
# path nothing upstream claims, so external uptime monitoring can see it.
HEALTH_PATHS = ("/healthz", "/-/health")

CSRF_EXEMPT_PATHS = {*HEALTH_PATHS, "/tasks/purge-deletions"}
CSRF_SERIALIZER = URLSafeTimedSerializer(app.secret_key, salt="velvt-csrf")

# --- outbound mail ------------------------------------------------------
# Resend over plain HTTPS through the `requests` dependency the app already
# has, rather than an SDK or an SMTP client -- Cloud Run has no local mail
# transport, and this keeps the dependency list where CLAUDE.md pins it.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "Velvt <onboarding@resend.dev>")
# Where a reply goes. Transactional mail is sent from a noreply address so a
# person cannot start a conversation with the sending system, but people do
# reply to it anyway -- often to ask for help, sometimes to report someone --
# and without this that reply bounces into nothing. Defaults to whatever the
# app already publishes as its point of contact.
MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "").strip()
# Needed to build absolute links in email; falls back to CANONICAL_HOST.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")

app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_LIFETIME_DAYS),
    # Refuse an oversized upload before Werkzeug reads it into memory,
    # rather than after, where PHOTO_MAX_BYTES catches it.
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Keyed to production, not to CANONICAL_HOST: a deployment that has not
    # mapped its domain yet is still served over https and still needs this.
    # Left off in development because a Secure cookie is never sent back
    # over plain http on localhost, which would break login there.
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
)

# The one hostname the app answers on, e.g. "velvt.nl". Every other host that
# reaches us -- www, the *.run.app URL -- is redirected there. Unset means no
# redirect at all, which is what local development and any not-yet-mapped
# deployment want. Sessions are the reason this matters: a cookie set on
# velvt.nl is not sent to www.velvt.nl, so a user who logs in on one host and
# later lands on the other looks logged out.
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().lower()

GENDERS = ["Woman", "Man", "Non-binary"]

# Object pronoun for the reveal's "Ask {pronoun} about X" line, keyed on the
# self-reported profiles.gender value. Anything else (Non-binary, unset)
# reads as "them" -- never guessed from a name, only from what the person
# themselves put on their own profile.
PRONOUNS = {"Woman": "her", "Man": "him"}

SEEKING_OPTIONS = ["Women", "Men", "Non-binary people", "Everyone"]

# Which profile genders each "looking for" choice accepts. Every gender in
# GENDERS is nameable here, so a non-binary searcher is findable by someone
# looking specifically for them rather than only via "Everyone".
SEEKING_MATCHES = {
    "Women": {"Woman"},
    "Men": {"Man"},
    "Non-binary people": {"Non-binary"},
    "Everyone": set(GENDERS),
}

# Coordinates for the cities the search can filter by, so a radius in km
# can be applied without calling out to a geocoding service.
CITY_COORDS = {
    "berlin": (52.520, 13.405),
    "hamburg": (53.551, 9.994),
    "munich": (48.135, 11.582),
    "münchen": (48.135, 11.582),
    "cologne": (50.938, 6.960),
    "köln": (50.938, 6.960),
    "frankfurt": (50.110, 8.682),
    "frankfurt am main": (50.110, 8.682),
    "stuttgart": (48.776, 9.183),
    "düsseldorf": (51.228, 6.773),
    "dusseldorf": (51.228, 6.773),
    "leipzig": (51.340, 12.375),
    "dresden": (51.051, 13.739),
    "hannover": (52.376, 9.732),
    "hanover": (52.376, 9.732),
    "bremen": (53.079, 8.802),
    "nuremberg": (49.452, 11.077),
    "nürnberg": (49.452, 11.077),
    "essen": (51.456, 7.012),
    "dortmund": (51.514, 7.466),
    "vienna": (48.208, 16.373),
    "wien": (48.208, 16.373),
    "zurich": (47.377, 8.542),
    "zürich": (47.377, 8.542),
    "amsterdam": (52.370, 4.895),
    "basel": (47.560, 7.588),
    "salzburg": (47.809, 13.055),
    "maastricht": (50.851, 5.691),
    "rotterdam": (51.924, 4.478),
    "utrecht": (52.092, 5.104),
    "eindhoven": (51.441, 5.478),
    "the hague": (52.070, 4.301),
    "den haag": (52.070, 4.301),
    "groningen": (53.219, 6.567),
    "nijmegen": (51.812, 5.837),
    "arnhem": (51.985, 5.899),
}

# Offered in the location picker, nicely cased.
CITY_CHOICES = [
    "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart",
    "Düsseldorf", "Leipzig", "Dresden", "Hannover", "Bremen", "Nuremberg",
    "Essen", "Dortmund", "Vienna", "Zurich", "Amsterdam", "Basel", "Salzburg",
    "Maastricht", "Rotterdam", "Utrecht", "Eindhoven", "The Hague",
    "Groningen", "Nijmegen", "Arnhem",
]

RADIUS_MAX_KM = 500  # slider maximum; at the top it means "anywhere"

# Velvt is launching in one city, so "where are you?" is not a question anyone
# is asked yet: every profile and every search is pinned here, server-side, no
# matter what a form posts. Asking would be worse than pointless -- it would
# invite someone in Berlin to sign up and search a pool that cannot contain
# anybody.
#
# This is the single switch for that. Set it to None to go multi-city again:
# the location pickers, the wizard's location step, the distance filter and
# /api/places are all still present and wired, just not rendered while a city
# is pinned here. Whatever is named here must exist in CITY_COORDS, or distance
# filtering silently reads as "anywhere" -- hence the assert.
SINGLE_CITY = "Maastricht"

assert SINGLE_CITY is None or SINGLE_CITY.lower() in CITY_COORDS, (
    f"SINGLE_CITY {SINGLE_CITY!r} is missing from CITY_COORDS"
)

AGE_MIN_YEARS, AGE_MAX_YEARS = 18, 39

# How long a search must run before it can be paired. The demo pool is
# always populated, so without this every search resolves on its first
# attempt and the waiting screen never actually shows.
MIN_SEARCH_SECONDS = 7

# Longest single message. Enforced in send_message(), mirrored as maxlength
# on the composer.
MESSAGE_MAX_CHARS = 2000

# How long a search must run with zero fits before the waiting screen offers
# "Search wider". Measured from searches.created_at (like MIN_SEARCH_SECONDS
# above), not a client-side clock -- a page reload must not push the offer
# back, and neither must a filter tweak, since the apply endpoint never
# touches created_at either.
SEARCH_WIDER_SECONDS = 45

# The seeded demo members (seed_demo.py, is_bot=TRUE) auto-reply in chat and
# auto-continue past the decision phase. That is exactly what a local demo
# wants and exactly what a real deployment must never do: a real person would
# spend five minutes talking to a canned script and be told it was a match.
# So bots are out of the pool unless this is switched on, and it is only ever
# switched on locally -- dev.ps1 sets it, production never does.
ALLOW_BOT_MATCHES = os.environ.get("ALLOW_BOT_MATCHES", "0") not in ("0", "false", "no")

# Who is allowed to show up in someone else's search pool. Interpolated into
# both try_pair() and _search_pool() so the matcher and the "why am I not
# matching" preview can never disagree -- if these two drifted, the preview
# would promise a candidate the matcher then refuses to pair you with.
#
# The fragment is built from constants only, never from request data, and it
# assumes the queries it lands in have joined `users` as `u`.
# How long a waiting search stays in the pool without hearing from the
# browser. The waiting screen polls /search/status every few seconds, so a
# minute is many missed ticks -- long enough to ride out a tunnel or a
# backgrounded tab, short enough that a closed laptop stops being offered
# to people as a live person to talk to.
SEARCH_ALIVE_SECONDS = 60


def _candidate_eligible_sql():
    clauses = ["u.status = 'active'"]
    if not ALLOW_BOT_MATCHES:
        clauses.append("u.is_bot = FALSE")
    # Demo members have no browser to poll with, so they would go stale
    # within the minute and make local testing impossible. The exemption is
    # dead weight in production, where the is_bot clause above has already
    # removed them.
    clauses.append(
        "(u.is_bot = TRUE OR s.last_seen > NOW() - "
        f"({SEARCH_ALIVE_SECONDS} * INTERVAL '1 second'))"
    )
    return "".join(f" AND {c}" for c in clauses)


CANDIDATE_ELIGIBLE_SQL = _candidate_eligible_sql()

# Excludes anyone either side has blocked. Kept separate from the fragment
# above because it needs the viewer's id as a parameter, and because the
# landing page's anonymous count has no viewer to exclude against.
#
# Symmetric on purpose: one block hides both people from each other, so
# being blocked never reveals who did it.
NOT_BLOCKED_SQL = """
  AND NOT EXISTS (
      SELECT 1 FROM blocks b
      WHERE (b.blocker_id = ? AND b.blocked_id = s.user_id)
         OR (b.blocker_id = s.user_id AND b.blocked_id = ?)
  )
"""

# --- match lifecycle (live-search pairings only; /find stays instant) -----
REVEAL_SECONDS = 20          # "it's a match" card before the chat opens
TIMED_CHAT_SECONDS = 300     # 5 minutes to talk before a decision is forced
DECISION_GRACE_SECONDS = 86400  # no answer within a day counts as unmatch

# --- photos -----------------------------------------------------------
PHOTO_MAX_BYTES = 2 * 1024 * 1024
PHOTO_MAX_PER_USER = 6
PHOTO_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}


def sniff_image_mime(data):
    """Identify an image by its magic bytes, never by the browser-supplied
    Content-Type header — that header is client-controlled and trivially
    spoofed. SVG is deliberately not supported: it can carry script that
    would execute on this origin when served back."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_blocked_between(a_id, b_id):
    """True if either has blocked the other.

    Symmetric by design: a block hides both people from each other, so the
    blocked party is never handed the information that they were blocked.
    """
    if a_id == b_id:
        return False
    return get_db().execute(
        """
        SELECT 1 AS hit FROM blocks
        WHERE (blocker_id = ? AND blocked_id = ?)
           OR (blocker_id = ? AND blocked_id = ?)
        LIMIT 1
        """,
        (a_id, b_id, b_id, a_id),
    ).fetchone() is not None


def can_view_photos(owner_id, viewer_id, viewer_is_admin):
    """Photos unlock only once both sides have pressed Continue — i.e. a
    matches row exists between the two with status='active'. That is
    exactly the same state resolve_match() writes, so this needs no
    bookkeeping of its own."""
    if viewer_id == owner_id:
        return True
    if is_blocked_between(owner_id, viewer_id):
        # Checked before the admin bypass would be wrong -- an admin
        # reviewing a report needs to see what was reported.
        if not viewer_is_admin:
            return False
    if viewer_is_admin:
        return True
    a, b = sorted((owner_id, viewer_id))
    row = get_db().execute(
        "SELECT status FROM matches WHERE user_a = ? AND user_b = ?", (a, b)
    ).fetchone()
    return row is not None and row["status"] == "active"


# --- profile auto-fill (random sample values, no API) ------------------
SAMPLE_NAMES = ["Alex", "Sam", "Jordan", "Robin", "Casey", "Morgan", "Taylor", "Rowan"]
SAMPLE_BIOS = [
    "Coffee enthusiast who's always planning the next trip.",
    "Enjoys long walks, good food, and even better conversation.",
    "Spends most weekends outdoors, the rest catching up on films.",
    "Firm believer that a good playlist fixes most problems.",
]
SAMPLE_INTERESTS = [
    "music, travel, cooking", "hiking, photography, films", "yoga, reading, coffee",
    "gaming, cycling, cooking",
]
SAMPLE_HOBBIES = [
    "salsa dancing, yoga", "guitar, running", "sailing, painting", "climbing, chess",
]

RELATIONSHIP_TYPES = [
    "Long-term relationship",
    "Short-term relationship",
    "Friendship",
    "Not sure yet",
]

# Self-descriptive, like body_type or hair_color -- shown on the profile,
# not a live-search filter. Kept separate from RELATIONSHIP_TYPES (which is
# "what kind of connection", CSV, and feeds matching) because monogamous vs.
# polyamorous is a different axis a searcher isn't filtered on today.
RELATIONSHIP_PREFERENCES = [
    "Monogamous",
    "Polyamorous",
    "Open relationship",
    "Not sure yet",
]

# Fallback reveal copy when two searches share no interest keyword -- the
# thing that's always true instead: they're both looking for the same
# relationship_type. Keyed on RELATIONSHIP_TYPES values.
RELATIONSHIP_REASON_PHRASES = {
    "Long-term relationship": "something long-term",
    "Short-term relationship": "something short-term",
    "Friendship": "the same thing -- friendship",
    "Not sure yet": "the same thing, even if neither of you is sure yet",
}


def clean_relationship_types(raw):
    """Validate and normalise a relationship_type CSV: every part must be a
    real RELATIONSHIP_TYPES value, order preserved, duplicates dropped.
    Invalid parts are silently dropped rather than rejecting the whole
    value, the same posture clean_interests() takes -- one bad entry in a
    hand-built request shouldn't cost the valid ones next to it. Empty (or
    entirely invalid) input returns "".
    """
    seen = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part in RELATIONSHIP_TYPES and part not in seen:
            seen.append(part)
    return ",".join(seen)


BODY_TYPES = ["Slim", "Athletic", "Average", "Curvy", "Muscular", "Plus-size"]
FITNESS_LEVELS = ["Sedentary", "Lightly active", "Active", "Very active", "Athlete"]
HAIR_COLORS = ["Black", "Brown", "Blonde", "Red", "Grey/White", "Other"]
EYE_COLORS = ["Brown", "Blue", "Green", "Hazel", "Grey", "Other"]
TATTOO_LEVELS = ["None", "A few", "Many"]
HEIGHT_MIN_CM, HEIGHT_MAX_CM = 130, 230

PROFILE_FIELDS = [
    "name",
    "age",
    "gender",
    "seeking",
    "location",
    "height_cm",
    "body_type",
    "fitness_level",
    "hair_color",
    "eye_color",
    "tattoos",
    "bio",
    "interests",
    "hobbies",
    "relationship_type",
    "relationship_preference",
]
# Used by the search wizard's step-3 physical filters (searches.pref_body_types),
# a checkbox group that arrives as repeated fields rather than one value, so it
# doesn't fit the uniform .get() loop those routes build from.
PREF_BODY_TYPES_FIELD = "pref_body_types"


def sample_profile_data():
    """Vocabulary for the profile-edit "Fill" buttons.

    Picked client-side (see profile_edit.html) so a click is instant and
    needs no round trip. Built entirely from constants that already exist
    for the real form, plus the short SAMPLE_* sentence lists above, so
    there is nothing here to keep in sync by hand.
    """
    return {
        "name": SAMPLE_NAMES,
        "age": {"min": AGE_MIN_YEARS, "max": AGE_MAX_YEARS},
        "gender": GENDERS,
        "seeking": SEEKING_OPTIONS,
        "location": CITY_CHOICES,
        "bio": SAMPLE_BIOS,
        "interests": SAMPLE_INTERESTS,
        "hobbies": SAMPLE_HOBBIES,
        "relationship_type": RELATIONSHIP_TYPES,
        "relationship_preference": RELATIONSHIP_PREFERENCES,
        "height_cm": {"min": HEIGHT_MIN_CM, "max": HEIGHT_MAX_CM},
        "body_type": BODY_TYPES,
        "fitness_level": FITNESS_LEVELS,
        "hair_color": HAIR_COLORS,
        "eye_color": EYE_COLORS,
        "tattoos": TATTOO_LEVELS,
    }


class Db:
    """Thin wrapper giving a psycopg connection the shape this file expects.

    Call sites keep using `?` placeholders and
    `db.execute(...).fetchone()`. Postgres wants `%s`, so placeholders are
    rewritten here — safe because no query in this file contains a literal
    `?` or `%`. Rows come back as dicts, so both `row["col"]` and
    `dict(row)` behave as they did with `sqlite3.Row`.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def insert_returning_id(self, sql, params=()):
        """Postgres has no lastrowid; ask the INSERT for the new id."""
        return self.execute(sql + " RETURNING id", params).fetchone()["id"]

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def get_db():
    if "db" not in g:
        g.db_conn = POOL.getconn()
        g.db = Db(g.db_conn)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db_conn", None)
    g.pop("db", None)
    if conn is not None:
        # Never hand a connection back mid-transaction.
        if exc is not None:
            conn.rollback()
        POOL.putconn(conn)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    -- Seeded demo members that auto-reply in chat (see seed_demo.py). Never
    -- set by user-facing code.
    is_bot BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_bot BOOLEAN NOT NULL DEFAULT FALSE;

-- Case-insensitive uniqueness, the equivalent of SQLite's COLLATE NOCASE.
-- An expression index rather than the citext extension, so no database
-- privileges beyond CREATE are needed.
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx
    ON users (LOWER(username));

CREATE TABLE IF NOT EXISTS profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    age INTEGER,
    gender TEXT NOT NULL DEFAULT '',
    seeking TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    height_cm INTEGER,
    body_type TEXT NOT NULL DEFAULT '',
    fitness_level TEXT NOT NULL DEFAULT '',
    hair_color TEXT NOT NULL DEFAULT '',
    eye_color TEXT NOT NULL DEFAULT '',
    tattoos TEXT NOT NULL DEFAULT '',
    pref_height_min INTEGER,
    pref_height_max INTEGER,
    pref_body_types TEXT NOT NULL DEFAULT '',
    pref_fitness_level TEXT NOT NULL DEFAULT '',
    pref_hair_color TEXT NOT NULL DEFAULT '',
    pref_eye_color TEXT NOT NULL DEFAULT '',
    pref_tattoos TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    hobbies TEXT NOT NULL DEFAULT '',
    wants TEXT NOT NULL DEFAULT '',
    needs TEXT NOT NULL DEFAULT '',
    relationship_type TEXT NOT NULL DEFAULT '',
    relationship_preference TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bring databases created before the physical/preference columns existed
-- up to date. Postgres has ADD COLUMN IF NOT EXISTS, so this is idempotent
-- without the try/except loop the SQLite version needed.
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS height_cm INTEGER;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS body_type TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS fitness_level TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS hair_color TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS eye_color TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS tattoos TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_height_min INTEGER;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_height_max INTEGER;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_body_types TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_fitness_level TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_hair_color TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_eye_color TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pref_tattoos TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS relationship_preference TEXT NOT NULL DEFAULT '';

-- status default is 'active' so every pre-existing row (and every future
-- /find "Match & chat" row, which never goes through try_pair) behaves as a
-- permanent chat exactly as before. Only try_pair() writes 'timed'.
CREATE TABLE IF NOT EXISTS matches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_a BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    paired_at TIMESTAMPTZ,
    decision_a TEXT NOT NULL DEFAULT '',
    decision_b TEXT NOT NULL DEFAULT '',
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_a, user_b),
    CHECK (user_a < user_b)
);

ALTER TABLE matches ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE matches ADD COLUMN IF NOT EXISTS paired_at TIMESTAMPTZ;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS decision_a TEXT NOT NULL DEFAULT '';
ALTER TABLE matches ADD COLUMN IF NOT EXISTS decision_b TEXT NOT NULL DEFAULT '';
ALTER TABLE matches ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
-- Read receipts: the highest messages.id each side has had the room open
-- for. A single counter per side rather than a per-message table, since
-- "read" only ever moves forward and only the high-water mark is ever
-- shown (a single vs. double check on the sender's own bubbles).
ALTER TABLE matches ADD COLUMN IF NOT EXISTS read_a BIGINT NOT NULL DEFAULT 0;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS read_b BIGINT NOT NULL DEFAULT 0;

-- One row per member currently looking for a live match.
CREATE TABLE IF NOT EXISTS searches (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    seeking TEXT NOT NULL DEFAULT '',
    age_min INTEGER NOT NULL DEFAULT 18,
    age_max INTEGER NOT NULL DEFAULT 39,
    relationship_type TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    radius_km INTEGER NOT NULL DEFAULT 500,
    pref_height_min INTEGER,
    pref_height_max INTEGER,
    pref_body_types TEXT NOT NULL DEFAULT '',
    pref_fitness_level TEXT NOT NULL DEFAULT '',
    pref_hair_color TEXT NOT NULL DEFAULT '',
    pref_eye_color TEXT NOT NULL DEFAULT '',
    pref_tattoos TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'waiting',
    match_id BIGINT REFERENCES matches(id) ON DELETE SET NULL,
    -- Each filter can be switched off without losing the value behind it, so
    -- a searcher can widen their net and put it back afterwards. These govern
    -- only this searcher's own side of the check: the other person's filters
    -- still apply, which is why turning one off does not guarantee a match.
    use_gender BOOLEAN NOT NULL DEFAULT TRUE,
    use_age BOOLEAN NOT NULL DEFAULT TRUE,
    use_relationship BOOLEAN NOT NULL DEFAULT TRUE,
    use_distance BOOLEAN NOT NULL DEFAULT TRUE,
    use_physical BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Last sign of life from the waiting page. created_at cannot stand in
    -- for this: a searcher who closes the tab leaves a row that still says
    -- 'waiting' forever, and pairing with it produces a five-minute room
    -- with nobody in it. The waiting screen already polls, so every poll
    -- rewrites this and going quiet is what drops you out of the pool.
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bring databases created before the per-filter toggles existed up to date.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_gender BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_age BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_relationship BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_distance BOOLEAN NOT NULL DEFAULT TRUE;
-- The physical block is one switch rather than one per trait: it hides or shows
-- a whole panel in the UI, and DEFAULT TRUE keeps every pre-existing row filtering
-- exactly as it did before the switch existed.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_physical BOOLEAN NOT NULL DEFAULT TRUE;
-- Pre-heartbeat rows default to NOW(), which grants them one grace window
-- rather than dropping every live searcher out of the pool at deploy time.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS searches_waiting_idx ON searches (status, last_seen);

-- Bring searches created before the physical-trait step existed up to date.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_height_min INTEGER;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_height_max INTEGER;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_body_types TEXT NOT NULL DEFAULT '';
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_fitness_level TEXT NOT NULL DEFAULT '';
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_hair_color TEXT NOT NULL DEFAULT '';
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_eye_color TEXT NOT NULL DEFAULT '';
ALTER TABLE searches ADD COLUMN IF NOT EXISTS pref_tattoos TEXT NOT NULL DEFAULT '';

-- Coordinates from the /api/places geocoder, used ahead of the CITY_COORDS
-- fallback so distance filtering works for any city, not just the seeded
-- list. Nullable: a free-typed or unrecognised location leaves these unset.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION;

-- The pairing pass scans waiting searchers.
CREATE INDEX IF NOT EXISTS searches_status_idx ON searches (status);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    sender_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Serves the chat poll: "messages in this room newer than <id>".
CREATE INDEX IF NOT EXISTS messages_match_id_idx ON messages (match_id, id);

-- A deleted account must not take the other person's conversation with it.
-- sender_id becomes nullable and detaches on delete instead of cascading,
-- so the surviving participant keeps a readable history rather than a chat
-- full of holes. Everything identifying the deleted account still goes.
ALTER TABLE messages ALTER COLUMN sender_id DROP NOT NULL;
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_sender_id_fkey;
ALTER TABLE messages ADD CONSTRAINT messages_sender_id_fkey
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE SET NULL;

-- Photos are stored as bytes so they survive Cloud Run's ephemeral disk
-- with no bucket, and so visibility can be a plain SQL check on the
-- serving route (see /photo/<id>) rather than a static URL that bypasses
-- auth entirely.
CREATE TABLE IF NOT EXISTS photos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    data BYTEA NOT NULL,
    mime TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The order the edit screen's tiles were dragged into. is_primary still
-- outranks it: the main photo leads whatever the drag order says, so
-- every read is `ORDER BY is_primary DESC, sort_order, id`.
ALTER TABLE photos ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS photos_user_id_idx ON photos (user_id, is_primary);

-- --- accounts -----------------------------------------------------------
-- An account used to be a username and a password and nothing else, which
-- made a forgotten password unrecoverable: there was no address to send a
-- reset to and no way to prove the account was yours. Everything below is
-- nullable so existing rows survive the migration; the app requires the new
-- fields at registration, not at the column level.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
-- Date of birth, not age: an age is wrong within a year of storing it, and
-- the 18+ gate has to keep holding after the account is created.
ALTER TABLE users ADD COLUMN IF NOT EXISTS dob DATE;
-- Reserved for a real age-assurance check (the EU age-verification app, due
-- for rollout by the end of 2026). Unused for now, so wiring one in later
-- does not need a migration.
ALTER TABLE users ADD COLUMN IF NOT EXISTS age_verified_at TIMESTAMPTZ;
-- 'active' | 'suspended' | 'banned' | 'pending_deletion'. Checked on every
-- request via current_user(), so a suspension takes effect mid-session
-- rather than at the suspended user's next login.
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ;
-- Set the first time the "how a match works" screen is acknowledged. On the
-- account rather than in the session, so it does not reappear on a second
-- device -- and nullable rather than a boolean, because when someone was
-- told is the useful thing to know later.
ALTER TABLE users ADD COLUMN IF NOT EXISTS match_intro_seen_at TIMESTAMPTZ;

-- Case-insensitive, and partial so the pre-existing rows with no address at
-- all do not collide with each other on NULL.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx
    ON users (LOWER(email)) WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS users_status_idx ON users (status);

-- --- sessions -----------------------------------------------------------
-- Login used to live entirely in the signed cookie, which meant a session
-- could never be revoked: no "sign out my other devices", and no remedy for
-- a stolen phone short of rotating APP_SECRET_KEY and logging out everyone.
-- The cookie now carries an opaque token and this table is the authority.
--
-- Only the token's SHA-256 lands here. A database leak must not hand over a
-- set of live sessions.
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    user_agent TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);

-- --- email tokens -------------------------------------------------------
-- Address verification and password reset. Hashed for the same reason as
-- sessions: a leaked table must not be a set of working reset links.
-- purpose is 'verify' or 'reset'; used_at makes each token single-use.
CREATE TABLE IF NOT EXISTS email_tokens (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS email_tokens_user_idx ON email_tokens (user_id, purpose);

-- --- blocks -------------------------------------------------------------
-- Directional: blocker_id no longer wants anything to do with blocked_id.
-- Every check is "is there a row either way round", so one block hides both
-- people from each other -- being blocked should not tell you who did it.
CREATE TABLE IF NOT EXISTS blocks (
    blocker_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (blocker_id, blocked_id),
    CHECK (blocker_id <> blocked_id)
);

CREATE INDEX IF NOT EXISTS blocks_blocked_idx ON blocks (blocked_id);

-- --- reports ------------------------------------------------------------
-- DSA Article 16 requires every hosting provider serving the EU to run a
-- notice-and-action mechanism and to tell the reporter what came of it. The
-- micro-enterprise exemption covers internal complaint handling and trusted
-- flaggers; it does not cover this.
--
-- match_id and message_id are optional context: a report can be about a
-- whole profile, or about one specific thing that was said.
CREATE TABLE IF NOT EXISTS reports (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reporter_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    reported_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id BIGINT REFERENCES matches(id) ON DELETE SET NULL,
    message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    resolution TEXT NOT NULL DEFAULT '',
    resolution_note TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS reports_status_idx ON reports (status, created_at DESC);
CREATE INDEX IF NOT EXISTS reports_reported_idx ON reports (reported_id);

-- --- moderation log -----------------------------------------------------
-- Who did what to whom and why. Needed to answer "what happened" after an
-- incident, and to keep an admin accountable for their own actions.
CREATE TABLE IF NOT EXISTS admin_actions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    target_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- --- consent and terms --------------------------------------------------
-- Which *version* was accepted, not merely that something once was: "they
-- agreed at some point" is not an answer when the document has changed.
CREATE TABLE IF NOT EXISTS legal_acceptances (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document TEXT NOT NULL,
    version TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, document, version)
);

-- GDPR Article 9. A profile carrying gender and who you are seeking makes
-- sexual orientation inferable, which is special category data: it needs an
-- Article 9 exception (explicit consent) on top of an Article 6 basis, and
-- withdrawal has to be as easy as granting -- hence withdrawn_at rather
-- than deleting the row.
CREATE TABLE IF NOT EXISTS consents (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    withdrawn_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, purpose)
);

-- --- rate limiting ------------------------------------------------------
-- Backed by Postgres rather than process memory on purpose: Cloud Run runs
-- many instances against one database, so an in-process counter would let
-- an attacker have N times the budget by spreading requests across them.
-- --- security events -----------------------------------------------------
-- Written as well as logged. Logs answer "what happened" for a person
-- reading them; this table is what the app itself can query, which is what
-- makes spike detection possible at all.
--
-- It holds an IP address, which is personal data, so it is on the retention
-- schedule like everything else -- see AUTH_EVENT_RETENTION_DAYS.
CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind TEXT NOT NULL,
    outcome TEXT NOT NULL,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    ip TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS security_events_at_idx ON security_events (kind, at DESC);

CREATE TABLE IF NOT EXISTS rate_hits (
    bucket_key TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);

CREATE INDEX IF NOT EXISTS rate_hits_window_idx ON rate_hits (window_start);
"""

# Arbitrary but fixed keys for Postgres advisory locks. Any instance taking
# the same key blocks the others, which is what replaces the in-process
# locks this app used when it could only run as a single process.
INIT_LOCK_KEY = 8_474_021
PAIRING_LOCK_KEY = 8_474_022


def init_db():
    """Create the schema and ensure the admin account exists.

    Every instance runs this at boot, so it is wrapped in an advisory lock:
    concurrent `CREATE TABLE IF NOT EXISTS` from several instances can
    otherwise deadlock against each other.
    """
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (INIT_LOCK_KEY,))
            cur.execute(SCHEMA)

            cur.execute(
                "SELECT id FROM users WHERE LOWER(username) = LOWER(%s)",
                (ADMIN_USERNAME,),
            )
            admin = cur.fetchone()
            if admin is None:
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, is_admin)
                    VALUES (%s, %s, TRUE) RETURNING id
                    """,
                    (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
                )
                admin_id = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO profiles (user_id, name) VALUES (%s, 'Site Admin')",
                    (admin_id,),
                )
            else:
                cur.execute(
                    "UPDATE users SET is_admin = TRUE WHERE id = %s", (admin["id"],)
                )


# How many failed logins across the whole service, within this window,
# constitute a spike worth waking someone for. Tuned to be quiet: a handful
# of people mistyping a password is a Tuesday, not an attack.
LOGIN_FAILURE_SPIKE = 30
LOGIN_FAILURE_WINDOW_MINUTES = 10
# Once a spike is called, stay quiet for this long rather than repeating the
# alert on every subsequent failure -- an alert that fires 400 times is an
# alert nobody reads.
SPIKE_ALERT_COOLDOWN_MINUTES = 30


def security_event(kind, outcome, user_id=None, detail=None, ip=None):
    """Record something worth being able to reconstruct later.

    Written to the database *and* logged as a single JSON object, which is
    what Cloud Logging picks up as a structured payload -- so these are
    filterable by field rather than by grepping a sentence.

    Deliberately swallows its own failures. This is instrumentation: an
    audit trail that can take a request down with it makes the service less
    reliable and no more accountable.
    """
    if ip is None:
        ip = request.remote_addr if request else None
    try:
        db = get_db()
        db.execute(
            """INSERT INTO security_events (kind, outcome, user_id, ip, detail)
               VALUES (?, ?, ?, ?, ?)""",
            (kind, outcome, user_id, ip, detail),
        )
        db.commit()
    except Exception:
        app.logger.exception("could not record security event %s/%s", kind, outcome)

    payload = {"event": kind, "outcome": outcome, "user_id": user_id,
               "ip": ip, "detail": detail}
    app.logger.info(json.dumps({k: v for k, v in payload.items() if v is not None}))

    if kind == "login" and outcome == "failure":
        check_login_failure_spike()


def check_login_failure_spike():
    """Alert once when failed logins spike, then stay quiet for a while.

    Counted service-wide rather than per-IP on purpose: the rate limiter
    already handles one address hammering one account, and the pattern it
    cannot see is the one worth waking up for -- many addresses trying many
    accounts, each below the per-IP limit.
    """
    try:
        db = get_db()
        recent = db.execute(
            """SELECT COUNT(*) AS n FROM security_events
               WHERE kind = 'login' AND outcome = 'failure'
                 AND at > NOW() - (? * INTERVAL '1 minute')""",
            (LOGIN_FAILURE_WINDOW_MINUTES,),
        ).fetchone()["n"]
        if recent < LOGIN_FAILURE_SPIKE:
            return
        alerted = db.execute(
            """SELECT 1 AS hit FROM security_events
               WHERE kind = 'login_failure_spike'
                 AND at > NOW() - (? * INTERVAL '1 minute') LIMIT 1""",
            (SPIKE_ALERT_COOLDOWN_MINUTES,),
        ).fetchone()
        if alerted:
            return
        db.execute(
            """INSERT INTO security_events (kind, outcome, detail)
               VALUES ('login_failure_spike', 'alert', ?)""",
            (f"{recent} failed logins in {LOGIN_FAILURE_WINDOW_MINUTES} minutes",),
        )
        db.commit()
        app.logger.error(json.dumps({
            "event": "login_failure_spike",
            "outcome": "alert",
            "severity": "CRITICAL",
            "failures": recent,
            "window_minutes": LOGIN_FAILURE_WINDOW_MINUTES,
        }))
    except Exception:
        app.logger.exception("spike check failed")


def rate_limit_hit(bucket, limit, window_seconds):
    """Count one hit against `bucket`. True when it is over the limit.

    A fixed window rounded down to `window_seconds`, counted in Postgres
    rather than in process memory: Cloud Run runs several instances against
    one database, so an in-process counter would hand an attacker the whole
    budget again for every instance they happened to land on.

    Fixed windows let through up to 2x the limit across a boundary. That is
    a fine trade here -- this exists to stop credential stuffing and mail
    floods, not to meter an API to the request.
    """
    db = get_db()
    row = db.execute(
        """
        INSERT INTO rate_hits (bucket_key, window_start, hits)
        VALUES (?, to_timestamp(floor(extract(epoch FROM NOW()) / ?) * ?), 1)
        ON CONFLICT (bucket_key, window_start)
        DO UPDATE SET hits = rate_hits.hits + 1
        RETURNING hits
        """,
        (bucket, window_seconds, window_seconds),
    ).fetchone()
    db.commit()
    return row["hits"] > limit


def rate_limited(name, limit, window_seconds, by="ip", include_safe=False):
    """Refuse a route once it has been called too often.

    `by` picks what shares a budget: "ip" for anything a logged-out caller
    can reach, "user" for anything behind a login.

    GET is free unless `include_safe`. These decorators sit on routes that
    answer both methods, and the thing worth limiting is the *attempt* --
    counting page views would lock someone out of the login screen for
    reloading it, which is the opposite of the point. Routes that do their
    work on GET (the geocoder proxy) opt in.
    """
    from functools import wraps

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not include_safe and request.method in ("GET", "HEAD", "OPTIONS"):
                return view(*args, **kwargs)
            if by == "user":
                who = f"u{current_uid()}"
            else:
                who = request.remote_addr or "unknown"
            if rate_limit_hit(f"{name}:{who}", limit, window_seconds):
                app.logger.warning("rate limit %s hit by %s", name, who)
                security_event("rate_limit", "throttled", detail=f"{name} by {who}")
                retry = window_seconds
                if "application/json" in request.headers.get("Accept", ""):
                    return (
                        {"error": "Too many requests. Please wait a moment."},
                        429,
                        {"Retry-After": str(retry)},
                    )
                return (
                    render_template("rate_limited.html", seconds=retry),
                    429,
                    {"Retry-After": str(retry)},
                )
            return view(*args, **kwargs)

        return wrapped

    return decorator


def csrf_token():
    """The caller's CSRF token, minted on first use and stable per session.

    A signed wrapper around a nonce held in the session cookie: the
    signature proves we issued it, and comparing it back against the
    session's own nonce proves it belongs to *this* session rather than one
    the attacker minted for themselves.
    """
    nonce = session.get("csrf_nonce")
    if not nonce:
        nonce = secrets.token_urlsafe(16)
        session["csrf_nonce"] = nonce
    return CSRF_SERIALIZER.dumps(nonce)


def csrf_valid(supplied):
    nonce = session.get("csrf_nonce")
    if not nonce or not supplied:
        return False
    try:
        unsigned = CSRF_SERIALIZER.loads(supplied, max_age=CSRF_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return secrets.compare_digest(unsigned, nonce)


def valid_email(value):
    """Loose on purpose: the only real proof an address works is mail sent
    to it, which is what the verification step is for. This just rejects
    the obviously-not-an-address."""
    return bool(EMAIL_RE.match(value)) and len(value) <= 254


def parse_dob(raw):
    """Parse the <input type="date"> value, or None if it isn't a real date."""
    try:
        return dt.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def age_on(dob, today=None):
    """Whole years old, counting birthdays rather than dividing by 365.25."""
    today = today or date.today()
    if dob > today:
        return None
    had_birthday = (today.month, today.day) >= (dob.month, dob.day)
    return today.year - dob.year - (0 if had_birthday else 1)


def app_url(path):
    """An absolute URL for a link in an email.

    APP_BASE_URL wins, then the canonical host. request.host_url is the last
    resort and only sound in development: in production the Host header is
    attacker-controlled, and a reset link built from it would point wherever
    the sender liked.
    """
    base = APP_BASE_URL or (f"https://{CANONICAL_HOST}" if CANONICAL_HOST else "")
    if not base:
        base = request.host_url.rstrip("/")
    return f"{base}{path}"


def send_email(to, subject, html):
    """Send one transactional email. Returns True if it was accepted.

    Never raises. A mail provider having a bad afternoon must not turn
    registration into a 500 -- the account is already created by then, and
    the user can ask for another link.
    """
    if not RESEND_API_KEY:
        app.logger.warning("RESEND_API_KEY unset — not sending %r to %s", subject, to)
        if not IS_PRODUCTION:
            # So the verification and reset links are usable locally.
            app.logger.warning("would have sent:\n%s", html)
        return False

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": MAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
                # SUPPORT_EMAIL is the published point of contact, so it is the
                # honest fallback: a reply reaches the same humans the imprint
                # promises. Omitted entirely if neither is configured, rather
                # than pointing replies at a placeholder.
                **({"reply_to": MAIL_REPLY_TO or SUPPORT_EMAIL}
                   if (MAIL_REPLY_TO or SUPPORT_EMAIL) else {}),
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        app.logger.error("could not reach the mail provider: %s", exc)
        return False

    if resp.status_code >= 400:
        app.logger.error(
            "mail provider rejected a send: %s %s", resp.status_code, resp.text[:300]
        )
        return False
    return True


def issue_email_token(user_id, purpose, hours):
    """Mint a single-use token and invalidate any earlier one of its kind."""
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute(
        """
        UPDATE email_tokens SET used_at = NOW()
        WHERE user_id = ? AND purpose = ? AND used_at IS NULL
        """,
        (user_id, purpose),
    )
    db.execute(
        """
        INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at)
        VALUES (?, ?, ?, NOW() + (? * INTERVAL '1 hour'))
        """,
        (user_id, purpose, hash_token(token), hours),
    )
    db.commit()
    return token


def consume_email_token(token, purpose, peek=False):
    """Return the token's user id, spending it unless `peek`.

    The reset form needs to check the token twice -- once to decide whether
    to render the form at all, once when the new password is submitted --
    and burning it on the GET would break the POST that follows.
    """
    if not token:
        return None
    db = get_db()
    row = db.execute(
        """
        SELECT id, user_id FROM email_tokens
        WHERE token_hash = ? AND purpose = ?
          AND used_at IS NULL AND expires_at > NOW()
        """,
        (hash_token(token), purpose),
    ).fetchone()
    if row is None:
        return None
    if not peek:
        db.execute("UPDATE email_tokens SET used_at = NOW() WHERE id = ?", (row["id"],))
        db.commit()
    return row["user_id"]


def send_verification_email(user_id, email):
    token = issue_email_token(user_id, "verify", VERIFY_TOKEN_HOURS)
    link = app_url(url_for("verify_email", token=token))
    return send_email(
        email,
        "Confirm your Velvt address",
        f"""<p>Welcome to Velvt.</p>
            <p><a href="{link}">Confirm this address</a> to start searching.</p>
            <p>The link expires in {VERIFY_TOKEN_HOURS} hours.</p>""",
    )


def hash_token(token):
    """Store only this, never the token itself.

    A leaked `sessions` or `email_tokens` table must not be a set of working
    logins and reset links.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(user_id, remember=True):
    """Log `user_id` in: mint a session row and hand the cookie its token.

    The cookie carries an opaque token; this table is the authority. That is
    the whole point -- a signed cookie alone can never be revoked, so a
    stolen phone or a leaked key had no remedy short of rotating
    APP_SECRET_KEY and logging out every user at once.
    """
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute(
        """
        INSERT INTO sessions (user_id, token_hash, user_agent, ip, expires_at)
        VALUES (?, ?, ?, ?, NOW() + (? * INTERVAL '1 day'))
        """,
        (
            user_id,
            hash_token(token),
            (request.headers.get("User-Agent") or "")[:300],
            request.remote_addr or "",
            SESSION_LIFETIME_DAYS,
        ),
    )
    db.commit()

    reset_session_keeping_language()
    session["sid"] = token
    # Unchecked "keep me signed in" leaves a browser-session cookie, which is
    # what someone on a shared machine is asking for.
    session.permanent = bool(remember)
    g.current_user = None  # force a re-resolve on the next current_user()
    return token


LANG_SESSION_KEY = "lang"


def current_language():
    """The language to render this request in.

    An explicit choice wins and is remembered in the session. Failing that,
    the browser's own Accept-Language is honoured, so a Dutch speaker's first
    visit is already Dutch without touching the switcher. Failing that,
    English.
    """
    chosen = normalize_language(session.get(LANG_SESSION_KEY))
    if chosen:
        return chosen
    # Werkzeug does the quality-value parsing; we only offer what we have.
    guessed = request.accept_languages.best_match(LANGUAGE_CODES)
    return normalize_language(guessed) or DEFAULT_LANGUAGE


def t(key, **kwargs):
    """Translate inside a request, for copy the server produces itself --
    flash messages and validation errors. Templates get their own `t` from
    the context processor; this is the Python-side twin."""
    return translate(current_language(), key, **kwargs)


def opt_label_for(value):
    """Display label for a stored option value, server-side.

    The stored value stays canonical English (see translations.py) because
    searches_compatible() compares it as a string; this is only for text a
    human reads.
    """
    return option_label(current_language(), value)


def reset_session_keeping_language():
    """Clear the session but carry the chosen language across.

    session.clear() on sign-in and sign-out is deliberate -- it defends
    against session fixation, and nothing from the previous visitor should
    survive. The language is the one exception: it is a display preference
    rather than anything privileged, and dropping it sent someone who had
    just picked Dutch back to English at exactly the moment they committed.
    """
    chosen = session.get(LANG_SESSION_KEY)
    session.clear()
    if chosen:
        session[LANG_SESSION_KEY] = chosen


def end_session():
    """Log out just this device."""
    token = session.get("sid")
    if token:
        db = get_db()
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        db.commit()
    # Language survives sign-out too: the sign-in page you land on should not
    # suddenly be in a language you did not choose.
    reset_session_keeping_language()
    g.current_user = None


def revoke_user_sessions(user_id, except_token=None):
    """Log a user out everywhere. Used on password change and reset.

    `except_token` keeps the caller's own session alive, so changing your
    password does not immediately log you out of the tab you did it in.
    """
    db = get_db()
    if except_token:
        db.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, hash_token(except_token)),
        )
    else:
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.commit()


def _resolve_session_user():
    """Look up the caller from the session cookie. Read-only."""
    token = session.get("sid")
    if not token:
        return None
    return get_db().execute(
        """
        SELECT u.*, s.id AS session_id, s.last_seen_at AS session_last_seen
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > NOW()
        """,
        (hash_token(token),),
    ).fetchone()


def current_user():
    """The logged-in user row, or None.

    Resolved once per request by load_current_user() and cached on `g`: the
    context processor calls this on every rendered page, and it is now a
    join rather than a primary-key lookup.
    """
    if "current_user" in g and g.current_user is not None:
        return g.current_user
    user = _resolve_session_user()
    if user is not None and user["status"] not in LOGIN_ALLOWED_STATUSES:
        user = None
    g.current_user = user
    return user


def current_uid():
    """The logged-in user's id, or None."""
    user = current_user()
    return None if user is None else user["id"]


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash(t("msg.sign_in_first"))
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None or not user["is_admin"]:
            flash(t("msg.admin_only"))
            return redirect(url_for("live_search"))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    lang = current_language()
    return {
        "current_user": current_user(),
        "csrf_token": csrf_token,
        # The footer on every page needs somewhere to point "Contact".
        "support_email": SUPPORT_EMAIL,
        # So the composer's maxlength and send_message()'s cap cannot drift.
        "message_max_chars": MESSAGE_MAX_CHARS,
        # t() is the workhorse: every template calls it, so it is short on
        # purpose. opt_label() and interest_text() translate the *label* of a
        # value that stays canonical English in the database.
        "t": lambda key, **kw: translate(lang, key, **kw),
        "opt_label": lambda value: option_label(lang, value),
        "interest_text": lambda value: interest_label(lang, value),
        "lang": lang,
        "languages": LANGUAGES,
        "language_short": LANGUAGE_SHORT,
        # A callable, not a value: base.html is rendered for every response,
        # and the sheet only needs rendering once per process.
        "css_digest": lambda: _render_stylesheet()["digest"],
        # Global rather than passed per-route: whether a location control
        # renders at all comes up in the profile form, the search wizard and
        # the criteria screen alike.
        "single_city": SINGLE_CITY,
    }


@app.before_request
def force_canonical_host():
    """Send every request to CANONICAL_HOST over https, if one is configured.

    The health paths are exempt: Cloud Run's startup probe reaches the
    container directly, not through the mapped domain, so redirecting it would
    fail every deploy.

    308 rather than 301 -- a 301 lets the browser turn a POST into a GET and
    drop the body, which would quietly break a login or a sent message posted
    to the wrong host.
    """
    if not CANONICAL_HOST or request.path in HEALTH_PATHS:
        return
    host = (request.host or "").lower()
    if not host or host == CANONICAL_HOST:
        return
    target = f"https://{CANONICAL_HOST}{request.full_path if request.query_string else request.path}"
    return redirect(target, code=308)


@app.before_request
def check_csrf():
    """Reject any state-changing request that didn't come from our own page.

    Without this every POST is forgeable from another site: a page the user
    happens to visit while signed in can send a message, change their
    profile, or resolve a match on their behalf. SameSite=Lax blocks the
    classic cross-site form post in current browsers, but it is a
    same-origin heuristic, not a token, and it does nothing for the
    fetch-based endpoints.
    """
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if request.path in CSRF_EXEMPT_PATHS:
        return

    supplied = request.form.get(CSRF_FIELD) or request.headers.get(CSRF_HEADER, "")
    if csrf_valid(supplied):
        return

    app.logger.warning("CSRF check failed for %s %s", request.method, request.path)
    security_event("csrf", "rejected", detail=f"{request.method} {request.path}")
    if "application/json" in request.headers.get("Accept", ""):
        return {"error": "Your session expired. Reload the page and try again."}, 400
    return (
        render_template("csrf_error.html"),
        400,
    )


@app.before_request
def load_current_user():
    """Resolve the session once per request and cache it on `g`.

    The last_seen_at refresh lives here rather than in current_user()
    because it writes: current_user() is called from the template context
    processor, and committing mid-render would commit whatever else the
    view had in flight. At before_request time nothing else is pending.
    """
    g.current_user = None
    user = _resolve_session_user()
    if user is None:
        return
    if user["status"] not in LOGIN_ALLOWED_STATUSES:
        # Suspended or banned mid-session: drop the session rather than
        # waiting for it to expire on its own.
        end_session()
        flash(t("msg.account_unavailable"))
        return
    g.current_user = user

    stale = user["session_last_seen"] < dt.now(timezone.utc) - SESSION_TOUCH_AFTER
    if stale:
        db = get_db()
        db.execute(
            "UPDATE sessions SET last_seen_at = NOW() WHERE id = ?",
            (user["session_id"],),
        )
        db.commit()


@app.before_request
def auto_login_admin():
    """Optional dev shortcut (AUTO_LOGIN=1): browse as admin without logging in.

    Debug-only: on a public deployment this would log every anonymous
    visitor in as the administrator. IS_PRODUCTION already refuses to let
    AUTO_LOGIN be set there, and this is the second lock on the same door.
    """
    if not AUTO_LOGIN or IS_PRODUCTION or current_user() is not None:
        return
    admin = get_db().execute(
        "SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (ADMIN_USERNAME,)
    ).fetchone()
    if admin is not None:
        start_session(admin["id"])


# --- security headers ------------------------------------------------------
# Every inline <script> in templates/ carries nonce="{{ csp_nonce() }}", which
# is what lets script-src stay strict: 'unsafe-inline' would make the CSP a
# decoration, since the whole point is that injected markup cannot run.
#
# style-src is the honest exception. Inline style="..." attributes are used
# throughout the templates and a nonce cannot cover an attribute, so
# 'unsafe-inline' stays there until those are gone. It is a far smaller
# opening than the script side would be.
#
# The photo route sets its own headers and is left alone -- it serves user
# bytes, not a page, and already says nosniff.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)


@app.before_request
def make_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)


@app.template_filter("br")
def _br(text):
    """Render a translated string's line breaks as <br>.

    Several headlines are deliberately broken across lines -- "Something /
    softer than / swiping." -- and where the break falls is a translator's
    decision, not the template's, so the newline lives in the catalogue and
    this turns it into markup. Escapes first, so only the <br> it adds is
    ever treated as HTML.
    """
    return Markup("<br>".join(escape(line) for line in str(text).split("\n")))


@app.context_processor
def expose_csp_nonce():
    return {"csp_nonce": lambda: getattr(g, "csp_nonce", "")}


# Text compresses to about a quarter of its size and nothing in front of
# this app does it: Cloud Run's frontend passes the body through untouched,
# so an uncompressed 142KB page stayed 142KB over the wire. stdlib gzip
# rather than a dependency -- this is one hook, and requirements.txt is
# deliberately short.
COMPRESSIBLE = ("text/html", "text/css", "text/plain",
                "application/json", "application/javascript", "image/svg+xml")
COMPRESS_MIN_BYTES = 1024


@app.after_request
def compress_response(response):
    """gzip a text response when the client said it could take one.

    Skips anything already encoded, anything streamed (direct_passthrough --
    touching .data there would buffer a file into memory), and anything small
    enough that the header overhead outweighs the saving. Vary is set either
    way, so a shared cache cannot hand a gzipped body to a client that did
    not ask for one.
    """
    response.headers.add("Vary", "Accept-Encoding")
    if (
        response.direct_passthrough
        or response.status_code < 200
        or response.status_code >= 300
        or "Content-Encoding" in response.headers
        or "gzip" not in request.headers.get("Accept-Encoding", "")
    ):
        return response
    if response.mimetype not in COMPRESSIBLE:
        return response
    body = response.get_data()
    if len(body) < COMPRESS_MIN_BYTES:
        return response
    # mtime=0 so the same body always produces the same bytes, which keeps
    # any ETag downstream stable across restarts.
    packed = gzip.compress(body, compresslevel=6, mtime=0)
    if len(packed) >= len(body):
        return response
    response.set_data(packed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(packed))
    return response


@app.after_request
def security_headers(response):
    # /lab serves the mockup file verbatim -- it is not a Jinja template, so
    # its inline scripts carry no nonce and it pulls webfonts from Google.
    # It is admin-only and touches no data; the rest of the headers still
    # apply to it. Weakening the whole app's CSP to accommodate a design
    # scratchpad would be the wrong way round.
    if request.path != "/lab":
        response.headers.setdefault(
            "Content-Security-Policy", CSP.format(nonce=getattr(g, "csp_nonce", "")))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(), microphone=(), payment=()")
    # Only over TLS, and only in production: sending HSTS from a plain-http
    # dev server teaches the browser to refuse localhost over http for a year.
    if IS_PRODUCTION and request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


MOCKUPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mockups")


@app.route("/lab")
@admin_required
def design_lab():
    """Serve the design iteration lab.

    Static, self-contained mock data that never touches the database — but
    it is an internal tool, and an internal tool on a public dating site is
    just an unexplained page strangers can find.
    """
    return send_from_directory(MOCKUPS_DIR, "velvet-lab.html")


# Below this, the member count is not shown at all -- not replaced with a
# bigger one. A launching product has a thin first week and "3 members" reads
# worse than saying nothing, but the fix for a number you don't want to show
# is to not show it, not to print a different one: every visitor decides
# whether to sign up partly on how many people are already here, so a figure
# that isn't true is a false answer to the question they are actually asking.
MEMBER_COUNT_FLOOR = 25


def landing_pulse():
    """One true line about how busy Velvt is, for logged-out visitors.

    Four tiers, tried in order, and every one of them is a fact:
      1. people searching this minute -- the strongest thing we can say, and
         the only tier that earns the live dot
      2. searches started today, when nobody is mid-search right now
      3. members registered, once there are enough for the number to invite
         rather than deter
      4. no number at all -- an invitation instead

    Demo members are excluded throughout by CANDIDATE_ELIGIBLE_SQL and the
    is_bot check: counting them would advertise a pool that does not exist.
    """
    db = get_db()
    live = db.execute(
        f"""
        SELECT COUNT(*) AS n FROM searches s
        JOIN users u ON u.id = s.user_id
        WHERE s.status = 'waiting' {CANDIDATE_ELIGIBLE_SQL}
        """
    ).fetchone()["n"]
    if live:
        return {"live": True,
                "text": t("pulse.live_one") if live == 1 else t("pulse.live_many", n=live)}

    row = db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM searches s JOIN users u ON u.id = s.user_id
             WHERE u.is_bot = FALSE AND s.created_at >= NOW() - INTERVAL '1 day') AS today,
          (SELECT COUNT(*) FROM users
             WHERE is_bot = FALSE AND status = 'active') AS members
        """
    ).fetchone()
    if row["today"]:
        return {"live": False,
                "text": t("pulse.today_one") if row["today"] == 1
                        else t("pulse.today_many", n=row["today"])}
    if row["members"] >= MEMBER_COUNT_FLOOR:
        return {"live": False, "text": t("pulse.members", n=row["members"])}
    return {"live": False, "text": t("pulse.be_first")}


@app.route("/")
def index():
    if current_uid():
        return redirect(url_for("live_search"))
    return render_template("landing.html", pulse=landing_pulse())


@app.route("/help")
def help_page():
    """Kept as a redirect, not a page of its own.

    A concurrent branch built a real /help route with its own placeholder
    legal text before the launch-readiness audit's actual /terms, /privacy,
    /imprint, /safety and /faq existed. Serving that stub now would regress
    real compliance copy (consent, DSA notice-and-action, the real imprint)
    behind a nicer-sounding URL. Anything that already links to /help still
    resolves -- just to the real FAQ instead of a page that duplicates it.
    """
    return redirect(url_for("faq"))


@app.route("/register", methods=["GET", "POST"])
@rate_limited("register", limit=20, window_seconds=3600)
def register():
    if current_uid():
        return redirect(url_for("live_search"))

    form = {"username": "", "email": "", "dob": ""}

    if request.method == "POST":
        form["username"] = request.form.get("username", "").strip()
        form["email"] = request.form.get("email", "").strip()
        form["dob"] = request.form.get("dob", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        dob = parse_dob(form["dob"])
        age = None if dob is None else age_on(dob)

        error = None
        if not form["username"] or len(form["username"]) < 3:
            error = t("msg.username_short")
        elif not valid_email(form["email"]):
            error = t("msg.email_required")
        elif dob is None:
            error = t("msg.dob_required")
        elif age is None or age < MIN_SIGNUP_AGE:
            # Deliberately terminal: a "you must be 18" message next to an
            # editable date field is an instruction to try another one.
            session["age_gate_failed"] = True
            return render_template("age_gate.html"), 403
        elif age > MAX_PLAUSIBLE_AGE:
            error = t("msg.dob_invalid")
        elif password_problem(password, confirm):
            error = password_problem(password, confirm)
        elif not request.form.get("accept_terms"):
            error = t("msg.accept_terms")
        elif not request.form.get("accept_sensitive"):
            # Separate from the terms box on purpose. Article 9 consent has
            # to be specific and freely given, which a single "I agree to
            # everything" checkbox is not.
            error = (
                "We need your permission to use your gender and who you're "
                "looking for, or we can't match you."
            )

        if error is None and session.get("age_gate_failed"):
            return render_template("age_gate.html"), 403

        if error is None:
            db = get_db()
            try:
                new_id = db.insert_returning_id(
                    """
                    INSERT INTO users (username, email, password_hash, dob,
                                       password_changed_at)
                    VALUES (?, ?, ?, ?, NOW())
                    """,
                    (
                        form["username"],
                        form["email"],
                        generate_password_hash(password),
                        dob,
                    ),
                )
                db.execute(
                    "INSERT INTO profiles (user_id, age) VALUES (?, ?)", (new_id, age)
                )
                for document, version in (
                    ("terms", TERMS_VERSION),
                    ("privacy", PRIVACY_VERSION),
                ):
                    db.execute(
                        """
                        INSERT INTO legal_acceptances (user_id, document, version)
                        VALUES (?, ?, ?) ON CONFLICT DO NOTHING
                        """,
                        (new_id, document, version),
                    )
                db.execute(
                    "INSERT INTO consents (user_id, purpose) VALUES (?, ?) "
                    "ON CONFLICT DO NOTHING",
                    (new_id, CONSENT_SENSITIVE),
                )
                db.commit()
            except psycopg.errors.UniqueViolation:
                db.rollback()
                # Which one collided decides the message, so "taken" never
                # doubles as an account-enumeration oracle for addresses.
                taken = db.execute(
                    "SELECT 1 AS hit FROM users WHERE LOWER(username) = LOWER(?)",
                    (form["username"],),
                ).fetchone()
                error = (
                    "That username is already taken."
                    if taken
                    else "That email address is already registered. Try signing in."
                )
            else:
                send_verification_email(new_id, form["email"])
                start_session(new_id)
                flash(t("msg.registered"))
                return redirect(url_for("edit_profile"))

        flash(error)

    return render_template("register.html", form=form, age_min=MIN_SIGNUP_AGE)


@app.route("/login", methods=["GET", "POST"])
@rate_limited("login", limit=10, window_seconds=300)
def login():
    if current_uid():
        return redirect(url_for("live_search"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        # Either the username or the email address signs you in -- people
        # remember one or the other, rarely which one this site wanted.
        user = get_db().execute(
            """
            SELECT * FROM users
            WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
            """,
            (identifier, identifier),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            if user["status"] not in LOGIN_ALLOWED_STATUSES:
                security_event("login", "refused", user_id=user["id"],
                               detail=f"status={user['status']}")
                flash(t("msg.account_unavailable"))
                return render_template("login.html")
            start_session(user["id"], remember=remember)
            security_event("login", "success", user_id=user["id"])
            return redirect(url_for("live_search"))

        # The identifier is not recorded: a failed login often *is* somebody's
        # password typed into the username box, and that would put it in the
        # log in clear.
        security_event("login", "failure",
                       user_id=user["id"] if user else None,
                       detail="unknown account" if not user else "wrong password")
        flash(t("msg.bad_credentials"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    end_session()
    return redirect(url_for("login"))


@app.route("/verify/<token>")
def verify_email(token):
    user_id = consume_email_token(token, "verify")
    if user_id is None:
        flash(t("msg.verify_expired"))
        user = current_user()
        if user is not None and user["email"]:
            send_verification_email(user["id"], user["email"])
        return redirect(url_for("live_search") if user else url_for("login"))

    db = get_db()
    db.execute(
        "UPDATE users SET email_verified_at = NOW() WHERE id = ?", (user_id,)
    )
    db.commit()
    flash(t("msg.verified"))
    return redirect(url_for("live_search") if current_uid() else url_for("login"))


@app.route("/verify/resend", methods=["POST"])
@login_required
@rate_limited("resend", limit=3, window_seconds=3600, by="user")
def resend_verification():
    user = current_user()
    if user["email"] and user["email_verified_at"] is None:
        send_verification_email(user["id"], user["email"])
    flash(t("msg.verify_sent"))
    return redirect(request.referrer or url_for("live_search"))


@app.route("/forgot", methods=["GET", "POST"])
@rate_limited("forgot", limit=5, window_seconds=3600)
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = get_db().execute(
            "SELECT id, email FROM users WHERE LOWER(email) = LOWER(?)", (email,)
        ).fetchone()

        if user is not None:
            token = issue_email_token(user["id"], "reset", RESET_TOKEN_HOURS)
            link = app_url(url_for("reset_password", token=token))
            send_email(
                user["email"],
                "Reset your Velvt password",
                f"""<p>Someone asked to reset the password for your Velvt account.</p>
                    <p><a href="{link}">Choose a new password</a></p>
                    <p>The link works once and expires in {RESET_TOKEN_HOURS} hour(s).
                       If this wasn't you, ignore this email — nothing has changed.</p>""",
            )

        # Same answer either way. Branching here would turn this form into a
        # way to ask the site which addresses have accounts.
        flash(t("msg.reset_sent"))
        return redirect(url_for("login"))

    return render_template("forgot.html")


@app.route("/reset/<token>", methods=["GET", "POST"])
@rate_limited("reset", limit=10, window_seconds=3600)
def reset_password(token):
    user_id = consume_email_token(token, "reset", peek=True)
    if user_id is None:
        flash(t("msg.reset_expired"))
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        problem = password_problem(password, confirm)
        if problem:
            flash(problem)
        else:
            consume_email_token(token, "reset")
            db = get_db()
            db.execute(
                """
                UPDATE users SET password_hash = ?, password_changed_at = NOW()
                WHERE id = ?
                """,
                (generate_password_hash(password), user_id),
            )
            db.commit()
            # Whoever had the old password is now out, everywhere. That is
            # the point of a reset.
            revoke_user_sessions(user_id)
            security_event("password_reset", "success", user_id=user_id)
            start_session(user_id)
            flash(t("msg.password_updated"))
            return redirect(url_for("live_search"))

    return render_template("reset.html", token=token)


def validate_profile(values):
    """Return (error, age) for a submitted profile form."""
    age = None
    error = None
    if not values["name"]:
        error = t("msg.name_required")
    else:
        try:
            age = int(values["age"])
            if not AGE_MIN_YEARS <= age <= AGE_MAX_YEARS:
                error = f"Age must be between {AGE_MIN_YEARS} and {AGE_MAX_YEARS}."
        except (TypeError, ValueError):
            error = t("msg.age_invalid")

    if values["relationship_type"] and values["relationship_type"] not in RELATIONSHIP_TYPES:
        error = t("msg.pick_relationship")
    if (values["relationship_preference"]
            and values["relationship_preference"] not in RELATIONSHIP_PREFERENCES):
        error = t("msg.pick_relationship_preference")
    if values["gender"] and values["gender"] not in GENDERS:
        error = t("msg.pick_gender")
    if values["seeking"] and values["seeking"] not in SEEKING_OPTIONS:
        error = t("msg.pick_seeking")

    return error, age


def validate_physical(values):
    """Validate and coerce physical attributes and preferences.

    Returns (error, coerced_dict) where error is None on success, else a
    string. Coerced dict has ints for height fields, validated strings for
    categories, and CSV for multi-select.
    """
    coerced = {}

    # Self-attributes
    if values.get("height_cm"):
        try:
            h = int(values["height_cm"])
            if not HEIGHT_MIN_CM <= h <= HEIGHT_MAX_CM:
                return f"Height must be between {HEIGHT_MIN_CM} and {HEIGHT_MAX_CM} cm.", None
            coerced["height_cm"] = h
        except (TypeError, ValueError):
            return "Please enter a valid height.", None
    else:
        coerced["height_cm"] = None

    for field, options in [
        ("body_type", BODY_TYPES),
        ("fitness_level", FITNESS_LEVELS),
        ("hair_color", HAIR_COLORS),
        ("eye_color", EYE_COLORS),
        ("tattoos", TATTOO_LEVELS),
    ]:
        val = values.get(field, "").strip()
        if val and val not in options:
            return f"Invalid {field.replace('_', ' ')}.", None
        coerced[field] = val

    # Preferences (search wizard's step-3 physical filters, stored on
    # searches, not profiles)
    pref_h_min_str = values.get("pref_height_min", "").strip()
    pref_h_max_str = values.get("pref_height_max", "").strip()

    if pref_h_min_str or pref_h_max_str:
        try:
            pref_h_min = int(pref_h_min_str) if pref_h_min_str else None
            pref_h_max = int(pref_h_max_str) if pref_h_max_str else None

            if pref_h_min is None or pref_h_max is None:
                return "Both height bounds are required if either is set.", None
            if not (HEIGHT_MIN_CM <= pref_h_min <= HEIGHT_MAX_CM):
                return f"Minimum height must be between {HEIGHT_MIN_CM} and {HEIGHT_MAX_CM} cm.", None
            if not (HEIGHT_MIN_CM <= pref_h_max <= HEIGHT_MAX_CM):
                return f"Maximum height must be between {HEIGHT_MIN_CM} and {HEIGHT_MAX_CM} cm.", None
            if pref_h_min > pref_h_max:
                return "Minimum height must not exceed maximum.", None

            coerced["pref_height_min"] = pref_h_min
            coerced["pref_height_max"] = pref_h_max
        except (TypeError, ValueError):
            return "Please enter valid height bounds.", None
    else:
        coerced["pref_height_min"] = None
        coerced["pref_height_max"] = None

    # Preferences: body types (multi-select, CSV)
    # The caller uses request.form.getlist() separately; we just validate if provided
    pref_body_csv = values.get(PREF_BODY_TYPES_FIELD, "").strip()
    if pref_body_csv:
        selected = [b.strip() for b in pref_body_csv.split(",")]
        for b in selected:
            if b and b not in BODY_TYPES:
                return f"Invalid body type: {b}.", None
    coerced[PREF_BODY_TYPES_FIELD] = pref_body_csv

    # Preferences: single-select categories
    for field, options in [
        ("pref_fitness_level", FITNESS_LEVELS),
        ("pref_hair_color", HAIR_COLORS),
        ("pref_eye_color", EYE_COLORS),
        ("pref_tattoos", TATTOO_LEVELS),
    ]:
        val = values.get(field, "").strip()
        if val and val not in options:
            return f"Invalid {field.replace('_', ' ')}.", None
        coerced[field] = val

    return None, coerced


# Scoring parameters
WEIGHTS = {
    "height": 18,
    "body_type": 16,
    "fitness": 14,
    "hair_color": 8,
    "eye_color": 8,
    "tattoos": 10,
    # physical subtotal = 74
    "interests": 12,
    "relationship_type": 8,
    "age": 4,
    "location": 2,
    # total = 100
}

HEIGHT_TAPER_CM = 15  # taper range for height preference satisfaction


def _normalize_numeric(value, pref_min, pref_max, taper_span):
    """Normalize a numeric attribute to [0, 1] with linear taper outside range.

    Returns None if value or both bounds are missing.
    1.0 inside [pref_min, pref_max], linear taper to 0 across taper_span outside.
    """
    if value is None or pref_min is None or pref_max is None:
        return None

    if pref_min <= value <= pref_max:
        return 1.0

    if value < pref_min:
        gap = pref_min - value
        if gap >= taper_span:
            return 0.0
        return 1.0 - (gap / taper_span)
    else:  # value > pref_max
        gap = value - pref_max
        if gap >= taper_span:
            return 0.0
        return 1.0 - (gap / taper_span)


def _ordinal_satisfaction(value, target, levels):
    """Ordinal satisfaction: distance between indices.

    Returns None if either is missing.
    1.0 for exact match, linear falloff by |idx_diff| / (num_levels - 1).
    """
    if value is None or target is None or not value or not target:
        return None

    if value not in levels or target not in levels:
        return None

    idx_val = levels.index(value)
    idx_tgt = levels.index(target)
    n = len(levels) - 1
    if n == 0:
        return 1.0
    return 1.0 - (abs(idx_val - idx_tgt) / n)


def _categorical_satisfaction(value, target):
    """Exact-match satisfaction: 1.0 for match, 0.0 otherwise.

    Returns None if either is missing.
    """
    if value is None or target is None or not value or not target:
        return None

    return 1.0 if value == target else 0.0


def _categorical_multi_satisfaction(value, target_csv):
    """Multi-select satisfaction: is value in the CSV list?

    Returns None if either is missing or empty.
    1.0 if value is in target_csv, 0.0 otherwise.
    """
    if value is None or target_csv is None or not value or not target_csv:
        return None

    targets = [t.strip() for t in target_csv.split(",")]
    return 1.0 if value in targets else 0.0


def directional_score(seeker, candidate):
    """Score a candidate from seeker's perspective: (score_0_100, reasons).

    Computes a weighted harmonic average of attribute satisfactions:
    - Physical: height, body_type, fitness, hair_color, eye_color, tattoos
    - Social: interests (token overlap), relationship_type, age, location

    Attributes with missing data (None/"") are skipped; only present values
    contribute to the average.

    Returns:
        (float score 0-100, list of reason strings for high-scoring matches)
    """
    satisfactions = []  # (weight, satisfaction, attribute_name)

    # Height
    sat = _normalize_numeric(
        candidate.get("height_cm"),
        seeker.get("pref_height_min"),
        seeker.get("pref_height_max"),
        HEIGHT_TAPER_CM,
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["height"], sat, "height"))

    # Body type (seeker's preference is CSV)
    sat = _categorical_multi_satisfaction(
        candidate.get("body_type"),
        seeker.get("pref_body_types"),
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["body_type"], sat, "body_type"))

    # Fitness level
    sat = _ordinal_satisfaction(
        candidate.get("fitness_level"),
        seeker.get("pref_fitness_level"),
        FITNESS_LEVELS,
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["fitness"], sat, "fitness"))

    # Hair color
    sat = _categorical_satisfaction(
        candidate.get("hair_color"),
        seeker.get("pref_hair_color"),
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["hair_color"], sat, "hair_color"))

    # Eye color
    sat = _categorical_satisfaction(
        candidate.get("eye_color"),
        seeker.get("pref_eye_color"),
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["eye_color"], sat, "eye_color"))

    # Tattoos (ordinal like fitness)
    sat = _ordinal_satisfaction(
        candidate.get("tattoos"),
        seeker.get("pref_tattoos"),
        TATTOO_LEVELS,
    )
    if sat is not None:
        satisfactions.append((WEIGHTS["tattoos"], sat, "tattoos"))

    # Shared interests
    shared = _tokens(seeker["interests"], seeker["hobbies"]) & _tokens(
        candidate["interests"], candidate["hobbies"]
    )
    if shared:
        # Cap shared interests at 1.0 by capping the contribution.
        # Use min(shared_count, max_keywords) to avoid unbounded scores.
        max_keywords = 5
        interest_count = min(len(shared), max_keywords)
        sat = interest_count / max_keywords
        satisfactions.append((WEIGHTS["interests"], sat, "interests"))

    # Relationship type
    if (
        seeker.get("relationship_type")
        and candidate.get("relationship_type")
        and seeker["relationship_type"] == candidate["relationship_type"]
    ):
        satisfactions.append((WEIGHTS["relationship_type"], 1.0, "relationship_type"))

    # Age proximity
    if seeker.get("age") and candidate.get("age"):
        gap = abs(seeker["age"] - candidate["age"])
        # Linear: 1.0 at gap=0, 0.0 at gap=20+
        age_sat = max(0.0, 1.0 - (gap / 20.0))
        satisfactions.append((WEIGHTS["age"], age_sat, "age"))

    # Location
    if (
        seeker.get("location")
        and candidate.get("location")
        and seeker["location"].strip().lower() == candidate["location"].strip().lower()
    ):
        satisfactions.append((WEIGHTS["location"], 1.0, "location"))

    # Compute weighted average
    if not satisfactions:
        return 0.0, []

    total_weight = sum(w for w, _, _ in satisfactions)
    total_satisfaction = sum(w * s for w, s, _ in satisfactions)
    score = 100.0 * total_satisfaction / total_weight if total_weight > 0 else 0.0

    # Collect reason strings for attributes scoring >= 0.75 at non-trivial weight
    reasons = []
    for weight, sat, attr in satisfactions:
        if sat >= 0.75 and weight >= 5:
            if attr == "interests" and shared:
                reasons.append("Shared interests: " + ", ".join(sorted(shared)))
            elif attr == "height":
                reasons.append("Preferred height range")
            elif attr == "body_type":
                reasons.append("Matches body type preference")
            elif attr == "fitness":
                reasons.append("Fitness level preference match")
            elif attr == "hair_color":
                reasons.append("Hair color preference")
            elif attr == "eye_color":
                reasons.append("Eye color preference")
            elif attr == "tattoos":
                reasons.append("Tattoo preference")
            elif attr == "relationship_type":
                reasons.append(f"You both want: {seeker['relationship_type'].lower()}")
            elif attr == "age":
                gap = abs(seeker["age"] - candidate["age"])
                if gap <= 3:
                    reasons.append("Close in age")
                else:
                    reasons.append("Within age preference")
            elif attr == "location":
                reasons.append(f"Same location: {candidate['location']}")

    return score, reasons


def mutual_score(a, b):
    """Harmonic mean of reciprocal match scores.

    Returns (float score 0-100, list of reasons).

    Computes directional_score(a, b) and directional_score(b, a), then
    returns 2ab/(a+b) so that one-sided attraction cannot outrank mutual
    compatibility.
    """
    score_a_to_b, reasons_a = directional_score(a, b)
    score_b_to_a, reasons_b = directional_score(b, a)

    if score_a_to_b == 0 or score_b_to_a == 0:
        return 0.0, []

    harmonic = (2 * score_a_to_b * score_b_to_a) / (score_a_to_b + score_b_to_a)

    # Combine reasons: use unique strings, avoid duplicates
    all_reasons = list(set(reasons_a + reasons_b))
    return harmonic, sorted(all_reasons)


# Bio length the editor counts against. Generous next to what people
# actually write (the seeded profiles top out around 85 characters), so it
# reads as a target rather than a wall. Enforced in the browser only — an
# existing longer bio still saves untouched rather than being rejected.
BIO_MAX_CHARS = 240

# Offered as chips in the editor. Interests stay free text in the database:
# these are the common values, and anything already on a profile is shown
# alongside them, so nothing anyone wrote is lost by picking from a list.
INTEREST_SUGGESTIONS = [
    "anime", "art", "board games", "books", "cars", "cooking", "cycling",
    "festivals", "films", "food", "football", "gaming", "gardening",
    "hiking", "jazz", "languages", "museums", "music", "photography",
    "poetry", "sailing", "techno", "travel", "whisky", "wine",
]


# The handful the search wizard shows inline. The rest stay one tap away in
# the "More" overlay -- the step's promise is that it never scrolls, and the
# full 25 do not fit a phone screen.
INTEREST_COMMON = [
    "music", "films", "food", "travel", "cooking", "hiking",
    "books", "gaming", "art", "football", "photography", "cycling",
]

# Interests are an AND-free filter -- one shared keyword is enough to pair --
# so a long list makes matching easier, not pickier, and reads as noise on
# the other person's card. Cap it.
INTEREST_MAX = 4


def clean_interests(raw, limit=INTEREST_MAX):
    """Normalise an interests CSV: trimmed, de-duplicated, capped.

    Enforced here as well as in the browser, since the cap is a real rule
    about the stored value rather than a hint about the form.
    """
    out = []
    seen = set()
    for part in (raw or "").split(","):
        value = " ".join(part.split())
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        out.append(value)
        if len(out) >= limit:
            break
    return ", ".join(out)


def interest_choices(raw):
    """Chips to show, and which are on, for a profile's interests CSV.

    Anything the profile already carries leads the list even when it is not
    a suggestion, so a custom interest survives a round trip through the
    editor instead of being quietly dropped.
    """
    chosen = [p.strip() for p in (raw or "").split(",") if p.strip()]
    extras = [c for c in chosen if c not in INTEREST_SUGGESTIONS]
    return extras + INTEREST_SUGGESTIONS, chosen


# The fields other people's filters actually read. Profile strength is just
# how many of them are filled in — no hidden weighting — and the hint names
# the first real gap instead of nagging in general terms.
STRENGTH_FIELDS = [
    ("name", "Add your name"),
    ("age", "Add your age"),
    ("gender", "Set your gender"),
    ("seeking", "Say who you're looking for"),
    ("location", "Add your location"),
    ("relationship_type", "Say what kind of connection you want"),
    ("bio", "Write a short bio"),
    ("interests", "List a few interests"),
    ("height_cm", "Add your height"),
    ("body_type", "Add your body type"),
    ("fitness_level", "Add your fitness level"),
    ("hair_color", "Add your hair colour"),
    ("eye_color", "Add your eye colour"),
    ("tattoos", "Say whether you have tattoos"),
    ("relationship_preference", "Say your relationship preference"),
]


def profile_strength(profile, photo_count):
    """Return (percent complete, next gap to close).

    A photo counts for one slot of its own: other people's physical filters
    skip profiles that have none, so it is worth about as much as any single
    field, and it is listed first when missing for the same reason.
    """
    filled = [bool(str(profile.get(f) or "").strip()) for f, _ in STRENGTH_FIELDS]
    missing = [hint for (_, hint), ok in zip(STRENGTH_FIELDS, filled) if not ok]

    done = sum(filled) + (1 if photo_count else 0)
    if not photo_count:
        missing.insert(0, "Add a photo — other people's filters skip profiles without one")

    percent = round(done * 100 / (len(STRENGTH_FIELDS) + 1))
    return percent, (missing[0] if missing else None)


def apply_photo_edits(db, user_id, removals, uploads, posted_order, posted_primary):
    """Land one save's worth of photo changes. Does not commit.

    The edit screen stages the lot -- removals, new files, the drag order and
    which tile is the main one -- and posts them together, so they have to be
    applied together and in this order: a photo removed here must free its
    place before the cap is spent, and the order and the primary can only be
    written once the new rows have ids.

    `posted_order` and `posted_primary` speak the tiles' language: an existing
    photo is its id, a file picked in this session is "new:<n>", indexing the
    file input the browser submitted. Anything that doesn't resolve to a row
    this user owns is dropped on the floor rather than trusted.
    """
    if removals:
        db.execute(
            "DELETE FROM photos WHERE user_id = ? AND id = ANY(?)",
            (user_id, list(removals)),
        )

    # Insert in submission order, so new:<n> lines up with the n-th file.
    new_ids = [
        db.insert_returning_id(
            "INSERT INTO photos (user_id, data, mime, is_primary) VALUES (?, ?, ?, FALSE)",
            (user_id, data, mime),
        )
        for mime, data in uploads
    ]

    owned = [
        row["id"] for row in db.execute(
            "SELECT id FROM photos WHERE user_id = ?"
            " ORDER BY is_primary DESC, sort_order, id",
            (user_id,),
        ).fetchall()
    ]
    if not owned:
        return

    def resolve(key):
        if key.startswith("new:"):
            n = key[4:]
            if n.isdigit() and int(n) < len(new_ids):
                return new_ids[int(n)]
            return None
        return int(key) if key.lstrip("-").isdigit() and int(key) in owned else None

    # Whatever the tiles listed goes first, in that order; anything of theirs
    # the list forgot keeps its existing relative position after it, so a
    # stale or partial order can never silently drop a photo out of the set.
    ranked, seen = [], set()
    for key in posted_order:
        pid = resolve(key)
        if pid is not None and pid not in seen:
            seen.add(pid)
            ranked.append(pid)
    ranked += [pid for pid in owned if pid not in seen]

    for index, pid in enumerate(ranked):
        db.execute("UPDATE photos SET sort_order = ? WHERE id = ?", (index, pid))

    # The main photo: the tapped tile if it survived, otherwise whichever
    # photo now sorts first. A set is never left headless -- everything that
    # shows one photo takes the primary, so losing it would blank the avatars.
    primary = resolve(posted_primary) if posted_primary else None
    if primary is None:
        current = db.execute(
            "SELECT id FROM photos WHERE user_id = ? AND is_primary LIMIT 1", (user_id,)
        ).fetchone()
        primary = current["id"] if current else ranked[0]

    db.execute("UPDATE photos SET is_primary = (id = ?) WHERE user_id = ?", (primary, user_id))


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    user_id = current_uid()

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}
        # Pinned to one city for now, so the form has no location control and
        # whatever arrives under that name is ignored rather than trusted.
        values["location"], _, _ = pinned_place(values["location"])
        error, age = validate_profile(values)
        phys_error, phys = validate_physical(values)
        error = error or phys_error

        # Photos: sniff magic bytes rather than trusting the browser's
        # Content-Type, cap size and count. Validated up front so a bad
        # upload doesn't half-save the rest of the profile.
        #
        # The edit screen stages everything and submits it here in one go:
        # which existing photos to drop, which order the tiles were dragged
        # into, and which one was tapped as the main. Those three fields are
        # a convenience for the browser -- every id in them is re-checked
        # against ownership below, so a hand-written POST can only ever
        # rearrange the poster's own photos.
        removals = {
            int(part) for part in request.form.get("remove_photo_ids", "").split(",")
            if part.strip().lstrip("-").isdigit()
        }
        posted_order = [
            part.strip() for part in request.form.get("photo_order", "").split(",")
            if part.strip()
        ]
        posted_primary = request.form.get("primary_photo_id", "").strip()

        uploads = []
        for f in request.files.getlist("photos"):
            if not f or not f.filename:
                continue
            data = f.read(PHOTO_MAX_BYTES + 1)
            if len(data) > PHOTO_MAX_BYTES:
                error = error or t("msg.photo_too_big")
                break
            mime = sniff_image_mime(data)
            if mime is None or mime not in PHOTO_ALLOWED_MIMES:
                error = error or t("msg.photo_type")
                break
            uploads.append((mime, data))
        else:
            if uploads:
                owned = {
                    row["id"] for row in db.execute(
                        "SELECT id FROM photos WHERE user_id = ?", (user_id,)
                    ).fetchall()
                }
                # Removals count against the cap: swapping two photos for two
                # others is a legal save, and checking the stored count alone
                # (as this did) refused it at six.
                kept = len(owned - removals)
                if kept + len(uploads) > PHOTO_MAX_PER_USER:
                    error = error or f"You can have at most {PHOTO_MAX_PER_USER} photos."

        if error is None:
            # An UPSERT rather than a bare UPDATE: user_id is profiles' own
            # primary key, so a row always exists for a normal registration
            # or admin-created account (both insert one up front) — but a
            # save must still land even if that row is ever missing, rather
            # than silently affecting zero rows and reporting success anyway.
            db.execute(
                """
                INSERT INTO profiles
                    (user_id, name, age, gender, seeking, location,
                     height_cm, body_type, fitness_level,
                     hair_color, eye_color, tattoos,
                     bio, interests, hobbies,
                     relationship_type, relationship_preference, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    name = excluded.name, age = excluded.age,
                    gender = excluded.gender, seeking = excluded.seeking,
                    location = excluded.location,
                    height_cm = excluded.height_cm,
                    body_type = excluded.body_type,
                    fitness_level = excluded.fitness_level,
                    hair_color = excluded.hair_color,
                    eye_color = excluded.eye_color,
                    tattoos = excluded.tattoos,
                    bio = excluded.bio, interests = excluded.interests,
                    hobbies = excluded.hobbies,
                    relationship_type = excluded.relationship_type,
                    relationship_preference = excluded.relationship_preference,
                    updated_at = NOW()
                """,
                (
                    user_id, values["name"], age, values["gender"], values["seeking"],
                    values["location"],
                    phys["height_cm"], phys["body_type"], phys["fitness_level"],
                    phys["hair_color"], phys["eye_color"], phys["tattoos"],
                    values["bio"], values["interests"],
                    values["hobbies"], values["relationship_type"],
                    values["relationship_preference"],
                ),
            )
            apply_photo_edits(db, user_id, removals, uploads, posted_order, posted_primary)
            db.commit()
            flash(t("msg.profile_saved"))
            return redirect(url_for("view_profile", user_id=user_id))

        flash(error)
        profile = dict(values)
    else:
        row = db.execute(
            "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        # Every account gets a profiles row at creation (register() and
        # admin_new_profile() both insert one), so this is a defensive
        # fallback rather than the normal path — but the edit form should
        # render blank and let a save recreate the row instead of 500ing.
        profile = dict(row) if row is not None else {f: "" for f in PROFILE_FIELDS}

    # Shown as tiles so you can see what you already have while editing.
    photos = db.execute(
        "SELECT id, is_primary FROM photos WHERE user_id = ?"
        " ORDER BY is_primary DESC, sort_order, id",
        (user_id,),
    ).fetchall()
    strength_pct, strength_hint = profile_strength(profile, len(photos))
    chips, chosen = interest_choices(profile.get("interests"))

    # The Fill buttons are a dev affordance -- _profile_fields.html renders
    # them only when sample_profile is defined, so passing it unconditionally
    # shipped them to every real user. Admins keep them everywhere.
    extra = {}
    if current_user()["is_admin"]:
        extra["sample_profile"] = sample_profile_data()

    return render_template(
        "profile_edit.html",
        profile=profile,
        photos=photos,
        strength_pct=strength_pct,
        strength_hint=strength_hint,
        # What is *blocking* a search, as opposed to what would merely
        # improve the profile -- the meter's hint covers the latter.
        blocking=profile_completeness(current_uid(), profile)["missing"],
        bio_max=BIO_MAX_CHARS,
        interest_chips=chips,
        interest_chosen=chosen,
        interest_max=INTEREST_MAX,
        relationship_types=RELATIONSHIP_TYPES,
        relationship_preferences=RELATIONSHIP_PREFERENCES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
        body_types=BODY_TYPES,
        fitness_levels=FITNESS_LEVELS,
        hair_colors=HAIR_COLORS,
        eye_colors=EYE_COLORS,
        tattoo_levels=TATTOO_LEVELS,
        height_min=HEIGHT_MIN_CM,
        height_max=HEIGHT_MAX_CM,
        city_choices=CITY_CHOICES,
        photo_max_bytes=PHOTO_MAX_BYTES,
        photo_max_per_user=PHOTO_MAX_PER_USER,
        **extra,
    )


@app.route("/profile/<int:user_id>")
@login_required
def view_profile(user_id):
    row = get_db().execute(
        """
        SELECT p.*, u.username FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id = ?
        """,
        (user_id,),
    ).fetchone()

    user = current_user()
    if row is None or (
        is_blocked_between(user_id, user["id"]) and not user["is_admin"]
    ):
        # Same answer for "no such profile" and "blocked", so the page
        # cannot be used to work out that someone blocked you.
        flash(t("msg.no_such_profile"))
        return redirect(url_for("live_search"))

    can_view = can_view_photos(user_id, user["id"], user["is_admin"])
    photos = (
        get_db()
        .execute(
            "SELECT id, is_primary FROM photos WHERE user_id = ?"
            " ORDER BY is_primary DESC, sort_order, id",
            (user_id,),
        )
        .fetchall()
        if can_view
        else []
    )

    return render_template(
        "profile_view.html",
        profile=row,
        is_own=(user_id == current_uid()),
        can_view_photos=can_view,
        photos=photos,
    )


@app.route("/terms")
def terms():
    return render_template("legal_terms.html", version=TERMS_VERSION,
                           support_email=SUPPORT_EMAIL)


@app.route("/privacy")
def privacy():
    return render_template("legal_privacy.html", version=PRIVACY_VERSION,
                           support_email=SUPPORT_EMAIL,
                           retention_days=DELETION_GRACE_DAYS)


@app.route("/imprint")
def imprint():
    return render_template("legal_imprint.html", support_email=SUPPORT_EMAIL)


@app.route("/safety")
def safety():
    return render_template("safety.html", support_email=SUPPORT_EMAIL)


@app.route("/faq")
def faq():
    """The questions support would otherwise answer one at a time.

    Public, like /safety: someone deciding whether to sign up has most of
    these questions before they have an account.
    """
    return render_template(
        "faq.html",
        reveal_seconds=REVEAL_SECONDS,
        chat_minutes=TIMED_CHAT_SECONDS // 60,
    )


@app.route("/how-matching-works", methods=["GET", "POST"])
@login_required
def how_matching_works():
    """The timed-match mechanic, explained before it happens rather than
    during. Reachable any time from the footer; shown automatically once,
    before the first search.

    POST is the acknowledgement. Marking it seen on GET would mean a
    half-loaded page counts as having been read.
    """
    if request.method == "POST":
        db = get_db()
        db.execute(
            "UPDATE users SET match_intro_seen_at = NOW() WHERE id = ? "
            "AND match_intro_seen_at IS NULL",
            (current_uid(),),
        )
        db.commit()
        return redirect(url_for("live_search"))

    return render_template(
        "how_matching_works.html",
        reveal_seconds=REVEAL_SECONDS,
        chat_minutes=TIMED_CHAT_SECONDS // 60,
        first_time=not current_user()["match_intro_seen_at"],
    )


@app.route("/settings")
@login_required
def settings():
    me = current_user()
    db = get_db()
    mine_hash = hash_token(session.get("sid", ""))
    sessions = [
        dict(row, is_current=(row["token_hash"] == mine_hash))
        for row in db.execute(
            """
            SELECT id, token_hash, user_agent, ip, created_at, last_seen_at
            FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC
            """,
            (me["id"],),
        ).fetchall()
    ]
    blocked = db.execute(
        """
        SELECT u.id, u.username, p.name FROM blocks b
        JOIN users u ON u.id = b.blocked_id
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE b.blocker_id = ? ORDER BY b.created_at DESC
        """,
        (me["id"],),
    ).fetchall()
    consent = db.execute(
        "SELECT * FROM consents WHERE user_id = ? AND purpose = ?",
        (me["id"], CONSENT_SENSITIVE),
    ).fetchone()

    return render_template(
        "settings.html",
        me=me,
        sessions=sessions,
        blocked=blocked,
        consent=consent,
        deletion_grace_days=DELETION_GRACE_DAYS,
    )


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    me = current_user()
    current = request.form.get("current", "")
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if not check_password_hash(me["password_hash"], current):
        flash(t("msg.password_wrong"))
    elif password_problem(password, confirm):
        flash(password_problem(password, confirm))
    else:
        db = get_db()
        db.execute(
            "UPDATE users SET password_hash = ?, password_changed_at = NOW() WHERE id = ?",
            (generate_password_hash(password), me["id"]),
        )
        db.commit()
        # Everywhere but here: changing your password should not log you out
        # of the tab you did it in, but it must log out everyone else.
        revoke_user_sessions(me["id"], except_token=session.get("sid"))
        security_event("password_change", "success", user_id=me["id"])
        flash(t("msg.password_changed"))
    return redirect(url_for("settings"))


@app.route("/settings/sessions/<int:session_id>/revoke", methods=["POST"])
@login_required
def revoke_session(session_id):
    db = get_db()
    db.execute(
        "DELETE FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, current_uid()),
    )
    db.commit()
    flash(t("msg.session_revoked"))
    return redirect(url_for("settings"))


@app.route("/settings/sessions/revoke-others", methods=["POST"])
@login_required
def revoke_other_sessions():
    revoke_user_sessions(current_uid(), except_token=session.get("sid"))
    flash(t("msg.sessions_revoked"))
    return redirect(url_for("settings"))


@app.route("/settings/consent", methods=["POST"])
@login_required
def update_consent():
    """Withdraw or re-grant the Article 9 consent.

    Withdrawal has to be as easy as granting, which is why this is one
    button and not a support request. Withdrawing stops the search working,
    because the fields it needs are exactly the ones consent covers.
    """
    grant = bool(request.form.get("grant"))
    db = get_db()
    if grant:
        db.execute(
            """
            INSERT INTO consents (user_id, purpose) VALUES (?, ?)
            ON CONFLICT (user_id, purpose)
            DO UPDATE SET granted_at = NOW(), withdrawn_at = NULL
            """,
            (current_uid(), CONSENT_SENSITIVE),
        )
        flash(t("msg.consent_given"))
    else:
        db.execute(
            "UPDATE consents SET withdrawn_at = NOW() WHERE user_id = ? AND purpose = ?",
            (current_uid(), CONSENT_SENSITIVE),
        )
        db.execute(
            "UPDATE searches SET status = 'cancelled' WHERE user_id = ? AND status = 'waiting'",
            (current_uid(),),
        )
        flash(t("msg.consent_withdrawn"))
    db.commit()
    return redirect(url_for("settings"))


@app.route("/settings/export")
@login_required
def export_data():
    """Everything we hold about the caller, as JSON (GDPR Art. 15 and 20).

    Photo bytes are referenced by URL rather than inlined -- a base64 blob
    per photo would make the file unusable in the machine-readable sense
    Article 20 is asking for.
    """
    me = current_uid()
    db = get_db()

    def rows(sql, params=(me,)):
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    account = dict(
        db.execute(
            """
            SELECT id, username, email, dob, status, created_at,
                   email_verified_at, password_changed_at
            FROM users WHERE id = ?
            """,
            (me,),
        ).fetchone()
    )

    payload = {
        "exported_at": dt.now(timezone.utc).isoformat(),
        "account": account,
        "profile": rows("SELECT * FROM profiles WHERE user_id = ?"),
        "photos": rows(
            "SELECT id, mime, is_primary, created_at FROM photos WHERE user_id = ?"
        ),
        "searches": rows("SELECT * FROM searches WHERE user_id = ?"),
        "matches": rows(
            "SELECT * FROM matches WHERE user_a = ? OR user_b = ?", (me, me)
        ),
        "messages": rows(
            "SELECT id, match_id, body, created_at FROM messages WHERE sender_id = ?"
        ),
        "blocks": rows("SELECT blocked_id, created_at FROM blocks WHERE blocker_id = ?"),
        "reports_filed": rows(
            "SELECT id, reported_id, reason, detail, status, created_at "
            "FROM reports WHERE reporter_id = ?"
        ),
        "consents": rows("SELECT * FROM consents WHERE user_id = ?"),
        "terms_accepted": rows("SELECT * FROM legal_acceptances WHERE user_id = ?"),
    }

    body = json.dumps(payload, indent=2, default=str)
    return Response(
        body,
        mimetype="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="velvt-export.json"',
            "Cache-Control": "no-store",
        },
    )


@app.route("/settings/delete", methods=["POST"])
@login_required
def request_deletion():
    """Schedule deletion, with a grace period (GDPR Art. 17).

    Not immediate: people delete accounts angry, and an irreversible button
    at that moment is a worse experience than a reversible one. The account
    is unreachable to everyone else from this moment either way.
    """
    me = current_user()
    if not check_password_hash(me["password_hash"], request.form.get("password", "")):
        flash(t("msg.confirm_password_delete"))
        return redirect(url_for("settings"))

    db = get_db()
    db.execute(
        """
        UPDATE users SET status = 'pending_deletion', deletion_requested_at = NOW()
        WHERE id = ?
        """,
        (me["id"],),
    )
    db.execute(
        "UPDATE searches SET status = 'cancelled' WHERE user_id = ? AND status = 'waiting'",
        (me["id"],),
    )
    db.execute(
        """
        UPDATE matches SET status = 'ended', ended_at = NOW()
        WHERE (user_a = ? OR user_b = ?) AND status <> 'ended'
        """,
        (me["id"], me["id"]),
    )
    db.commit()
    flash(
        f"Your account is scheduled for deletion in {DELETION_GRACE_DAYS} days. "
        "Sign in before then to cancel."
    )
    return redirect(url_for("settings"))


@app.route("/settings/delete/cancel", methods=["POST"])
@login_required
def cancel_deletion():
    db = get_db()
    db.execute(
        """
        UPDATE users SET status = 'active', deletion_requested_at = NULL
        WHERE id = ? AND status = 'pending_deletion'
        """,
        (current_uid(),),
    )
    db.commit()
    flash(t("msg.reinstated"))
    return redirect(url_for("settings"))


def purge_due_deletions():
    """Erase accounts whose grace period has run out.

    Anonymised in place rather than DELETEd. Every foreign key pointing at
    users cascades, so removing the row would delete the *matches* too, and
    with them the other participant's entire conversation -- their record of
    a relationship, erased because the other person left. Article 17 asks us
    to erase personal data, not to reach into someone else's history.

    So: every field that identifies the person is destroyed, the profile and
    photos go entirely, and what remains is a numbered tombstone that reads
    as "Deleted member" wherever it surfaces. Nothing about it is personal
    data, and nothing can be recovered from it.
    """
    db = get_db()
    due = db.execute(
        """
        SELECT id FROM users
        WHERE status = 'pending_deletion'
          AND deletion_requested_at < NOW() - (? * INTERVAL '1 day')
        """,
        (DELETION_GRACE_DAYS,),
    ).fetchall()

    for row in due:
        uid = row["id"]
        # Everything that is only ever about them.
        for table in ("photos", "searches", "sessions", "email_tokens", "consents",
                      "legal_acceptances"):
            db.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM profiles WHERE user_id = ?", (uid,))
        db.execute(
            "DELETE FROM blocks WHERE blocker_id = ? OR blocked_id = ?", (uid, uid)
        )
        # Their side of any conversation stays readable to the other person,
        # but is no longer attributed to a real account.
        db.execute("UPDATE messages SET sender_id = NULL WHERE sender_id = ?", (uid,))
        db.execute(
            """
            UPDATE matches SET status = 'ended', ended_at = COALESCE(ended_at, NOW())
            WHERE user_a = ? OR user_b = ?
            """,
            (uid, uid),
        )
        db.execute(
            """
            UPDATE users
            SET username = ?, email = NULL, dob = NULL, email_verified_at = NULL,
                age_verified_at = NULL, password_hash = ?, status = 'deleted',
                deletion_requested_at = NULL
            WHERE id = ?
            """,
            (f"deleted_{uid}", secrets.token_hex(32), uid),
        )
    db.commit()
    return len(due)


def purge_expired_data():
    """Enforce the retention schedule above.

    Runs on the same schedule as the deletion purge and reports what it
    touched, so the job's log line is the evidence that retention is a
    thing that happens rather than a thing that is written down.

    Order matters in one place only: messages are deleted before the
    matches that own them, because the foreign key cascades and doing it
    the other way round would make the message count a lie.

    An ended match with an unresolved report against it is left alone. A
    report is a request that someone look at what was said, and expiring
    the evidence while the complaint is open would answer it by losing it.
    """
    db = get_db()
    counts = {}

    kept_open = """
        AND NOT EXISTS (
            SELECT 1 FROM reports r
            WHERE r.match_id = m.id AND r.resolved_at IS NULL
        )
    """

    counts["messages"] = db.execute(
        f"""
        DELETE FROM messages
        WHERE match_id IN (
            SELECT m.id FROM matches m
            WHERE m.status = 'ended'
              AND m.ended_at IS NOT NULL
              AND m.ended_at < NOW() - (? * INTERVAL '1 day')
              {kept_open}
        )
        """,
        (ENDED_MATCH_RETENTION_DAYS,),
    ).rowcount

    counts["matches"] = db.execute(
        f"""
        DELETE FROM matches m
        WHERE m.status = 'ended'
          AND m.ended_at IS NOT NULL
          AND m.ended_at < NOW() - (? * INTERVAL '1 day')
          {kept_open}
        """,
        (ENDED_MATCH_RETENTION_DAYS,),
    ).rowcount

    counts["searches"] = db.execute(
        """
        DELETE FROM searches
        WHERE status IN ('cancelled', 'matched')
          AND created_at < NOW() - (? * INTERVAL '1 day')
        """,
        (RESOLVED_SEARCH_RETENTION_DAYS,),
    ).rowcount

    # Coarsened, not cleared: `location` is the town the searcher typed and
    # stays, so a row with no coordinates at all would still say roughly
    # where they were while losing the ability to say it was approximate.
    counts["coordinates_coarsened"] = db.execute(
        """
        UPDATE searches
        SET lat = ROUND(lat::numeric, ?), lng = ROUND(lng::numeric, ?)
        WHERE (lat IS NOT NULL OR lng IS NOT NULL)
          AND created_at < NOW() - (? * INTERVAL '1 day')
          AND (lat <> ROUND(lat::numeric, ?) OR lng <> ROUND(lng::numeric, ?))
        """,
        (COORDINATE_PLACES, COORDINATE_PLACES, COORDINATE_COARSEN_DAYS,
         COORDINATE_PLACES, COORDINATE_PLACES),
    ).rowcount

    # This one holds IP addresses. It is on the schedule for the same reason
    # everything else is, not exempted for being useful to us.
    counts["security_events"] = db.execute(
        "DELETE FROM security_events WHERE at < NOW() - (? * INTERVAL '1 day')",
        (AUTH_EVENT_RETENTION_DAYS,),
    ).rowcount

    counts["rate_hits"] = db.execute(
        "DELETE FROM rate_hits WHERE window_start < NOW() - (? * INTERVAL '1 day')",
        (RATE_HIT_RETENTION_DAYS,),
    ).rowcount

    counts["reports"] = db.execute(
        """
        DELETE FROM reports
        WHERE resolved_at IS NOT NULL
          AND resolved_at < NOW() - (? * INTERVAL '1 day')
        """,
        (RESOLVED_REPORT_RETENTION_DAYS,),
    ).rowcount

    # Tokens are single-use and short-lived; an expired one is dead weight.
    counts["email_tokens"] = db.execute(
        "DELETE FROM email_tokens WHERE expires_at < NOW() - INTERVAL '1 day'"
    ).rowcount

    counts["sessions"] = db.execute(
        "DELETE FROM sessions WHERE expires_at < NOW()"
    ).rowcount

    db.commit()
    app.logger.info("retention purge: %s",
                    ", ".join(f"{k}={v}" for k, v in counts.items() if v))
    return counts


@app.route("/report/<int:user_id>", methods=["GET", "POST"])
@login_required
@rate_limited("report", limit=20, window_seconds=3600, by="user")
def report_user(user_id):
    """Notice-and-action, per DSA Article 16.

    Deliberately reachable for any account, not only a current match: the
    person you most need to report is often the one who has already ended
    the conversation.
    """
    me = current_uid()
    if user_id == me:
        flash(t("msg.report_self"))
        return redirect(url_for("live_search"))

    subject = get_db().execute(
        """
        SELECT u.id, u.username, p.name FROM users u
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.id = ?
        """,
        (user_id,),
    ).fetchone()
    if subject is None:
        flash(t("msg.no_such_profile"))
        return redirect(url_for("live_search"))

    match_id = request.values.get("match_id", type=int)

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        detail = request.form.get("detail", "").strip()[:2000]
        also_block = bool(request.form.get("block"))

        if reason not in REPORT_REASON_KEYS:
            flash(t("msg.report_reason"))
            return render_template(
                "report.html", subject=subject, reasons=REPORT_REASONS,
                match_id=match_id,
            )

        db = get_db()
        db.execute(
            """
            INSERT INTO reports (reporter_id, reported_id, match_id, reason, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (me, user_id, match_id, reason, detail),
        )
        db.commit()
        security_event("report", "filed", user_id=me,
                       detail=f"against user {user_id}, reason={reason}")

        if also_block:
            apply_block(me, user_id)
            flash(t("msg.report_blocked"))
        else:
            # Article 16 wants the reporter told what happens next, not just
            # that the form submitted.
            flash(t("msg.report_received"))
        return redirect(url_for("live_search"))

    return render_template(
        "report.html", subject=subject, reasons=REPORT_REASONS, match_id=match_id
    )


def apply_block(blocker_id, blocked_id):
    """Block, and end anything currently running between the two."""
    if blocker_id == blocked_id:
        return
    db = get_db()
    db.execute(
        """
        INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)
        ON CONFLICT DO NOTHING
        """,
        (blocker_id, blocked_id),
    )
    a, b = sorted((blocker_id, blocked_id))
    db.execute(
        """
        UPDATE matches SET status = 'ended', ended_at = NOW()
        WHERE user_a = ? AND user_b = ? AND status <> 'ended'
        """,
        (a, b),
    )
    # A waiting search must not immediately re-pair them.
    db.execute(
        "UPDATE searches SET status = 'cancelled' WHERE user_id = ? AND status = 'waiting'",
        (blocker_id,),
    )
    db.commit()


@app.route("/block/<int:user_id>", methods=["POST"])
@login_required
def block_user(user_id):
    apply_block(current_uid(), user_id)
    flash(t("msg.blocked"))
    return redirect(url_for("chats"))


@app.route("/unblock/<int:user_id>", methods=["POST"])
@login_required
def unblock_user(user_id):
    db = get_db()
    db.execute(
        "DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
        (current_uid(), user_id),
    )
    db.commit()
    flash(t("msg.unblocked"))
    return redirect(url_for("settings"))


def log_admin_action(actor_id, target_id, action, reason=""):
    db = get_db()
    db.execute(
        """
        INSERT INTO admin_actions (actor_id, target_id, action, reason)
        VALUES (?, ?, ?, ?)
        """,
        (actor_id, target_id, action, reason),
    )
    db.commit()


@app.route("/admin/members")
@admin_required
def admin_members():
    """Who has actually signed up, and what their profile looks like.

    The landing page deliberately shows a member count only once it is worth
    showing (see landing_pulse()), which leaves nowhere to read the real
    figure. This is that place: the true totals, and every member's profile
    one click away.

    Demo members are counted separately rather than folded in or hidden --
    seeing "40 demo" next to "3 real" is the whole point of the distinction,
    and a total that quietly included them would be the same lie the landing
    page refuses to tell.
    """
    show = request.args.get("show", "real")
    query = (request.args.get("q") or "").strip()

    db = get_db()
    totals = db.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE is_bot = FALSE)                        AS real_all,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND status = 'active')  AS real_active,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND status = 'suspended') AS suspended,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND status = 'banned')  AS banned,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND status = 'pending_deletion') AS pending_deletion,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND status = 'deleted') AS deleted,
          COUNT(*) FILTER (WHERE is_bot = TRUE)                         AS demo,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND created_at >= NOW() - INTERVAL '7 days') AS week,
          COUNT(*) FILTER (WHERE is_bot = FALSE AND created_at >= NOW() - INTERVAL '1 day')  AS today
        FROM users
        """
    ).fetchone()

    # LEFT JOIN: an account can exist before its profile does, and those are
    # exactly the rows worth seeing here -- someone who signed up and stalled.
    rows = db.execute(
        """
        SELECT u.id, u.username, u.email, u.status, u.is_bot,
               u.created_at, u.email_verified_at,
               -- last_seen_at lives on sessions, not users: it is a property
               -- of a signed-in device, and someone can have several.
               (SELECT MAX(se.last_seen_at) FROM sessions se
                  WHERE se.user_id = u.id) AS last_seen_at,
               p.name, p.age, p.gender, p.location,
               (SELECT COUNT(*) FROM photos ph WHERE ph.user_id = u.id) AS photos,
               (SELECT COUNT(*) FROM searches s
                  WHERE s.user_id = u.id AND s.status = 'waiting') AS searching
        FROM users u
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE (? = 'all' OR (? = 'real' AND u.is_bot = FALSE)
                         OR (? = 'demo' AND u.is_bot = TRUE))
          AND (? = '' OR u.username ILIKE ? OR p.name ILIKE ? OR u.email ILIKE ?)
        ORDER BY u.created_at DESC
        LIMIT 500
        """,
        (show, show, show, query, f"%{query}%", f"%{query}%", f"%{query}%"),
    ).fetchall()

    return render_template("admin_members.html", totals=totals, members=rows,
                           show=show, query=query, floor=MEMBER_COUNT_FLOOR)


@app.route("/admin/reports")
@admin_required
def admin_reports():
    show = request.args.get("show", "open")
    rows = get_db().execute(
        """
        SELECT r.*,
               rep.username AS reporter_username,
               sub.username AS reported_username,
               sub.status   AS reported_status,
               subp.name    AS reported_name
        FROM reports r
        LEFT JOIN users rep ON rep.id = r.reporter_id
        JOIN users sub ON sub.id = r.reported_id
        LEFT JOIN profiles subp ON subp.user_id = r.reported_id
        WHERE (? = 'all' OR r.status = ?)
        ORDER BY r.created_at DESC
        LIMIT 200
        """,
        (show, show),
    ).fetchall()

    # The reported message, where the report pointed at a conversation.
    context = {}
    for row in rows:
        if row["match_id"]:
            context[row["id"]] = get_db().execute(
                """
                SELECT m.body, m.created_at, u.username
                FROM messages m JOIN users u ON u.id = m.sender_id
                WHERE m.match_id = ? AND m.sender_id = ?
                ORDER BY m.id DESC LIMIT 5
                """,
                (row["match_id"], row["reported_id"]),
            ).fetchall()

    return render_template(
        "admin_reports.html",
        reports=rows,
        context=context,
        show=show,
        reasons=dict(REPORT_REASONS),
    )


@app.route("/admin/reports/<int:report_id>/resolve", methods=["POST"])
@admin_required
def admin_resolve_report(report_id):
    action = request.form.get("action", "")
    note = request.form.get("note", "").strip()[:1000]

    if action not in ADMIN_ACTIONS:
        flash(t("msg.unknown_action"))
        return redirect(url_for("admin_reports"))

    db = get_db()
    report = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if report is None:
        flash(t("msg.no_such_report"))
        return redirect(url_for("admin_reports"))

    me = current_uid()
    target = report["reported_id"]

    security_event("admin_action", action, user_id=me,
                   detail=f"report {report_id} against user {target}")

    if action in ("suspend", "ban"):
        new_status = "suspended" if action == "suspend" else "banned"
        db.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, target))
        # Kick them out now rather than at their next request.
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target,))
        db.execute(
            "UPDATE searches SET status = 'cancelled' WHERE user_id = ? AND status = 'waiting'",
            (target,),
        )

    db.execute(
        """
        UPDATE reports
        SET status = ?, resolved_by = ?, resolved_at = NOW(),
            resolution = ?, resolution_note = ?
        WHERE id = ?
        """,
        (
            "dismissed" if action == "dismiss" else "actioned",
            me,
            action,
            note,
            report_id,
        ),
    )
    db.commit()
    log_admin_action(me, target, action, note)

    flash(f"Report #{report_id}: {ADMIN_ACTIONS[action]}.")
    return redirect(url_for("admin_reports"))


@app.route("/admin/users/<int:user_id>/reinstate", methods=["POST"])
@admin_required
def admin_reinstate(user_id):
    db = get_db()
    db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    db.commit()
    log_admin_action(current_uid(), user_id, "reinstate")
    flash(t("msg.account_reinstated_admin"))
    return redirect(url_for("admin_reports"))


@app.route("/admin/profiles/new", methods=["GET", "POST"])
@admin_required
def admin_new_profile():
    db = get_db()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}
        # Same pin as the member-facing form -- an admin-created profile has to
        # land in the same city, or it is unmatchable.
        values["location"], _, _ = pinned_place(values["location"])

        error = None
        phys = None
        if not username or len(username) < 3:
            error = t("msg.username_short")
        elif password and len(password) < 8:
            error = t("msg.password_short_optional")
        else:
            error, age = validate_profile(values)
            phys_error, phys = validate_physical(values)
            error = error or phys_error

        if error is None:
            try:
                # Without a password the account can't log in until one
                # is set; with one, the person can sign in right away.
                new_id = db.insert_returning_id(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (
                        username,
                        generate_password_hash(
                            password or secrets.token_urlsafe(32)
                        ),
                    ),
                )
                db.execute(
                    """
                    INSERT INTO profiles
                        (user_id, name, age, gender, seeking, location,
                         height_cm, body_type, fitness_level, hair_color,
                         eye_color, tattoos, bio,
                         interests, hobbies, relationship_type,
                         relationship_preference)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id, values["name"], age, values["gender"],
                        values["seeking"], values["location"],
                        phys["height_cm"], phys["body_type"],
                        phys["fitness_level"], phys["hair_color"],
                        phys["eye_color"], phys["tattoos"],
                        values["bio"],
                        values["interests"], values["hobbies"],
                        values["relationship_type"],
                        values["relationship_preference"],
                    ),
                )
                db.commit()
            except psycopg.errors.UniqueViolation:
                db.rollback()
                error = t("msg.username_taken")
            else:
                flash(f"Profile for {values['name']} (@{username}) created.")
                return redirect(url_for("view_profile", user_id=new_id))

        flash(error)
        profile = dict(values)
        profile["username"] = username
    else:
        profile = {f: "" for f in PROFILE_FIELDS}
        profile["username"] = ""

    chips, chosen = interest_choices(profile.get("interests"))

    return render_template(
        "admin_profile_new.html",
        profile=profile,
        bio_max=BIO_MAX_CHARS,
        interest_chips=chips,
        interest_chosen=chosen,
        interest_max=INTEREST_MAX,
        relationship_types=RELATIONSHIP_TYPES,
        relationship_preferences=RELATIONSHIP_PREFERENCES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
        body_types=BODY_TYPES,
        fitness_levels=FITNESS_LEVELS,
        hair_colors=HAIR_COLORS,
        eye_colors=EYE_COLORS,
        tattoo_levels=TATTOO_LEVELS,
        height_min=HEIGHT_MIN_CM,
        height_max=HEIGHT_MAX_CM,
        city_choices=CITY_CHOICES,
        sample_profile=sample_profile_data(),
    )


def _stem(word):
    """Loosely strip a trailing suffix so near-miss word forms collapse.

    'hiking'/'hiker'/'hike' and 'film'/'films' all reduce to the same stem.
    Deliberately crude (no dictionary) -- good enough for matching interest
    keywords, not for display.
    """
    for suf in ("ing", "ers", "er", "es", "s", "e"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def _tokens(*texts):
    """Split free-text fields into a set of stemmed lowercase keywords.

    Used both by try_pair()'s ranking and by the match reveal, so loosening
    the comparison here (stem instead of exact string) fixes both at once.
    """
    words = set()
    for text in texts:
        for tok in re.split(r"[,;/\n]+|\s+", (text or "").lower()):
            tok = tok.strip(".!?()\"'")
            if len(tok) > 2:
                words.add(_stem(tok))
    return words


def _shared_interest_words(mine_text, other_text):
    """Original-cased words from `mine_text` whose stem overlaps `other_text`.

    Used for display (the reveal names the actual shared interest), while
    `_tokens()` intersections drive ranking/matching elsewhere.
    """
    other_stems = _tokens(other_text)
    seen = set()
    result = []
    for raw in re.split(r"[,;/\n]+|\s+", (mine_text or "")):
        raw = raw.strip()
        if not raw:
            continue
        tok = raw.lower().strip(".!?()\"'")
        if len(tok) <= 2:
            continue
        stem = _stem(tok)
        if stem in other_stems and stem not in seen:
            seen.add(stem)
            result.append(raw)
    return result


def city_coords(location):
    """Look up coordinates for a location string like 'Berlin, Germany'."""
    if not location:
        return None
    key = location.split(",")[0].strip().lower()
    return CITY_COORDS.get(key)


def pinned_place(posted_location="", posted_lat=None, posted_lng=None):
    """Resolve the location a submission should be stored with.

    While SINGLE_CITY is set this ignores the form entirely and returns the
    pinned city with its own coordinates -- the field is not rendered, so
    anything arriving under those names is either a stale draft or someone
    posting by hand. Returns (location, lat, lng).
    """
    if SINGLE_CITY:
        lat, lng = CITY_COORDS[SINGLE_CITY.lower()]
        return SINGLE_CITY, lat, lng
    return posted_location, posted_lat, posted_lng


def distance_km(loc_a, loc_b):
    """Great-circle distance between two location strings, or None."""
    a, b = city_coords(loc_a), city_coords(loc_b)
    if a is None or b is None:
        return None

    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def search_coords(search):
    """Coordinates for a `searches` row: the geocoded lat/lng when the
    location was picked from /api/places suggestions, else the hardcoded
    CITY_COORDS fallback. Lets distance filtering work for any city on
    earth, not just the ~27 seeded ones.
    """
    lat, lng = search.get("lat"), search.get("lng")
    if lat is not None and lng is not None:
        return (lat, lng)
    return city_coords(search.get("location"))


def search_distance_km(s1, s2):
    """Great-circle distance between two `searches` rows, or None."""
    a, b = search_coords(s1), search_coords(s2)
    if a is None or b is None:
        return None

    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def physical_ok(searcher, candidate):
    """True when a candidate's physical traits satisfy the searcher's step-3 filters.

    Each filter only blocks when the searcher set it AND the candidate has a
    value for that attribute — an unset filter or an unset candidate
    attribute is treated as "no preference", same convention as gender/age.

    The whole block is behind one switch (searches.use_physical), so a
    searcher can widen their net without losing the values behind it.
    """
    if not searcher.get("use_physical", True):
        return True

    h_min, h_max = searcher.get("pref_height_min"), searcher.get("pref_height_max")
    if h_min is not None and h_max is not None and candidate.get("height_cm") is not None:
        if not h_min <= candidate["height_cm"] <= h_max:
            return False

    body_types = (searcher.get("pref_body_types") or "").strip()
    if body_types and candidate.get("body_type"):
        if candidate["body_type"] not in body_types.split(","):
            return False

    for field in ("fitness_level", "hair_color", "eye_color", "tattoos"):
        pref = searcher.get("pref_" + field)
        val = candidate.get(field)
        if pref and val and pref != val:
            return False

    return True


def physical_summary(search):
    """One human-readable line for whatever physical filters are set.

    Empty string when none are — the caller decides what to say in that
    case, since "no preferences" reads differently on a review row than it
    does in a form.
    """
    parts = []
    h_min, h_max = search.get("pref_height_min"), search.get("pref_height_max")
    if h_min is not None and h_max is not None:
        parts.append(f"{h_min}–{h_max} cm")

    body_types = (search.get("pref_body_types") or "").strip()
    if body_types:
        parts.append(body_types.replace(",", ", "))

    for field in ("pref_fitness_level", "pref_hair_color", "pref_eye_color", "pref_tattoos"):
        if search.get(field):
            parts.append(search[field])

    return " · ".join(parts)


def searches_compatible(s1, s2):
    """True when two live searches satisfy each other's criteria.

    Both directions must hold: each person's gender must be one the other
    is looking for, each person's age must fall inside the other's
    requested range, each person's physical traits must satisfy the
    other's step-3 filters, and the distance between them must sit inside
    both radii. Relationship type (a CSV -- a searcher can want more than
    one kind of connection) only blocks when both named at least one and
    share none. Interests, when set, requires at least one shared (stemmed)
    keyword. Unset fields are treated as "no preference".

    Each side can also switch a filter off (searches.use_gender/use_age/
    use_relationship/use_distance/use_physical), which relaxes only that side's own
    check — the other person's filter still applies, so disabling one
    filter does not by itself guarantee a match. Missing keys (hand-built
    dicts, pre-migration rows) default to "on" via .get(key, True), which
    matches the column's own DEFAULT TRUE. Interests has no use_* column —
    an empty interests string (the toggle off on screen 2, or never filled
    in) already reads as "no preference", so there is nothing to disable.
    """

    def gender_ok(searcher, candidate_gender):
        if not searcher.get("use_gender", True):
            return True
        if not searcher["seeking"] or not candidate_gender:
            return True
        return candidate_gender in SEEKING_MATCHES[searcher["seeking"]]

    def age_ok(searcher, candidate_age):
        if not searcher.get("use_age", True):
            return True
        if candidate_age is None:
            return True
        return searcher["age_min"] <= candidate_age <= searcher["age_max"]

    def interests_ok(searcher, candidate_interests):
        # Empty interests means "no preference" -- same convention as the
        # other filters, and how a searcher who left this blank (or
        # switched it off, which stores '') already reads. That "no
        # preference" reading has to apply from either side: a candidate
        # who never filled in interests has none to share by definition,
        # so treat their blank field the same as the searcher's own blank
        # field rather than an automatic non-match. Only require overlap
        # when both sides actually listed something, judged the same way
        # try_pair()'s ranking does (stemmed tokens, so near-misses like
        # "hiking"/"hike" still count).
        if not searcher.get("interests") or not candidate_interests:
            return True
        return bool(_tokens(searcher["interests"]) & _tokens(candidate_interests))

    if not (gender_ok(s1, s2["gender"]) and gender_ok(s2, s1["gender"])):
        return False
    if not (age_ok(s1, s2["age"]) and age_ok(s2, s1["age"])):
        return False
    if not (
        interests_ok(s1, s2.get("interests"))
        and interests_ok(s2, s1.get("interests"))
    ):
        return False
    if not (physical_ok(s1, s2) and physical_ok(s2, s1)):
        return False
    if s1.get("use_relationship", True) and s2.get("use_relationship", True):
        # relationship_type is a CSV now -- a searcher can want more than
        # one kind of connection -- so "differ" becomes "share nothing".
        # Symmetric, like the flag check above it, so one call covers both
        # directions rather than the two separate _ok(searcher, candidate)
        # calls gender/age/interests each need.
        t1 = {t.strip() for t in (s1["relationship_type"] or "").split(",") if t.strip()}
        t2 = {t.strip() for t in (s2["relationship_type"] or "").split(",") if t.strip()}
        if t1 and t2 and not (t1 & t2):
            return False

    # Distance must fit inside both people's radius. An unknown city or a
    # radius at the maximum means "anywhere". A side with use_distance off
    # is simply skipped from the per-searcher loop below.
    gap = search_distance_km(s1, s2)
    if gap is not None:
        for search in (s1, s2):
            if not search.get("use_distance", True):
                continue
            if search["radius_km"] < RADIUS_MAX_KM and gap > search["radius_km"]:
                return False
    return True


def try_pair(user_id):
    """Pair this searcher with a waiting, mutually-compatible one.

    Returns the match id when a pair is formed (or already was), else None.

    A search only becomes eligible once it has been running for
    MIN_SEARCH_SECONDS. Without that, a compatible partner already in the
    pool pairs on the very first attempt and the searcher is thrown into a
    chat before the waiting screen has drawn a frame -- the app looks like
    it is handing out canned matches rather than looking for one. The gate
    applies to both sides (this searcher and the candidates), so being the
    second one to arrive does not skip the wait either.

    Pairing is serialized with a Postgres advisory lock rather than an
    in-process one, so two searchers cannot claim the same partner even
    when they are being served by different instances. The lock is held
    for the transaction and released by the commit/rollback below.
    """
    db = get_db()

    db.execute("SELECT pg_advisory_xact_lock(?)", (PAIRING_LOCK_KEY,))
    try:
        mine = db.execute(
            """
            SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos,
                   s.created_at <= NOW() - (? * INTERVAL '1 second') AS ripe
            FROM searches s
            JOIN profiles p ON p.user_id = s.user_id
            WHERE s.user_id = ?
            """,
            (MIN_SEARCH_SECONDS, user_id),
        ).fetchone()

        if mine is None:
            db.commit()
            return None
        if mine["status"] == "matched":
            db.commit()
            return mine["match_id"]
        if mine["status"] != "waiting":
            db.commit()
            return None
        if not mine["ripe"]:
            db.commit()
            return None

        others = db.execute(
            f"""
            SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
            JOIN profiles p ON p.user_id = s.user_id
            JOIN users u ON u.id = s.user_id
            WHERE s.status = 'waiting' AND s.user_id != ?
              AND s.created_at <= NOW() - (? * INTERVAL '1 second')
              {CANDIDATE_ELIGIBLE_SQL}
              {NOT_BLOCKED_SQL}
            ORDER BY s.created_at
            """,
            (user_id, MIN_SEARCH_SECONDS, user_id, user_id),
        ).fetchall()

        best = None
        my_words = _tokens(mine["interests"])
        for other in others:
            if not searches_compatible(mine, other):
                continue
            # Tie-break on shared interests, then longest wait (query order).
            overlap = len(my_words & _tokens(other["interests"]))
            if best is None or overlap > best[0]:
                best = (overlap, other)

        if best is None:
            db.commit()
            return None

        partner_id = best[1]["user_id"]
        a, b = sorted((user_id, partner_id))
        existing = db.execute(
            "SELECT id FROM matches WHERE user_a = ? AND user_b = ?", (a, b)
        ).fetchone()
        if existing:
            matched_id = existing["id"]
        else:
            # status='timed' + paired_at kicks off the reveal/timed-chat/
            # decision lifecycle in match_phase() — only live-search pairs
            # go through it; /find's create_match() leaves the 'active'
            # default alone.
            matched_id = db.insert_returning_id(
                "INSERT INTO matches (user_a, user_b, status, paired_at) VALUES (?, ?, 'timed', NOW())",
                (a, b),
            )

        db.execute(
            "UPDATE searches SET status = 'matched', match_id = ? WHERE user_id IN (?, ?)",
            (matched_id, user_id, partner_id),
        )
        db.commit()
        return matched_id
    except Exception:
        db.rollback()
        raise


def require_profile():
    """Return the caller's profile, or None if it still needs filling in."""
    me = get_db().execute(
        "SELECT * FROM profiles WHERE user_id = ?", (current_uid(),)
    ).fetchone()
    return me if me is not None and me["name"] else None


# What a profile must have before it can go live-searching, and what merely
# makes it better. The gate is deliberately short: five minutes of
# conversation with someone whose profile is blank is the experience this
# stops, but a wall of required fields between signing up and the app is a
# different way to lose the same person.
PROFILE_REQUIRED = (
    ("name", "A name to go by"),
    ("age", "Your age"),
    ("gender", "Your gender"),
    ("seeking", "Who you're looking for"),
    ("__photo__", "One photo"),
)

PROFILE_OPTIONAL = (
    ("bio", "A line about you"),
    ("location", "Where you are"),
    ("interests", "A few interests"),
    ("hobbies", "What you do for fun"),
    ("relationship_type", "What you're looking for"),
)


def profile_completeness(user_id, profile=None):
    """What this profile has, what it is missing, and how far along it is.

    One function behind both the gate and the meter, so the list of things
    the meter nags about can never drift from the list the gate enforces.
    """
    db = get_db()
    if profile is None:
        profile = db.execute(
            "SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    has_photo = db.execute(
        "SELECT 1 AS hit FROM photos WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()

    def filled(field):
        if field == "__photo__":
            return has_photo is not None
        if profile is None:
            return False
        value = profile[field] if field in profile.keys() else None
        return bool(str(value).strip()) if value is not None else False

    missing = [label for field, label in PROFILE_REQUIRED if not filled(field)]
    done = [label for field, label in PROFILE_OPTIONAL if filled(field)]
    todo = [label for field, label in PROFILE_OPTIONAL if not filled(field)]

    total = len(PROFILE_REQUIRED) + len(PROFILE_OPTIONAL)
    have = (len(PROFILE_REQUIRED) - len(missing)) + len(done)
    return {
        "missing": missing,          # blocks searching
        "suggestions": todo,         # merely encouraged
        "ready": not missing,
        "percent": round(have * 100 / total),
    }


def unverified_email_block():
    """Why the caller can't start a search yet, or None.

    Verification gates searching rather than signing in: someone whose
    address bounced still needs to reach settings to fix it. And it only
    applies once mail is actually configured, so a deployment with no
    provider does not lock everyone out of the feature the app exists for.
    """
    if not RESEND_API_KEY:
        return None
    me = current_user()
    if me is not None and me["email"] and me["email_verified_at"] is None:
        return "Confirm your email address before you start searching."
    return None


def save_search(
    user_id, *, seeking, age_min, age_max, relationship_type, interests,
    location, lat, lng, radius_km,
    pref_height_min, pref_height_max, pref_body_types, pref_fitness_level,
    pref_hair_color, pref_eye_color, pref_tattoos,
    use_gender, use_age, use_distance, use_physical,
):
    """Upsert one user's live-search row and mark it 'waiting'.

    Shared by the criteria screen and the "just start searching" escape
    hatch on screen 1, which calls this with the column defaults instead
    of the values a completed screen 2 would have produced.
    """
    db = get_db()
    db.execute(
        """
        INSERT INTO searches
            (user_id, seeking, age_min, age_max, relationship_type,
             interests, location, lat, lng, radius_km,
             pref_height_min, pref_height_max, pref_body_types,
             pref_fitness_level, pref_hair_color, pref_eye_color,
             pref_tattoos, use_gender, use_age, use_distance,
             use_physical, status, match_id, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'waiting', NULL, NOW(), NOW())
        ON CONFLICT(user_id) DO UPDATE SET
            seeking = excluded.seeking,
            age_min = excluded.age_min,
            age_max = excluded.age_max,
            relationship_type = excluded.relationship_type,
            interests = excluded.interests,
            location = excluded.location,
            lat = excluded.lat,
            lng = excluded.lng,
            radius_km = excluded.radius_km,
            pref_height_min = excluded.pref_height_min,
            pref_height_max = excluded.pref_height_max,
            pref_body_types = excluded.pref_body_types,
            pref_fitness_level = excluded.pref_fitness_level,
            pref_hair_color = excluded.pref_hair_color,
            pref_eye_color = excluded.pref_eye_color,
            pref_tattoos = excluded.pref_tattoos,
            -- The switches are explicit user intent now -- the criteria
            -- screen asks which filters matter -- so they are written from
            -- the caller rather than forced back on. use_relationship
            -- stays on: it *is* the connection type picked on screen 1,
            -- which has no switch of its own.
            use_gender = excluded.use_gender,
            use_age = excluded.use_age,
            use_relationship = TRUE,
            use_distance = excluded.use_distance,
            use_physical = excluded.use_physical,
            status = 'waiting',
            match_id = NULL,
            created_at = NOW(),
            last_seen = NOW()
        """,
        (
            user_id, seeking, age_min, age_max, relationship_type, interests,
            location, lat, lng, radius_km,
            pref_height_min, pref_height_max, pref_body_types,
            pref_fitness_level, pref_hair_color, pref_eye_color, pref_tattoos,
            use_gender, use_age, use_distance, use_physical,
        ),
    )
    db.commit()


def touch_search(user_id):
    """Mark this searcher as still here.

    Called from every request the waiting screen makes -- the page itself
    and both of its polls -- so the heartbeat survives a poll failing or a
    tab being reloaded. Scoped to 'waiting' rows so it can never resurrect
    a cancelled or matched search.
    """
    db = get_db()
    db.execute(
        "UPDATE searches SET last_seen = NOW() WHERE user_id = ? AND status = 'waiting'",
        (user_id,),
    )
    db.commit()


@app.route("/search", methods=["GET", "POST"])
@login_required
def live_search():
    """The live-search wizard: six questions, one per step, then search.

    Every step lives in one page and one form — the stepping is done in the
    browser (templates/search_start.html) so moving between questions is
    instant rather than a page load per answer. That means this handler still
    receives one complete form and validates it in one place.

    Distance is deliberately not asked: the search is saved at the maximum
    radius, which searches_compatible() reads as "anywhere". Other people's
    own distance filters still apply to you, which is why the place is still
    worth collecting.
    """
    blocked = unverified_email_block()
    if blocked:
        flash(blocked)
        return redirect(url_for("settings"))

    me = require_profile()
    if me is None:
        flash(t("msg.fill_profile_first"))
        return redirect(url_for("edit_profile"))

    # A profile with nothing in it is somebody the person on the other side
    # of a five-minute conversation has nothing to look at.
    state = profile_completeness(current_uid(), me)
    if not state["ready"]:
        flash(t("msg.profile_missing", items=", ".join(state["missing"]).lower()))
        return redirect(url_for("edit_profile"))

    # How a match works is the most unusual thing about this app and, until
    # now, the one thing nobody was told before it happened to them. Shown
    # once, remembered on the account rather than in the session so it does
    # not reappear on a second device.
    if request.method == "GET" and not current_user()["match_intro_seen_at"]:
        return redirect(url_for("how_matching_works"))

    if request.method == "POST":
        wanted = clean_relationship_types(",".join(request.form.getlist("relationship_type")))
        seeking = request.form.get("seeking", "")
        interests = clean_interests(request.form.get("interests", ""))
        location = request.form.get("location", "").strip()

        # Set only when the combobox resolved a geocoder pick; its JS clears
        # both the moment the user free-types again, so a stale coordinate can
        # never be paired with a different typed city.
        lat = lng = None
        raw_lat = request.form.get("location_lat", "").strip()
        raw_lng = request.form.get("location_lng", "").strip()
        if raw_lat and raw_lng:
            try:
                cand_lat, cand_lng = float(raw_lat), float(raw_lng)
                if -90 <= cand_lat <= 90 and -180 <= cand_lng <= 180:
                    lat, lng = cand_lat, cand_lng
            except ValueError:
                pass

        # Pinned city wins over anything posted (the step is not rendered).
        location, lat, lng = pinned_place(location, lat, lng)

        # Left at the full span, the slider is saying "no preference" rather
        # than "18 to 39": AGE_MAX_YEARS is the slider's own ceiling, so a
        # range that reaches it cannot be expressing an upper bound. That has
        # to switch use_age off, otherwise anyone older than the ceiling would
        # be filtered out by a range the searcher never actually narrowed.
        try:
            age_min = int(request.form.get("age_min", AGE_MIN_YEARS))
            age_max = int(request.form.get("age_max", AGE_MAX_YEARS))
        except ValueError:
            age_min, age_max = AGE_MIN_YEARS, AGE_MAX_YEARS
        age_min = max(AGE_MIN_YEARS, min(age_min, AGE_MAX_YEARS))
        age_max = max(AGE_MIN_YEARS, min(age_max, AGE_MAX_YEARS))
        if age_min > age_max:
            age_min, age_max = age_max, age_min
        use_age = not (age_min == AGE_MIN_YEARS and age_max == AGE_MAX_YEARS)

        # Body type is the only physical filter the wizard asks about; the
        # rest keep the "no preference" shape validate_physical() produces
        # from a blank form, and stay editable on the criteria screen.
        _, phys = validate_physical({})
        body_types = [b for b in request.form.getlist(PREF_BODY_TYPES_FIELD)
                      if b in BODY_TYPES]

        error = None
        if not wanted:
            error = t("msg.choose_connection")
        elif seeking not in SEEKING_OPTIONS:
            error = t("msg.choose_seeking")

        if error:
            flash(error)
        else:
            save_search(
                current_uid(), seeking=seeking,
                age_min=age_min, age_max=age_max,
                relationship_type=wanted, interests=interests,
                location=location, lat=lat, lng=lng,
                radius_km=RADIUS_MAX_KM,
                pref_height_min=phys["pref_height_min"],
                pref_height_max=phys["pref_height_max"],
                pref_body_types=",".join(body_types),
                pref_fitness_level=phys["pref_fitness_level"],
                pref_hair_color=phys["pref_hair_color"],
                pref_eye_color=phys["pref_eye_color"],
                pref_tattoos=phys["pref_tattoos"],
                use_gender=True, use_age=use_age, use_distance=True,
                use_physical=bool(body_types),
            )
            session.pop("search_draft", None)

            # No try_pair() here: the search is brand new, so it cannot be
            # paired yet anyway (see MIN_SEARCH_SECONDS). The waiting page's
            # poll picks it up once it ripens.
            return redirect(url_for("search_waiting"))

    existing = get_db().execute(
        "SELECT * FROM searches WHERE user_id = ?", (current_uid(),)
    ).fetchone()

    return render_template(
        "search_start.html",
        me=me,
        relationship_types=RELATIONSHIP_TYPES,
        existing_relationship_types=(
            (existing["relationship_type"] or "").split(",") if existing else []
        ),
        seeking_options=SEEKING_OPTIONS,
        age_min_bound=AGE_MIN_YEARS,
        age_max_bound=AGE_MAX_YEARS,
        body_types=BODY_TYPES,
        interest_common=INTEREST_COMMON,
        interest_all=INTEREST_SUGGESTIONS,
        interest_max=INTEREST_MAX,
        interest_chosen=[
            p.strip() for p in ((existing["interests"] if existing else "") or "").split(",")
            if p.strip()
        ],
        existing=existing,
        existing_body_types=(
            (existing[PREF_BODY_TYPES_FIELD] or "").split(",") if existing else []
        ),
        draft=session.get("search_draft") or {},
        city_choices=CITY_CHOICES,
    )


@app.route("/search/criteria", methods=["GET", "POST"])
@login_required
def search_criteria():
    """Screen 2: which filters matter, and what they're set to — then search.

    Location, radius and the connection type were decided on screen 1 and
    ride along as hidden fields, so this handler still reads one complete
    form and the validation below is unchanged.
    """
    db = get_db()
    user_id = current_uid()
    blocked = unverified_email_block()
    if blocked:
        flash(blocked)
        return redirect(url_for("settings"))

    me = require_profile()
    if me is None:
        flash(t("msg.fill_profile_first"))
        return redirect(url_for("edit_profile"))

    wanted = clean_relationship_types(request.values.get("relationship_type", ""))
    if not wanted:
        return redirect(url_for("live_search"))

    existing = db.execute(
        "SELECT * FROM searches WHERE user_id = ?", (user_id,)
    ).fetchone()

    if request.method == "POST":
        seeking = request.form.get("seeking", "")
        interests = clean_interests(request.form.get("interests", ""))
        location = request.form.get("location", "").strip()

        # Set only when the combobox on screen 1 resolved a geocoder pick; the
        # JS clears these two fields the moment the user free-types after
        # selecting, so a stale coordinate can never be paired with a
        # different typed city.
        lat = lng = None
        raw_lat = request.form.get("location_lat", "").strip()
        raw_lng = request.form.get("location_lng", "").strip()
        if raw_lat and raw_lng:
            try:
                cand_lat, cand_lng = float(raw_lat), float(raw_lng)
                if -90 <= cand_lat <= 90 and -180 <= cand_lng <= 180:
                    lat, lng = cand_lat, cand_lng
            except ValueError:
                pass

        # Pinned city wins over anything posted (the step is not rendered).
        location, lat, lng = pinned_place(location, lat, lng)

        error = None
        if seeking and seeking not in SEEKING_OPTIONS:
            error = t("msg.choose_seeking")

        try:
            age_min = int(request.form.get("age_min", AGE_MIN_YEARS))
            age_max = int(request.form.get("age_max", AGE_MAX_YEARS))
            radius_km = int(request.form.get("radius_km", RADIUS_MAX_KM))
        except ValueError:
            error = t("msg.check_age_radius")
            age_min, age_max, radius_km = AGE_MIN_YEARS, AGE_MAX_YEARS, RADIUS_MAX_KM

        if error is None:
            if not AGE_MIN_YEARS <= age_min <= age_max <= AGE_MAX_YEARS:
                error = f"Age range must run from {AGE_MIN_YEARS} up to {AGE_MAX_YEARS}."
            elif not 1 <= radius_km <= RADIUS_MAX_KM:
                error = f"Radius must be between 1 and {RADIUS_MAX_KM} km."

        phys = {}
        if error is None:
            phys_values = dict(request.form)
            phys_values[PREF_BODY_TYPES_FIELD] = ",".join(
                request.form.getlist(PREF_BODY_TYPES_FIELD)
            )
            phys_error, phys = validate_physical(phys_values)
            error = error or phys_error

        # The switches on the criteria screen. A switch that is off leaves its
        # panel's inputs disabled, so those fields never reach us and the
        # validation above quietly falls back to its "no preference" defaults —
        # but the flag is what actually relaxes the check in
        # searches_compatible(), and it has to be stored either way.
        use_gender = "use_gender" in request.form
        use_age = "use_age" in request.form
        use_distance = "use_distance" in request.form
        use_physical = "use_physical" in request.form

        if error:
            flash(error)
        else:
            save_search(
                user_id, seeking=seeking, age_min=age_min, age_max=age_max,
                relationship_type=wanted, interests=interests,
                location=location, lat=lat, lng=lng, radius_km=radius_km,
                pref_height_min=phys["pref_height_min"],
                pref_height_max=phys["pref_height_max"],
                pref_body_types=phys[PREF_BODY_TYPES_FIELD],
                pref_fitness_level=phys["pref_fitness_level"],
                pref_hair_color=phys["pref_hair_color"],
                pref_eye_color=phys["pref_eye_color"],
                pref_tattoos=phys["pref_tattoos"],
                use_gender=use_gender, use_age=use_age,
                use_distance=use_distance, use_physical=use_physical,
            )
            # The draft has been saved for real; leaving it behind would let a
            # later visit to screen 1 prefill from a search already underway.
            session.pop("search_draft", None)

            # No try_pair() here: the search is brand new, so it cannot be
            # paired yet anyway (see MIN_SEARCH_SECONDS). The waiting page's
            # poll picks it up once it ripens.
            return redirect(url_for("search_waiting"))

    # Screen 1's answers, carried as hidden fields so this page still posts one
    # complete form. The draft wins over the saved row, which is only a
    # fallback for landing here directly (a bookmark, or a browser back).
    draft = session.get("search_draft") or {}
    if SINGLE_CITY:
        # Nothing upstream can have chosen anything else, so don't let a stale
        # draft or an old row show a place this search will not be saved with.
        pinned, pin_lat, pin_lng = pinned_place()
        place = {"location": pinned, "lat": pin_lat, "lng": pin_lng}
    else:
        place = {
            "location": draft.get("location")
                or (existing["location"] if existing else "")
                or me["location"],
            "lat": draft.get("location_lat")
                or (existing["lat"] if existing and existing["lat"] is not None else ""),
            "lng": draft.get("location_lng")
                or (existing["lng"] if existing and existing["lng"] is not None else ""),
        }
    try:
        place["radius_km"] = int(
            draft.get("radius_km")
            or (existing["radius_km"] if existing else RADIUS_MAX_KM)
        )
    except (TypeError, ValueError):
        place["radius_km"] = RADIUS_MAX_KM

    return render_template(
        "search_criteria.html",
        me=me,
        existing=existing,
        wanted=wanted,
        place=place,
        seeking_options=SEEKING_OPTIONS,
        city_choices=CITY_CHOICES,
        radius_max=RADIUS_MAX_KM,
        body_types=BODY_TYPES,
        fitness_levels=FITNESS_LEVELS,
        hair_colors=HAIR_COLORS,
        eye_colors=EYE_COLORS,
        tattoo_levels=TATTOO_LEVELS,
        height_min=HEIGHT_MIN_CM,
        height_max=HEIGHT_MAX_CM,
        age_min_bound=AGE_MIN_YEARS,
        age_max_bound=AGE_MAX_YEARS,
    )


# Small TTL cache so repeated keystrokes (and repeated users typing the same
# city) don't each hit the geocoder. Capped so a burst of unique queries
# can't grow this unboundedly across a long-running instance.
_PLACES_CACHE = {}
_PLACES_CACHE_TTL = 600
_PLACES_CACHE_MAX = 500


@app.route("/api/places")
@rate_limited("places", limit=60, window_seconds=60, include_safe=True)
@login_required
def api_places():
    """Typeahead suggestions for the location field, backed by Photon
    (an OSM geocoder built for per-keystroke autocomplete, unlike Nominatim
    which asks callers not to hit it that way).

    Always returns 200 with a (possibly empty) list — a geocoder outage or
    timeout must not break the location field, which still accepts free
    text with the CITY_CHOICES datalist as an offline fallback.
    """
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return {"results": []}

    key = q.lower()
    cached = _PLACES_CACHE.get(key)
    if cached and time.time() - cached[0] < _PLACES_CACHE_TTL:
        return {"results": cached[1]}

    results = []
    try:
        resp = requests.get(
            "https://photon.komoot.io/api/",
            params={"q": q, "limit": 6, "lang": "en"},
            headers={"User-Agent": "Velvet dating app (dev) - location autocomplete"},
            timeout=5,
        )
        resp.raise_for_status()
        payload = resp.json()
        place_kinds = {"city", "town", "village", "hamlet", "state", "country", "county"}
        for feat in payload.get("features", []):
            props = feat.get("properties", {})
            if props.get("osm_value") not in place_kinds and props.get("osm_key") != "place":
                continue
            coords = (feat.get("geometry") or {}).get("coordinates")
            if not coords or len(coords) != 2:
                continue
            lng, lat = coords
            parts = [props.get("name")]
            for extra in ("state", "country"):
                if props.get(extra) and props[extra] not in parts:
                    parts.append(props[extra])
            label = ", ".join(p for p in parts if p)
            if label:
                results.append({"label": label, "lat": lat, "lng": lng})
    except (requests.RequestException, ValueError):
        results = []

    if len(_PLACES_CACHE) > _PLACES_CACHE_MAX:
        _PLACES_CACHE.clear()
    _PLACES_CACHE[key] = (time.time(), results)
    return {"results": results}


@app.route("/search/preview", methods=["POST"])
@login_required
def search_preview():
    """Live pool readout for the criteria screen — how many people fit the
    criteria you're about to save, plus suggestions if the answer is zero.

    Writes nothing: builds a synthetic search row in the exact shape
    searches_compatible() expects and reuses the existing engine as-is, so
    the count and suggestions here are guaranteed consistent with what
    /search/waiting will show after you actually start searching.
    """
    blocked = unverified_email_block()
    if blocked:
        return {"error": blocked}, 400

    me = require_profile()
    if me is None:
        return {"error": "profile incomplete"}, 400

    wanted = clean_relationship_types(request.form.get("relationship_type", ""))
    if not wanted:
        return {"error": "invalid relationship_type"}, 400

    seeking = request.form.get("seeking", "")
    location = request.form.get("location", "").strip()
    try:
        lat = float(request.form.get("location_lat", "")) if request.form.get("location_lat") else None
        lng = float(request.form.get("location_lng", "")) if request.form.get("location_lng") else None
    except ValueError:
        lat = lng = None

    # Same pin the real save applies, so the preview count cannot be computed
    # against a place the saved search will not actually use.
    location, lat, lng = pinned_place(location, lat, lng)

    try:
        age_min = int(request.form.get("age_min", AGE_MIN_YEARS))
        age_max = int(request.form.get("age_max", AGE_MAX_YEARS))
        radius_km = int(request.form.get("radius_km", RADIUS_MAX_KM))
    except ValueError:
        return {"error": "invalid age or radius"}, 400

    phys_values = dict(request.form)
    phys_values[PREF_BODY_TYPES_FIELD] = ",".join(request.form.getlist(PREF_BODY_TYPES_FIELD))
    _phys_error, phys = validate_physical(phys_values)

    mine = {
        "user_id": current_uid(),
        "seeking": seeking,
        "age_min": age_min,
        "age_max": age_max,
        "relationship_type": wanted,
        "interests": request.form.get("interests", "").strip(),
        "location": location,
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        # The switches on the criteria screen post like any other checkbox, so
        # the preview counts what the user is actually about to save rather
        # than assuming every filter applies.
        "use_gender": "use_gender" in request.form,
        "use_age": "use_age" in request.form,
        "use_relationship": True,
        "use_distance": "use_distance" in request.form,
        "use_physical": "use_physical" in request.form,
        "gender": me["gender"],
        "age": me["age"],
        "height_cm": me["height_cm"],
        "body_type": me["body_type"],
        "fitness_level": me["fitness_level"],
        "hair_color": me["hair_color"],
        "eye_color": me["eye_color"],
        "tattoos": me["tattoos"],
        "pref_height_min": phys["pref_height_min"],
        "pref_height_max": phys["pref_height_max"],
        "pref_body_types": phys[PREF_BODY_TYPES_FIELD],
        "pref_fitness_level": phys["pref_fitness_level"],
        "pref_hair_color": phys["pref_hair_color"],
        "pref_eye_color": phys["pref_eye_color"],
        "pref_tattoos": phys["pref_tattoos"],
    }

    others = get_db().execute(
        f"""
        SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        JOIN users u ON u.id = s.user_id
        WHERE s.status = 'waiting' AND s.user_id != ?
          {CANDIDATE_ELIGIBLE_SQL}
          {NOT_BLOCKED_SQL}
        """,
        (current_uid(), current_uid(), current_uid()),
    ).fetchall()
    others = [dict(o) for o in others]

    blockers = search_blockers(mine, others)
    suggestions = []
    if blockers.get("age_suggestion"):
        suggestions.append({"key": "age", **blockers["age_suggestion"]})
    if blockers.get("distance_suggestion"):
        suggestions.append({"key": "distance", **blockers["distance_suggestion"]})
    for rs in blockers.get("relationship_suggestions", [])[:1]:
        suggestions.append({"key": "relationship", **rs})
    for gs in blockers.get("gender_suggestions", [])[:1]:
        suggestions.append({"key": "gender", **gs})

    return {
        "total_waiting": len(others),
        "compatible_count": blockers.get("current_count", 0),
        "suggestions": suggestions,
    }


def _minimal_age_suggestion(mine, others):
    """Smallest age-range widening that admits at least one waiting person.

    For each candidate, the minimal range that would include them is
    (min(my_lo, their_age), max(my_hi, their_age)) — widening any less
    still excludes them, so this is the least possible change per
    candidate. The smallest such span across all candidates is reported,
    but only if it is verified compatible on every OTHER filter too, via
    a real searches_compatible() call rather than by assumption.
    """
    best = None
    for o in others:
        cand_age = o["age"]
        if cand_age is None:
            continue
        lo = min(mine["age_min"], cand_age)
        hi = max(mine["age_max"], cand_age)
        if lo == mine["age_min"] and hi == mine["age_max"]:
            continue  # already inside range; some other filter is blocking them
        trial = dict(mine)
        trial["age_min"], trial["age_max"] = lo, hi
        if not searches_compatible(trial, o):
            continue
        span = hi - lo
        if best is None or span < best[0]:
            best = (span, lo, hi)

    if best is None:
        return None
    _, lo, hi = best
    trial = dict(mine)
    trial["age_min"], trial["age_max"] = lo, hi
    count = sum(1 for o in others if searches_compatible(trial, o))
    return {"age_min": lo, "age_max": hi, "count": count}


def _minimal_distance_suggestion(mine, others):
    """Smallest radius that admits at least one waiting person, verified
    the same way as the age suggestion above."""
    best = None
    for o in others:
        gap = search_distance_km(mine, o)
        if gap is None or gap <= mine["radius_km"]:
            continue
        radius = min(math.ceil(gap), RADIUS_MAX_KM)
        trial = dict(mine)
        trial["radius_km"] = radius
        if not searches_compatible(trial, o):
            continue
        if best is None or radius < best:
            best = radius

    if best is None:
        return None
    trial = dict(mine)
    trial["radius_km"] = best
    count = sum(1 for o in others if searches_compatible(trial, o))
    return {"radius_km": best, "count": count}


def _relationship_suggestions(mine, others):
    """Which other relationship types, if added alongside the ones already
    picked, would open up matches — each verified through
    searches_compatible(), most people admitted first.

    relationship_type is a CSV, so "switch to" became "add": the trial
    keeps every type mine already has and appends the candidate, the same
    shape chip_options()' relationship: rows try.
    """
    mine_types = [t.strip() for t in (mine["relationship_type"] or "").split(",") if t.strip()]
    results, seen = [], set(mine_types)
    for o in others:
        for rt in (o["relationship_type"] or "").split(","):
            rt = rt.strip()
            if not rt or rt in seen:
                continue
            seen.add(rt)
            trial = dict(mine)
            trial["relationship_type"] = ",".join(mine_types + [rt])
            trial["use_relationship"] = True
            count = sum(1 for x in others if searches_compatible(trial, x))
            if count:
                results.append({"relationship_type": rt, "count": count})
    results.sort(key=lambda r: -r["count"])
    return results


def _gender_suggestions(mine, others):
    """Which "looking for" options, if switched to, would open up
    matches, same verification and ordering as relationship."""
    results = []
    for opt in SEEKING_OPTIONS:
        if opt == mine["seeking"]:
            continue
        trial = dict(mine)
        trial["seeking"] = opt
        count = sum(1 for o in others if searches_compatible(trial, o))
        if count:
            results.append({"seeking": opt, "count": count})
    results.sort(key=lambda r: -r["count"])
    return results


def _search_pool(user_id):
    """Return (mine, others) as dicts, or (None, []) if not searching.

    others is every other waiting searcher, joined with the profile fields
    searches_compatible() needs (gender, age).
    """
    db = get_db()
    mine = db.execute(
        """
        SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        WHERE s.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if mine is None:
        return None, []

    others = db.execute(
        f"""
        SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        JOIN users u ON u.id = s.user_id
        WHERE s.status = 'waiting' AND s.user_id != ?
          {CANDIDATE_ELIGIBLE_SQL}
          {NOT_BLOCKED_SQL}
        """,
        (user_id, user_id, user_id),
    ).fetchall()
    return dict(mine), [dict(o) for o in others]


def search_blockers(mine, others):
    """Explain why a waiting search hasn't matched, filter by filter.

    Returns pool size, a per-filter "if you turned this off, N more people
    would fit" count (computed by actually disabling that use_* flag, so
    it is exactly what the toggle button would do), and a concrete
    suggested value for each filter that is currently blocking someone —
    every suggestion verified against the pool through searches_compatible(),
    never assumed.
    """
    if mine is None:
        return {}

    def relaxed(**overrides):
        loosened = dict(mine)
        loosened.update(overrides)
        return sum(1 for o in others if searches_compatible(loosened, o))

    current_count = sum(1 for o in others if searches_compatible(mine, o))

    return {
        "pool": len(others),
        "current_count": current_count,
        "if_any_gender": relaxed(use_gender=False),
        "if_any_age": relaxed(use_age=False),
        "if_any_connection": relaxed(use_relationship=False),
        "if_any_distance": relaxed(use_distance=False),
        "if_any_physical": relaxed(use_physical=False),
        "if_any_interests": relaxed(interests=""),
        "if_all_relaxed": relaxed(
            use_gender=False, use_age=False, use_relationship=False,
            use_distance=False, use_physical=False, interests="",
        ),
        "age_suggestion": _minimal_age_suggestion(mine, others),
        "distance_suggestion": _minimal_distance_suggestion(mine, others),
        "relationship_suggestions": _relationship_suggestions(mine, others),
        "gender_suggestions": _gender_suggestions(mine, others),
    }


def search_chips(search):
    """The filters a live search is actually applying, as editable chips.

    Each chip is {key, label, off}: `key` identifies what tapping it edits
    (chip_options() below answers "into what"), `off` marks a filter the
    searcher has already switched off -- still shown, so it can be switched
    back on, the same way "Any age" already read before this screen had
    controls. Anything with no value at all (no location typed, no
    interests picked) is omitted rather than shown as an empty row.

    relationship_type is a CSV -- a searcher can want more than one kind of
    connection -- so like interests and body types it gets one chip per
    selected value rather than the single always-present chip gender and
    age get. use_relationship still exists, but it now just tracks whether
    that CSV is empty (see the apply endpoint below), the same relationship
    use_physical has with pref_body_types.
    """
    chips = []
    for part in (search["relationship_type"] or "").split(","):
        part = part.strip()
        if part:
            chips.append({"key": f"relationship:{part}", "label": part, "off": False})
    chips.append({
        "key": "gender",
        "label": opt_label_for(search["seeking"]) or t("chip.anyone"),
        "off": not search["use_gender"],
    })
    chips.append({
        "key": "age",
        "label": f"{search['age_min']}–{search['age_max']}" if search["use_age"] else t("chip.any_age"),
        "off": not search["use_age"],
    })
    # While there is only one city, naming it says nothing about what this
    # search is looking for -- it is true of everyone by construction.
    if search["location"] and not SINGLE_CITY:
        chips.append({"key": "location", "label": search["location"], "off": False})
    for part in (search["interests"] or "").split(","):
        part = part.strip()
        if part:
            chips.append({"key": f"interest:{part}", "label": part, "off": False})
    for part in (search[PREF_BODY_TYPES_FIELD] or "").split(","):
        part = part.strip()
        if part:
            chips.append({"key": f"body:{part}", "label": part, "off": False})
    return chips


def _chip_trial_count(mine, others, **overrides):
    """How many of `others` a search would fit against with these overrides
    applied -- the one counting rule every option row below uses, so a count
    shown in the sheet is never anything other than a real
    searches_compatible() tally."""
    trial = dict(mine)
    trial.update(overrides)
    return sum(1 for o in others if searches_compatible(trial, o))


def chip_options(mine, others, key):
    """Alternatives for one chip, each priced with the count switching to it
    would yield: [{value, label, count, current}, ...]. `value` is what a
    POST to /search/chips echoes back to apply the row; `current` marks the
    one already in effect.
    """
    if key.startswith("relationship:"):
        # Same toggle-in-a-CSV shape as body: below: each row previews what
        # the set would become with this one type flipped, not switching to
        # it outright -- a searcher can want more than one kind of
        # connection at once.
        current = [t.strip() for t in (mine["relationship_type"] or "").split(",") if t.strip()]
        options = []
        for rt in RELATIONSHIP_TYPES:
            on = rt in current
            trial_list = [t for t in current if t != rt] if on else current + [rt]
            options.append({
                "value": ",".join(trial_list), "label": rt,
                "current": on,
                "count": _chip_trial_count(
                    mine, others,
                    relationship_type=",".join(trial_list),
                    use_relationship=bool(trial_list)),
            })
        options.append({
            "value": "", "label": "Any connection",
            "current": not mine["use_relationship"],
            "count": _chip_trial_count(mine, others, use_relationship=False),
        })
        return options

    if key == "gender":
        options = [
            {"value": opt, "label": opt, "current": opt == mine["seeking"] and mine["use_gender"],
             "count": _chip_trial_count(mine, others, seeking=opt, use_gender=True)}
            for opt in SEEKING_OPTIONS
        ]
        options.append({
            "value": "", "label": "Everyone (no preference)",
            "current": not mine["use_gender"],
            "count": _chip_trial_count(mine, others, use_gender=False),
        })
        return options

    if key == "age":
        seen = set()
        options = []

        def add(lo, hi, label):
            lo = max(AGE_MIN_YEARS, min(lo, AGE_MAX_YEARS))
            hi = max(AGE_MIN_YEARS, min(hi, AGE_MAX_YEARS))
            if lo > hi or (lo, hi) in seen:
                return
            seen.add((lo, hi))
            options.append({
                "value": f"{lo}-{hi}", "label": label,
                "current": mine["use_age"] and lo == mine["age_min"] and hi == mine["age_max"],
                "count": _chip_trial_count(mine, others, age_min=lo, age_max=hi, use_age=True),
            })

        add(mine["age_min"], mine["age_max"],
            f"{mine['age_min']}–{mine['age_max']} (current)")
        suggestion = _minimal_age_suggestion(mine, others)
        if suggestion:
            add(suggestion["age_min"], suggestion["age_max"],
                f"{suggestion['age_min']}–{suggestion['age_max']}")
        add(mine["age_min"] - 5, mine["age_max"] + 5, "Widen by 5 years")
        add(mine["age_min"] - 10, mine["age_max"] + 10, "Widen by 10 years")
        options.append({
            "value": "", "label": t("chip.any_age"),
            "current": not mine["use_age"],
            "count": _chip_trial_count(mine, others, use_age=False),
        })
        return options

    if key == "location":
        # No alternative city to switch to -- only removal, which is not a
        # no-op: the wizard always saves radius_km at its maximum (distance
        # is never asked), so this side's own radius never excludes anyone.
        # But search_distance_km() returns None when either side lacks
        # coordinates, so clearing this makes distance unenforceable in
        # both directions and dodges the OTHER person's radius filter too.
        return [{
            "value": "", "label": "No location",
            "current": False,
            "count": _chip_trial_count(mine, others, location="", lat=None, lng=None),
        }]

    if key.startswith("interest:"):
        word = key.split(":", 1)[1]
        current_words = [p.strip() for p in (mine["interests"] or "").split(",") if p.strip()]

        def with_words(words):
            return ",".join(words)

        options = [{
            "value": with_words([w for w in current_words if w != word]),
            "label": "Remove", "current": False,
            "count": _chip_trial_count(
                mine, others, interests=with_words([w for w in current_words if w != word])),
        }]
        # Swap-in candidates: suggested words not already picked, verified
        # to actually admit someone once swapped in for this one -- capped
        # by INTEREST_MAX the same way the wizard caps the list itself.
        room = current_words[:]
        if word in room:
            room.remove(word)
        for cand in INTEREST_SUGGESTIONS:
            if cand == word or cand in current_words or len(room) >= INTEREST_MAX:
                continue
            trial_words = room + [cand]
            count = _chip_trial_count(mine, others, interests=with_words(trial_words))
            if count:
                options.append({
                    "value": with_words(trial_words), "label": f"Swap for “{cand}”",
                    "current": False, "count": count,
                })
        return options

    if key.startswith("body:"):
        current = [p.strip() for p in (mine[PREF_BODY_TYPES_FIELD] or "").split(",") if p.strip()]
        options = []
        for bt in BODY_TYPES:
            on = bt in current
            trial_list = [t for t in current if t != bt] if on else current + [bt]
            options.append({
                "value": ",".join(trial_list), "label": bt,
                "current": on,
                "count": _chip_trial_count(
                    mine, others,
                    **{PREF_BODY_TYPES_FIELD: ",".join(trial_list), "use_physical": bool(trial_list)}),
            })
        options.append({
            "value": "", "label": "Any body type",
            "current": not mine["use_physical"],
            "count": _chip_trial_count(mine, others, use_physical=False),
        })
        return options

    return []


def chip_state(mine, others):
    """The JSON payload the waiting screen redraws itself from: every chip
    with its options priced, plus whether "Search wider" should show.

    fits == 0 is necessary but not sufficient -- see SEARCH_WIDER_SECONDS.
    Elapsed time is measured from searches.created_at (a database value, not
    a per-request one), so a page reload never pushes the offer back and a
    filter tweak -- which never touches created_at, see the note on
    UPDATE below -- never postpones it either.
    """
    blockers = search_blockers(mine, others)
    fits = blockers.get("current_count", 0)
    elapsed = (dt.now(timezone.utc) - mine["created_at"]).total_seconds()

    chips = search_chips(mine)
    for chip in chips:
        chip["options"] = chip_options(mine, others, chip["key"])

    state = {
        "chips": chips,
        "waiting": len(others),
        "fits": fits,
        "elapsed": int(elapsed),
        "ripe": elapsed >= MIN_SEARCH_SECONDS,
        "relax_all": {
            "count": blockers.get("if_all_relaxed", 0),
            "offer": fits == 0 and elapsed >= SEARCH_WIDER_SECONDS,
        },
        "status": mine["status"],
    }
    # The apply endpoint runs try_pair() before building this, so a change
    # that opened up a partner has already paired by the time the browser
    # sees the response -- carry the chat here rather than making it wait
    # for the next /search/status tick to notice.
    if mine["status"] == "matched" and mine["match_id"]:
        state["chat_url"] = url_for("chat", match_id=mine["match_id"])
    return state


@app.route("/search/waiting")
@login_required
def search_waiting():
    user_id = current_uid()
    touch_search(user_id)
    mine, others = _search_pool(user_id)

    if mine is None or mine["status"] == "cancelled":
        return redirect(url_for("live_search"))
    if mine["status"] == "matched" and mine["match_id"]:
        return redirect(url_for("chat", match_id=mine["match_id"]))

    return render_template("search_waiting.html", search=mine, state=chip_state(mine, others))


@app.route("/search/chips")
@login_required
def search_chips_get():
    """Polled alongside /search/status to refresh the waiting screen's
    pills as the pool changes -- same JSON shape POST returns below, so
    the browser redraws from either one identically."""
    user_id = current_uid()
    touch_search(user_id)
    mine, others = _search_pool(user_id)
    if mine is None:
        return {"error": "not searching"}, 404
    return chip_state(mine, others)


@app.route("/search/chips", methods=["POST"])
@login_required
def search_chips_apply():
    """Apply one pill's new value (or "Search wider") without disturbing
    created_at -- unlike save_search(), which resets it and would restart
    the MIN_SEARCH_SECONDS/SEARCH_WIDER_SECONDS clocks on every tap. Every
    posted value is re-validated the same way live_search() validates the
    wizard's own POST; nothing here trusts chip_options()' own output.
    """
    user_id = current_uid()
    mine, others = _search_pool(user_id)
    if mine is None:
        return {"error": "not searching"}, 404

    key = request.form.get("key", "")
    value = request.form.get("value", "")

    db = get_db()
    columns, params = [], []

    def set_col(col, val):
        columns.append(f"{col} = ?")
        params.append(val)

    if key == "all":
        set_col("use_gender", False)
        set_col("use_age", False)
        set_col("use_relationship", False)
        set_col("use_distance", False)
        set_col("use_physical", False)
        set_col("interests", "")
        set_col("location", "")
        set_col("lat", None)
        set_col("lng", None)

    elif key.startswith("relationship:"):
        # Same shape as body: below -- value is the whole CSV the row
        # already computed (one type toggled in or out), not a single type
        # to switch to, and "" is the sheet's own "Any connection" row.
        types = clean_relationship_types(value)
        set_col("relationship_type", types)
        set_col("use_relationship", bool(types))

    elif key == "gender":
        if value == "":
            set_col("use_gender", False)
        elif value in SEEKING_OPTIONS:
            set_col("seeking", value)
            set_col("use_gender", True)
        else:
            return {"error": "invalid seeking"}, 400

    elif key == "age":
        if value == "":
            set_col("use_age", False)
        else:
            try:
                lo_s, hi_s = value.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                return {"error": "invalid age range"}, 400
            if not (AGE_MIN_YEARS <= lo <= hi <= AGE_MAX_YEARS):
                return {"error": "age range out of bounds"}, 400
            set_col("age_min", lo)
            set_col("age_max", hi)
            set_col("use_age", True)

    elif key == "location":
        set_col("location", "")
        set_col("lat", None)
        set_col("lng", None)

    elif key.startswith("interest:"):
        set_col("interests", clean_interests(value))

    elif key.startswith("body:"):
        body_types = [b for b in value.split(",") if b in BODY_TYPES]
        set_col(PREF_BODY_TYPES_FIELD, ",".join(body_types))
        set_col("use_physical", bool(body_types))

    else:
        return {"error": "unknown key"}, 400

    db.execute(
        f"UPDATE searches SET {', '.join(columns)} WHERE user_id = ?",
        (*params, user_id),
    )
    db.commit()

    # A change that just opened up a partner should pair now, not on the
    # next status poll.
    try_pair(user_id)

    mine, others = _search_pool(user_id)
    return chip_state(mine, others)


@app.route("/search/status")
@login_required
def search_status():
    """Polled by the waiting page; reports whether a match exists yet.

    Returns immediately rather than holding the request open. Waking the
    exact instance that happens to hold a waiting request is not possible
    once the app is scaled out, so the waiting page polls on a short tick
    instead (see templates/search_waiting.html).
    """
    user_id = current_uid()
    touch_search(user_id)

    # Retry pairing on each poll so a searcher who arrived since the last
    # tick still gets picked up.
    try_pair(user_id)
    row = get_db().execute(
        "SELECT status, match_id FROM searches WHERE user_id = ?", (user_id,)
    ).fetchone()

    if row is None:
        return {"status": "none"}

    result = {"status": row["status"]}
    if row["status"] == "matched" and row["match_id"]:
        result["match_id"] = row["match_id"]
        result["chat_url"] = url_for("chat", match_id=row["match_id"])
    return result


@app.route("/search/cancel", methods=["POST"])
@login_required
def search_cancel():
    db = get_db()
    db.execute(
        "UPDATE searches SET status = 'cancelled' WHERE user_id = ? AND status = 'waiting'",
        (current_uid(),),
    )
    db.commit()
    flash(t("msg.search_stopped"))
    return redirect(url_for("live_search"))


def get_match_participants(match_id):
    """Return (match_row, [profile_a, profile_b]) or (None, None)."""
    db = get_db()
    match = db.execute(
        "SELECT * FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if match is None:
        return None, None
    profiles = [
        db.execute(
            """
            SELECT p.*, u.username, u.is_bot FROM profiles p
            JOIN users u ON u.id = p.user_id
            WHERE p.user_id = ?
            """,
            (uid,),
        ).fetchone()
        for uid in (match["user_a"], match["user_b"])
    ]
    return match, profiles


# --- match lifecycle: reveal -> timed chat -> decision -----------------
#
# Only try_pair() ever writes status='timed'; every pre-existing row and
# every /find "Match & chat" row keeps the 'active' default and behaves
# exactly as before. Phases are computed from paired_at rather than stored,
# so there is no background job advancing them — each poll (or the /decide
# POST) calls resolve_match() to persist a phase once it becomes terminal.

def match_phase(match, now=None):
    """Return 'reveal' | 'timed' | 'deciding' | 'active' | 'ended'."""
    if match["status"] in ("active", "ended"):
        return match["status"]

    paired_at = match["paired_at"]
    if paired_at is None:
        # Shouldn't happen for status='timed', but fail toward "active"
        # rather than stranding the chat behind a countdown with no anchor.
        return "active"

    now = now or dt.now(timezone.utc)
    elapsed = (now - paired_at).total_seconds()

    if elapsed < REVEAL_SECONDS:
        return "reveal"
    if elapsed < REVEAL_SECONDS + TIMED_CHAT_SECONDS:
        return "timed"
    # Past the grace window this is really "ended" (resolve_match() will
    # persist that on the next poll/decide call) but until then it still
    # reads as "deciding" — a match with no status write yet is not active.
    return "deciding"


def resolve_match(match_id):
    """Advance a timed match to its terminal state if one is now due.

    Both 'continue' -> active. Either 'unmatch' -> ended. Grace window
    elapsed with a decision still missing -> ended (auto-unmatch). A bot
    participant always auto-continues once the human has decided or the
    chat has locked, so a lifecycle can be exercised solo against a seeded
    member. Returns the (possibly updated) match row.
    """
    db = get_db()
    match = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if match is None or match["status"] in ("active", "ended"):
        return match

    now = dt.now(timezone.utc)
    phase = match_phase(match, now)
    if phase not in ("reveal", "timed", "deciding"):
        return match

    # Someone leaving ends the room the moment it happens, in any phase —
    # there is nothing left to wait for once one side has gone. Everything
    # below this is end-of-timer resolution and only applies to 'deciding'.
    if "unmatch" in (match["decision_a"], match["decision_b"]):
        db.execute(
            "UPDATE matches SET status = 'ended', ended_at = NOW() WHERE id = ?",
            (match_id,),
        )
        db.commit()
        return db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()

    users = db.execute(
        "SELECT id, is_bot FROM users WHERE id IN (?, ?)",
        (match["user_a"], match["user_b"]),
    ).fetchall()
    is_bot = {u["id"]: u["is_bot"] for u in users}

    # A bot answers as soon as there is anything to answer: the other side
    # has chosen, or the window has closed. Gating this on the 'deciding'
    # phase (as it used to be) made a bot the one thing standing between a
    # human who had already committed and the room they had committed to.
    decision_a, decision_b = match["decision_a"], match["decision_b"]
    if is_bot.get(match["user_a"]) and not decision_a and (decision_b or phase == "deciding"):
        decision_a = "continue"
    if is_bot.get(match["user_b"]) and not decision_b and (decision_a or phase == "deciding"):
        decision_b = "continue"

    grace_over = (now - match["paired_at"]).total_seconds() >= (
        REVEAL_SECONDS + TIMED_CHAT_SECONDS + DECISION_GRACE_SECONDS
    )

    new_status = None
    if decision_a == "unmatch" or decision_b == "unmatch":
        new_status = "ended"
    elif decision_a == "continue" and decision_b == "continue":
        # Both are in, so there is nothing left for the clock to decide --
        # in any phase, not just once the timer has run out. Continue is a
        # commitment, and making a committed pair sit out the rest of the
        # countdown was the timer holding them apart rather than pacing
        # them. (It cannot fire during 'reveal': match_decide() only accepts
        # 'continue' from 'timed' onward, so a pair still cannot skip the
        # timed chat wholesale by both accepting on the reveal screen.)
        new_status = "active"
    elif grace_over:
        new_status = "ended"  # no decision from someone within the window

    if decision_a != match["decision_a"] or decision_b != match["decision_b"]:
        db.execute(
            "UPDATE matches SET decision_a = ?, decision_b = ? WHERE id = ?",
            (decision_a, decision_b, match_id),
        )

    if new_status:
        db.execute(
            "UPDATE matches SET status = ?, ended_at = CASE WHEN ? = 'ended' THEN NOW() ELSE ended_at END WHERE id = ?",
            (new_status, new_status, match_id),
        )

    db.commit()
    return db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()


def match_state_payload(match, user_id):
    """JSON body for /match/<id>/state, polled by the chat page."""
    now = dt.now(timezone.utc)
    phase = match_phase(match, now)
    my_col, their_col = ("decision_a", "decision_b") if user_id == match["user_a"] \
        else ("decision_b", "decision_a")

    seconds_left = None
    if match["paired_at"] is not None:
        elapsed = (now - match["paired_at"]).total_seconds()
        if phase == "reveal":
            seconds_left = max(0, round(REVEAL_SECONDS - elapsed))
        elif phase == "timed":
            seconds_left = max(0, round(REVEAL_SECONDS + TIMED_CHAT_SECONDS - elapsed))

    return {
        "phase": phase,
        "seconds_left": seconds_left,
        "locked": phase not in ("timed", "active"),
        "my_decision": match[my_col] or None,
        "their_decision": match[their_col] or None,
        "chat_url": url_for("chat", match_id=match["id"]),
    }


@app.route("/match/<int:match_id>/state")
@login_required
def match_state(match_id):
    match, _ = get_match_participants(match_id)
    user_id = current_uid()
    if match is None:
        return {"error": "not found"}, 404
    if user_id not in (match["user_a"], match["user_b"]):
        return {"error": "forbidden"}, 403

    match = resolve_match(match_id) or match
    return match_state_payload(match, user_id)


@app.route("/match/<int:match_id>/decide", methods=["POST"])
@login_required
def match_decide(match_id):
    match, _ = get_match_participants(match_id)
    user_id = current_uid()
    if match is None:
        return {"error": "not found"}, 404
    if user_id not in (match["user_a"], match["user_b"]):
        return {"error": "forbidden"}, 403

    choice = request.form.get("choice", "")
    if choice not in ("continue", "unmatch"):
        return {"error": "invalid choice"}, 400

    match = resolve_match(match_id) or match
    # Leaving is allowed from the moment the match appears; committing to
    # continue only once the room is actually open, so a pair cannot both
    # accept during the reveal and skip the timed chat altogether.
    allowed = {
        "reveal": ("unmatch",),
        "timed": ("continue", "unmatch"),
        "deciding": ("continue", "unmatch"),
        # A match you both kept is still one either of you can leave. There
        # is no "continue" here -- you already did.
        "active": ("unmatch",),
    }.get(match_phase(match), ())
    if choice in allowed:
        col = "decision_a" if user_id == match["user_a"] else "decision_b"
        db = get_db()
        db.execute(f"UPDATE matches SET {col} = ? WHERE id = ?", (choice, match_id))
        # resolve_match() treats 'active' as terminal and will not revisit
        # it, so leaving a kept match has to be written here and now.
        if match["status"] == "active":
            db.execute(
                "UPDATE matches SET status = 'ended', ended_at = NOW() WHERE id = ?",
                (match_id,),
            )
        db.commit()
        match = resolve_match(match_id) or match

    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        return match_state_payload(match, user_id)
    return redirect(url_for("chat", match_id=match_id))


@app.route("/match/<int:match_id>/skip-reveal", methods=["POST"])
@login_required
def match_skip_reveal(match_id):
    """Let either participant open the room early, before the 20s reveal ends.

    Rewinds paired_at by REVEAL_SECONDS so match_phase() reads 'timed' for
    both sides on the very next request -- no separate "ready" flag needed,
    and it can't be abused to skip the timed chat itself: only the reveal
    phase is eligible.
    """
    match, _ = get_match_participants(match_id)
    user_id = current_uid()
    if match is None:
        return {"error": "not found"}, 404
    if user_id not in (match["user_a"], match["user_b"]):
        return {"error": "forbidden"}, 403

    if match_phase(match) == "reveal":
        db = get_db()
        db.execute(
            """
            UPDATE matches SET paired_at = paired_at - (? * INTERVAL '1 second')
            WHERE id = ? AND status = 'timed'
            """,
            (REVEAL_SECONDS, match_id),
        )
        db.commit()

    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        match = get_match_participants(match_id)[0] or match
        return match_state_payload(match, user_id)
    return redirect(url_for("chat", match_id=match_id))


def relative_time_label(when):
    """Short relative label ('now', '2m', '3h', '5d') for a chat-row timestamp."""
    if when is None:
        return ""
    seconds = int((dt.now(timezone.utc) - when).total_seconds())
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


@app.route("/chats")
@login_required
def chats():
    user = current_user()
    query = """
        SELECT m.*,
               COALESCE(pa.name, 'Deleted member') AS name_a,
               COALESCE(pb.name, 'Deleted member') AS name_b,
               (SELECT body FROM messages WHERE match_id = m.id
                ORDER BY id DESC LIMIT 1) AS last_message,
               (SELECT created_at FROM messages WHERE match_id = m.id
                ORDER BY id DESC LIMIT 1) AS last_message_at
        FROM matches m
        -- LEFT so a match with someone who has deleted their account stays
        -- in the surviving participant's list instead of silently vanishing.
        LEFT JOIN profiles pa ON pa.user_id = m.user_a
        LEFT JOIN profiles pb ON pb.user_id = m.user_b
        {where}
        ORDER BY m.id DESC
    """
    if user["is_admin"]:
        # The admin moderates and can see every room.
        rows = get_db().execute(query.format(where="")).fetchall()
    else:
        rows = get_db().execute(
            query.format(where="WHERE ? IN (m.user_a, m.user_b)"),
            (user["id"],),
        ).fetchall()

    # Phase labels so a timed/awaiting-decision room reads differently from
    # a permanent one; ended rooms sort last regardless of recency.
    rooms = []
    for row in rows:
        room = dict(row)
        room["phase"] = match_phase(row)
        room["when"] = relative_time_label(
            room["last_message_at"] or room["paired_at"] or room["created_at"]
        )

        # A participant reads their own row as being about the OTHER
        # person, not both names in third person -- the admin's moderation
        # view keeps the pair-wise rendering below, since neither name is
        # "you" from that seat.
        if not user["is_admin"]:
            if row["user_a"] == user["id"]:
                room["other_id"], room["other_name"] = row["user_b"], row["name_b"]
            else:
                room["other_id"], room["other_name"] = row["user_a"], row["name_a"]
            # Same gate can_view_photos() enforces (status='active'); no
            # need for its self/admin branches here since the viewer is
            # always the other, non-admin participant in this loop.
            room["other_photo_id"] = None
            if room["status"] == "active":
                photo = get_db().execute(
                    "SELECT id FROM photos WHERE user_id = ?"
                    " ORDER BY is_primary DESC, sort_order, id LIMIT 1",
                    (room["other_id"],),
                ).fetchone()
                room["other_photo_id"] = photo["id"] if photo else None

        rooms.append(room)
    rooms.sort(key=lambda r: (r["phase"] == "ended", -r["id"]))

    return render_template("chats.html", rooms=rooms, is_admin=user["is_admin"])


@app.route("/chat/<int:match_id>")
@login_required
def chat(match_id):
    match, profiles = get_match_participants(match_id)
    user = current_user()
    if match is None:
        flash(t("msg.no_such_room"))
        return redirect(url_for("chats"))

    is_participant = user["id"] in (match["user_a"], match["user_b"])
    if not is_participant and not user["is_admin"]:
        flash(t("msg.room_private"))
        return redirect(url_for("chats"))

    if is_participant:
        match = resolve_match(match_id) or match
    phase = match_phase(match)

    messages = get_db().execute(
        """
        SELECT msg.*, COALESCE(p.name, 'Deleted member') AS sender_name FROM messages msg
        LEFT JOIN profiles p ON p.user_id = msg.sender_id
        WHERE msg.match_id = ?
        ORDER BY msg.id
        """,
        (match_id,),
    ).fetchall()

    state = match_state_payload(match, user["id"]) if is_participant else None

    # Being on this page is the read signal: whatever is rendered here is
    # what the viewer has now seen, so advance their pointer to the last
    # message and read the other side's current pointer for the sender's
    # own bubbles (see mark_read()).
    their_read_id = None
    if is_participant:
        if messages:
            mark_read(match, user["id"], messages[-1]["id"])
            match = get_db().execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        their_read_id = match[their_read_column(match, user["id"])]

    # The reveal's hook: the shared-interest overlap try_pair() already
    # computed to pick this partner, rendered as chips (shared ones filled,
    # the rest outlined) plus a one-line opener naming the best one to ask
    # about. Falls back in order: a shared word -> the other person's own
    # interests (even with no overlap, that's still something to open with)
    # -> the thing that's always true, same relationship_type. Only worth
    # the queries during the reveal itself.
    reveal_heading = None
    reveal_chips = []
    reveal_highlight = None
    reveal_pronoun = "them"
    match_reason = None
    if is_participant and phase == "reveal":
        other_id = match["user_b"] if user["id"] == match["user_a"] else match["user_a"]
        rows = get_db().execute(
            "SELECT user_id, interests, relationship_type FROM searches WHERE user_id IN (?, ?)",
            (user["id"], other_id),
        ).fetchall()
        mine_search = next((r for r in rows if r["user_id"] == user["id"]), None)
        other_search = next((r for r in rows if r["user_id"] == other_id), None)
        other_profile = next((p for p in profiles if p["user_id"] == other_id), None)
        mine_profile = next((p for p in profiles if p["user_id"] == user["id"]), None)
        reveal_pronoun = PRONOUNS.get(other_profile["gender"] if other_profile else None, "them")
        if mine_search and other_search:
            # searches.interests is routinely blank: the "Interests" toggle
            # on screen 2 defaults off, and switching a filter off writes
            # '' rather than leaving the profile's value in place. Fall
            # back to the profile itself so the reveal still has something
            # to show instead of going straight to the generic line.
            mine_text = mine_search["interests"] or (mine_profile["interests"] if mine_profile else "")
            other_text = other_search["interests"] or (other_profile["interests"] if other_profile else "")

            other_interest_list = [w.strip() for w in re.split(r"[,;/\n]+", other_text) if w.strip()]
            # Word casing comes from the other person's own text -- the
            # chips and the opener describe them, in their own words.
            shared_interests = _shared_interest_words(other_text, mine_text)
            shared_stems = {_stem(w.lower().strip(".!?()\"'")) for w in shared_interests}

            if other_interest_list:
                reveal_chips = sorted(
                    (
                        {"text": w, "shared": _stem(w.lower().strip(".!?()\"'")) in shared_stems}
                        for w in other_interest_list
                    ),
                    key=lambda c: not c["shared"],
                )
                reveal_heading = "You both like" if shared_interests else f"{other_profile['name']}'s interests"
                reveal_highlight = shared_interests[0] if shared_interests else other_interest_list[0]
            else:
                # relationship_type is a CSV on both sides now; name the type
                # that actually paired them (the shared one -- try_pair()
                # would not have matched them otherwise) rather than either
                # side's whole list. The single-sided fallbacks keep the old
                # leniency for rows saved before this was CSV-aware.
                mine_types = [t.strip() for t in (mine_search["relationship_type"] or "").split(",") if t.strip()]
                other_types = [t.strip() for t in (other_search["relationship_type"] or "").split(",") if t.strip()]
                shared_rt = [t for t in mine_types if t in other_types]
                reason_type = shared_rt[0] if shared_rt else (mine_types[0] if mine_types else (other_types[0] if other_types else None))
                phrase = RELATIONSHIP_REASON_PHRASES.get(reason_type, "the same thing")
                match_reason = f"You're both here for {phrase}."

    # Avatar for the chat header. Photos stay locked until both sides
    # continue, so this is None for most of a timed room and the header
    # falls back to the placeholder — the same gate /photo enforces, asked
    # here so the template never has to guess.
    other_photo_id = None
    if is_participant:
        other_id = match["user_b"] if user["id"] == match["user_a"] else match["user_a"]
        if can_view_photos(other_id, user["id"], user["is_admin"]):
            row = get_db().execute(
                "SELECT id FROM photos WHERE user_id = ?"
                " ORDER BY is_primary DESC, sort_order, id LIMIT 1",
                (other_id,),
            ).fetchone()
            other_photo_id = row["id"] if row else None

    return render_template(
        "chat.html",
        match=match,
        profiles=profiles,
        messages=messages,
        me_id=current_uid(),
        is_participant=is_participant,
        phase=phase,
        state=state,
        other_photo_id=other_photo_id,
        reveal_seconds=REVEAL_SECONDS,
        timed_seconds=TIMED_CHAT_SECONDS,
        reveal_heading=reveal_heading,
        reveal_chips=reveal_chips,
        reveal_highlight=reveal_highlight,
        reveal_pronoun=reveal_pronoun,
        match_reason=match_reason,
        their_read_id=their_read_id,
    )


def message_dict(row):
    return {
        "id": row["id"],
        "sender_id": row["sender_id"],
        "sender_name": row["sender_name"],
        "body": row["body"],
        "created_at": row["created_at"].isoformat(),
    }


def their_read_column(match, user_id):
    """Which column holds the *other* participant's read pointer."""
    return "read_b" if user_id == match["user_a"] else "read_a"


def mark_read(match, user_id, up_to_id):
    """Advance user_id's read pointer to up_to_id, never backwards.

    Called every time a participant is actually looking at the room (page
    load, and each poll while the tab stays open) -- there is no separate
    "seen" event to listen for, so being on the page is the signal.
    """
    if not up_to_id:
        return
    col = "read_a" if user_id == match["user_a"] else "read_b"
    db = get_db()
    db.execute(
        f"UPDATE matches SET {col} = ? WHERE id = ? AND {col} < ?",
        (up_to_id, match["id"], up_to_id),
    )
    db.commit()


def fetch_messages_after(match_id, after):
    return get_db().execute(
        """
        SELECT msg.*, COALESCE(p.name, 'Deleted member') AS sender_name FROM messages msg
        LEFT JOIN profiles p ON p.user_id = msg.sender_id
        WHERE msg.match_id = ? AND msg.id > ?
        ORDER BY msg.id
        """,
        (match_id, after),
    ).fetchall()


# --- demo-profile bot replies -------------------------------------------
#
# No LLM dependency (see CLAUDE.md): a small template engine seeded with
# the bot's own profile, picked deterministically from (match_id, message
# count) so a chat replays identically rather than depending on `random` in
# the request path. It will repeat itself over a long conversation — the
# accepted cost of staying offline and dependency-free — but comfortably
# covers a five-minute timed chat.
BOT_LOCK_NAMESPACE = 9_213_005


def _bot_seed(match_id, count, salt=""):
    digest = hashlib.md5(f"{match_id}:{count}:{salt}".encode()).hexdigest()
    return int(digest, 16)


def _bot_delay_seconds(match_id, count):
    """Deterministic pseudo-random 2-6s 'typing' delay."""
    return 2 + (_bot_seed(match_id, count, "delay") % 4001) / 1000.0


def bot_reply_line(bot_profile, history, match_id, count):
    """Pick the bot's next line, grounded in its own profile."""
    topic = (bot_profile.get("interests") or bot_profile.get("hobbies") or "").split(",")[0].strip()
    topic = topic or "getting to know people"
    city = bot_profile.get("location") or "around here"
    name = bot_profile.get("name") or "there"

    if count == 0:
        openers = [
            f"Hey! I'm {name}, really into {topic}. How's your day going?",
            f"Hi there — {name} here, based in {city}. What made you start searching today?",
            f"Hello! Always happy to talk {topic}. What are you looking for?",
        ]
        return openers[_bot_seed(match_id, count, "line") % len(openers)]

    last_body = history[-1]["body"] if history else ""
    if last_body.strip().endswith("?"):
        answers = [
            f"Good question! Honestly, {topic} takes up most of my free time these days.",
            f"I'd say {city} keeps me pretty busy, but I'd love to hear more about you.",
            "Ha, depends on the day — ask me again tomorrow!",
        ]
        return answers[_bot_seed(match_id, count, "line") % len(answers)]

    rotating = [
        f"That's cool! I'm big on {topic} myself.",
        f"Nice — {city} has a lot to offer if you're into that.",
        "Tell me more, I'm curious!",
        f"I could talk about {topic} all day, honestly.",
        "Haha, I like that.",
    ]
    return rotating[_bot_seed(match_id, count, "line") % len(rotating)]


def maybe_bot_reply(match, profiles):
    """Generate the demo bot's next reply, lazily, inside the chat poll.

    There is no background worker and the app is multi-instance, so this
    is where the typing delay and the insert happen. Guarded by a per-match
    advisory lock so two concurrent polls from the same open tab set can't
    double-post (same pattern as try_pair()'s pairing lock).
    """
    if match_phase(match) not in ("timed", "active"):
        return
    bot_profile = next((p for p in profiles if p and p["is_bot"]), None)
    if bot_profile is None:
        return
    bot_id = bot_profile["user_id"]

    db = get_db()
    db.execute("SELECT pg_advisory_xact_lock(?, ?)", (BOT_LOCK_NAMESPACE, match["id"]))
    try:
        history = db.execute(
            "SELECT * FROM messages WHERE match_id = ? ORDER BY id", (match["id"],)
        ).fetchall()

        last = history[-1] if history else None
        if last is not None and last["sender_id"] == bot_id:
            db.commit()
            return  # already replied to the last human message

        anchor = last["created_at"] if last is not None else match["paired_at"]
        if anchor is None:
            db.commit()
            return

        count = len(history)
        if (dt.now(timezone.utc) - anchor).total_seconds() < _bot_delay_seconds(match["id"], count):
            db.commit()
            return

        # Replying implies having read up to here -- a bot's messages are
        # otherwise never marked seen (it never loads the page a human's
        # own poll marks read from), so the human's ticks would sit on a
        # single check forever. Inlined rather than mark_read() (which
        # commits on its own): this update has to land in the same
        # transaction as the insert below, under the advisory lock already
        # held, or a second poll could race between the two.
        if history:
            read_col = "read_a" if bot_id == match["user_a"] else "read_b"
            db.execute(
                f"UPDATE matches SET {read_col} = ? WHERE id = ? AND {read_col} < ?",
                (history[-1]["id"], match["id"], history[-1]["id"]),
            )

        line = bot_reply_line(bot_profile, history, match["id"], count)
        db.execute(
            "INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
            (match["id"], bot_id, line),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


@app.route("/chat/<int:match_id>/messages")
@login_required
def chat_messages(match_id):
    """JSON feed of messages newer than ?after=<id>.

    Returns immediately. The browser polls this on a short tick rather than
    holding a long-poll open: with the app scaled out, the instance that
    stores a message is usually not the one holding the recipient's open
    request, so an in-process wake-up could never reach them.
    """
    match, profiles = get_match_participants(match_id)
    user = current_user()
    if match is None:
        return {"error": "not found"}, 404
    if user["id"] not in (match["user_a"], match["user_b"]) and not user["is_admin"]:
        return {"error": "forbidden"}, 403

    is_participant = user["id"] in (match["user_a"], match["user_b"])
    if is_participant:
        match = resolve_match(match_id) or match
        maybe_bot_reply(match, profiles)

    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0

    rows = fetch_messages_after(match_id, after)

    # The tab being open and polling is itself the "seen" signal -- mark
    # read up to the newest message in the room, not just the ones this
    # particular poll happened to return, since the poll started counting
    # from the browser's own high-water mark rather than the room's.
    their_read_id = None
    if is_participant:
        latest_id = get_db().execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM messages WHERE match_id = ?",
            (match_id,),
        ).fetchone()["m"]
        mark_read(match, user["id"], latest_id)
        match = get_db().execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        their_read_id = match[their_read_column(match, user["id"])]

    return {
        "messages": [message_dict(r) for r in rows],
        "their_read_id": their_read_id,
    }


@app.route("/chat/<int:match_id>/send", methods=["POST"])
@login_required
@rate_limited("send", limit=30, window_seconds=60, by="user")
def send_message(match_id):
    match, _ = get_match_participants(match_id)
    wants_json = "application/json" in request.headers.get("Accept", "")

    def fail(msg, code):
        if wants_json:
            return {"error": msg}, code
        flash(msg)
        target = "chats" if match is None else "chat"
        kwargs = {} if match is None else {"match_id": match_id}
        return redirect(url_for(target, **kwargs))

    if match is None:
        return fail("That chatroom does not exist.", 404)

    body = request.form.get("body", "").strip()
    # Messages are always sent as the logged-in user, who must be one
    # of the two matched participants.
    sender_id = current_uid()
    if sender_id not in (match["user_a"], match["user_b"]):
        return fail("Only the two matched members can write in this chatroom.", 403)

    # The 5-minute lock is server-authoritative: a disabled composer in the
    # browser is not enough, since this endpoint can be hit directly.
    match = resolve_match(match_id) or match
    phase = match_phase(match)
    if phase not in ("timed", "active"):
        msg = "The match hasn't opened for chat yet." if phase == "reveal" \
            else "Time's up — press Continue or Unmatch to move on." if phase == "deciding" \
            else "This match has ended."
        return fail(msg, 409)

    if not body:
        return fail("Message can't be empty.", 400)
    # The composer sets maxlength, which is a courtesy to the person typing
    # and no obstacle at all to anyone posting here directly. Five minutes
    # of conversation has no legitimate need for a novel-length message, and
    # without a cap the only limit on a single row is MAX_CONTENT_LENGTH.
    if len(body) > MESSAGE_MAX_CHARS:
        return fail(f"That message is too long — {MESSAGE_MAX_CHARS} characters max.", 400)

    db = get_db()
    new_id = db.insert_returning_id(
        "INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
        (match_id, sender_id, body),
    )
    db.commit()

    if wants_json:
        row = db.execute(
            """
            SELECT msg.*, COALESCE(p.name, 'Deleted member') AS sender_name FROM messages msg
            LEFT JOIN profiles p ON p.user_id = msg.sender_id
            WHERE msg.id = ?
            """,
            (new_id,),
        ).fetchone()
        return {"message": message_dict(row)}

    return redirect(url_for("chat", match_id=match_id))


@app.route("/photo/<int:photo_id>")
@login_required
def photo(photo_id):
    """Serve a single photo, gated by can_view_photos().

    404s for anything the caller shouldn't see rather than 403 — a 403
    would itself confirm the photo exists. mime comes from the row (set by
    sniff_image_mime() at upload time, never from client input), and the
    response carries nosniff plus a private cache so it isn't handed to a
    shared cache or reinterpreted by the browser.
    """
    row = get_db().execute(
        "SELECT user_id, data, mime FROM photos WHERE id = ?", (photo_id,)
    ).fetchone()
    if row is None:
        abort(404)

    user = current_user()
    if not can_view_photos(row["user_id"], user["id"], user["is_admin"]):
        abort(404)

    data = bytes(row["data"])
    # Photos are the heaviest thing the app serves -- up to PHOTO_MAX_BYTES
    # each, straight out of Postgres, six to a profile. An ETag turns every
    # revisit into a 304 with no body, which is the difference between a
    # profile costing megabytes each time and costing it once. Weak-free and
    # content-derived, so replacing a photo at the same id still busts it.
    etag = '"%s"' % hashlib.sha256(data).hexdigest()[:16]
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag,
                                             "Cache-Control": "private, max-age=3600"})

    return Response(
        data,
        mimetype=row["mime"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=3600",
            "ETag": etag,
        },
    )


STARTUP_ERROR = None


def startup():
    """Open the pool and make sure the schema is in place.

    A failure here must not kill the worker. Gunicorn binds the port before
    forking, so a worker that dies on import still looks like a healthy
    deploy — the revision goes live and every request 503s with the real
    error nowhere in sight. Record it instead and let /healthz report it.
    """
    global STARTUP_ERROR
    try:
        POOL.open()
        init_db()
        STARTUP_ERROR = None
    except Exception as exc:  # surfaced via /healthz, logged for Cloud Run
        STARTUP_ERROR = exc
        app.logger.exception("startup failed: cannot reach the database")


@app.post("/tasks/purge-deletions")
def run_purge_deletions():
    """Finish deletions whose grace period has run out.

    There is no background worker here -- Cloud Run only runs while it is
    serving a request -- so this is an endpoint for Cloud Scheduler to hit
    daily, authenticated with a shared secret rather than a login.

    Without TASK_TOKEN set it refuses outright: an open endpoint that
    permanently erases accounts is worse than one nobody calls. Exempt from
    CSRF because the caller is a scheduler, not a browser with a session.
    """
    if not TASK_TOKEN:
        return "task endpoint disabled: TASK_TOKEN is not set", 503
    presented = request.headers.get("X-Task-Token", "")
    if not secrets.compare_digest(presented, TASK_TOKEN):
        return "forbidden", 403
    purged = purge_due_deletions()
    # One scheduled call does both jobs: a retention schedule that depends on
    # somebody remembering to wire up a second cron is one that quietly stops
    # being enforced.
    expired = purge_expired_data()
    return {"purged": purged, "expired": expired}, 200


# Rendered once per process and held here. The stylesheet is a Jinja
# template (it interpolates url_for() for the wordmark mask) but it depends
# on nothing request-specific, so re-rendering 134KB on every page view was
# work with no result. The digest is of the rendered bytes, so a deploy that
# changes a colour changes the URL and nobody serves a stale sheet.
_STYLESHEET = {}


def _render_stylesheet():
    if not _STYLESHEET:
        body = render_template("velvt.css")
        _STYLESHEET["body"] = body
        _STYLESHEET["digest"] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return _STYLESHEET


@app.get("/favicon.ico")
def favicon():
    """Browsers ask for this whether or not a <link rel="icon"> says to.

    Without it every page view logged a 404. Serving the SVG under the .ico
    name is fine -- the content type is what a browser reads, not the
    extension -- and it saves carrying a second copy of the mark in a format
    nothing has needed since IE.
    """
    return send_from_directory(app.static_folder, "velvt-icon.svg",
                               mimetype="image/svg+xml")


@app.route("/velvt.<digest>.css")
def stylesheet(digest):
    """The whole design system, at a URL that changes when it does.

    Immutable for a year: the digest is in the path, so a changed sheet is a
    different URL and there is nothing to revalidate. This is the single
    biggest thing the app sends -- inlined into every page it was 134KB of
    every navigation, uncacheable by construction.
    """
    sheet = _render_stylesheet()
    if digest != sheet["digest"]:
        # An old digest is a stale page asking for a sheet that no longer
        # exists. Send the current one rather than 404ing an unstyled page.
        return redirect(url_for("stylesheet", digest=sheet["digest"]))
    return Response(
        sheet["body"],
        mimetype="text/css",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.route("/lang/<code>", methods=["GET", "POST"])
def set_language(code):
    """Switch language and return the visitor to the page they were reading.

    The redirect target comes from the form/query rather than Referer, and has
    to be a same-site path: an open redirect here would be a free phishing
    hop, and this endpoint is reachable without signing in.

    GET as well as POST, and the switcher itself is a plain link. A GET that
    changes state is normally worth avoiding, but the only state here is a
    display preference in the caller's own session -- the worst a forged
    request achieves is showing someone Dutch -- and a link is what works
    without JavaScript, survives being shared, and needs no CSRF token on a
    page a signed-out visitor is reading.
    """
    lang = normalize_language(code)
    if lang:
        session[LANG_SESSION_KEY] = lang

    target = request.values.get("next") or "/"
    # Only ever a path on this site: no scheme, no host, and no
    # protocol-relative "//evil.example", which a browser reads as a host.
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return redirect(target)


@app.get("/healthz")
@app.get("/-/health")
def healthz():
    """Readiness, for Cloud Run's startup probe and for anything watching.

    Two paths, same answer. The probe is configured against /healthz and
    reaches the container directly, so that one has always worked -- this
    revision going live at all is the proof, since a failing probe is what
    stops one being promoted. But Google's frontend intercepts the literal
    /healthz on the way in, so through velvt.nl it answers with Google's own
    404 page and never reaches Flask. /-/health is the path to point an
    external monitor at.

    Retries the schema init, so a database that was merely slow to accept
    connections recovers on its own rather than needing a redeploy.

    A configuration error fails the probe deliberately: a revision missing
    its secrets should never go live at all. Failing here keeps the
    previous, working revision serving instead of promoting one that
    answers every request with a 503.
    """
    if CONFIG_ERROR:
        return f"misconfigured: {CONFIG_ERROR}", 503
    if STARTUP_ERROR is not None:
        startup()
    if STARTUP_ERROR is not None:
        return f"db unavailable: {STARTUP_ERROR}", 503
    return "ok", 200


startup()

if __name__ == "__main__":
    # host/port/debug are overridable for deployment (Cloud Run sets PORT;
    # FLASK_DEBUG=0 turns off the reloader/debugger). In production this
    # runs behind gunicorn ("gunicorn app:app"), which skips this block.
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") not in ("0", "false", "no")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
