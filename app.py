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

import hashlib
import math
import os
import re
import secrets
import time
from datetime import datetime as dt, timezone

import requests
import psycopg
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
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)


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
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "admin12345")
AUTO_LOGIN = os.environ.get("AUTO_LOGIN", "0") not in ("0", "false", "no")

GENDERS = ["Woman", "Man", "Non-binary"]

SEEKING_OPTIONS = ["Women", "Men", "Everyone"]

# Which profile genders each "looking for" choice accepts.
SEEKING_MATCHES = {
    "Women": {"Woman"},
    "Men": {"Man"},
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

# How long a search must run before it can be paired. The demo pool is
# always populated, so without this every search resolves on its first
# attempt and the waiting screen never actually shows.
MIN_SEARCH_SECONDS = 7

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


def can_view_photos(owner_id, viewer_id, viewer_is_admin):
    """Photos unlock only once both sides have pressed Continue — i.e. a
    matches row exists between the two with status='active'. That is
    exactly the same state resolve_match() writes, so this needs no
    bookkeeping of its own."""
    if viewer_id == owner_id or viewer_is_admin:
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
SAMPLE_WANTS = [
    "Someone easy to talk to who's up for spontaneous plans.",
    "A genuine connection built on honesty and a shared sense of humour.",
    "Someone who's as curious about the world as I am.",
]
SAMPLE_NEEDS = [
    "Honesty and good communication, above everything else.",
    "Someone who makes time, even when life gets busy.",
    "Kindness — to me and to everyone else around them.",
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
    "pref_height_min",
    "pref_height_max",
    "pref_fitness_level",
    "pref_hair_color",
    "pref_eye_color",
    "pref_tattoos",
    "bio",
    "interests",
    "hobbies",
    "wants",
    "needs",
    "relationship_type",
]
# Handled separately via request.form.getlist() — a checkbox group, not a
# single value, so it doesn't fit the uniform PROFILE_FIELDS .get() loop.
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
        "age": {"min": 18, "max": 75},
        "gender": GENDERS,
        "seeking": SEEKING_OPTIONS,
        "location": CITY_CHOICES,
        "bio": SAMPLE_BIOS,
        "interests": SAMPLE_INTERESTS,
        "hobbies": SAMPLE_HOBBIES,
        "wants": SAMPLE_WANTS,
        "needs": SAMPLE_NEEDS,
        "relationship_type": RELATIONSHIP_TYPES,
        "height_cm": {"min": HEIGHT_MIN_CM, "max": HEIGHT_MAX_CM},
        "body_type": BODY_TYPES,
        "fitness_level": FITNESS_LEVELS,
        "hair_color": HAIR_COLORS,
        "eye_color": EYE_COLORS,
        "tattoos": TATTOO_LEVELS,
        "pref_height_min": {"min": HEIGHT_MIN_CM, "max": HEIGHT_MAX_CM},
        "pref_height_max": {"min": HEIGHT_MIN_CM, "max": HEIGHT_MAX_CM},
        "pref_body_types": BODY_TYPES,
        "pref_fitness_level": FITNESS_LEVELS,
        "pref_hair_color": HAIR_COLORS,
        "pref_eye_color": EYE_COLORS,
        "pref_tattoos": TATTOO_LEVELS,
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

-- One row per member currently looking for a live match.
CREATE TABLE IF NOT EXISTS searches (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    seeking TEXT NOT NULL DEFAULT '',
    age_min INTEGER NOT NULL DEFAULT 18,
    age_max INTEGER NOT NULL DEFAULT 120,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bring databases created before the per-filter toggles existed up to date.
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_gender BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_age BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_relationship BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE searches ADD COLUMN IF NOT EXISTS use_distance BOOLEAN NOT NULL DEFAULT TRUE;

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS photos_user_id_idx ON photos (user_id, is_primary);
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


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please sign in first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None or not user["is_admin"]:
            flash("Only the admin can do that.")
            return redirect(url_for("live_search"))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


@app.before_request
def auto_login_admin():
    """Optional dev shortcut (AUTO_LOGIN=1): browse as admin without logging in."""
    if not AUTO_LOGIN or session.get("user_id") is not None:
        return
    admin = get_db().execute(
        "SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (ADMIN_USERNAME,)
    ).fetchone()
    if admin is not None:
        session["user_id"] = admin["id"]


MOCKUPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mockups")


@app.route("/lab")
def design_lab():
    """Serve the design iteration lab. Static, self-contained, no auth —
    it renders mock data only and never touches the database."""
    return send_from_directory(MOCKUPS_DIR, "velvet-lab.html")


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("live_search"))
    searching_now = get_db().execute(
        "SELECT COUNT(*) AS n FROM searches WHERE status = 'waiting'"
    ).fetchone()["n"]
    return render_template("landing.html", searching_now=searching_now)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("live_search"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not username or len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."

        if error is None:
            db = get_db()
            try:
                new_id = db.insert_returning_id(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.execute("INSERT INTO profiles (user_id) VALUES (?)", (new_id,))
                db.commit()
            except psycopg.errors.UniqueViolation:
                db.rollback()
                error = "That username is already taken."
            else:
                session.clear()
                session["user_id"] = new_id
                flash("Welcome! Now set up your profile.")
                return redirect(url_for("edit_profile"))

        flash(error)

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("live_search"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("live_search"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def validate_profile(values):
    """Return (error, age) for a submitted profile form."""
    age = None
    error = None
    if not values["name"]:
        error = "Please enter your name."
    else:
        try:
            age = int(values["age"])
            if not 18 <= age <= 120:
                error = "Age must be between 18 and 120."
        except (TypeError, ValueError):
            error = "Please enter a valid age."

    if values["relationship_type"] and values["relationship_type"] not in RELATIONSHIP_TYPES:
        error = "Please pick a relationship type from the list."
    if values["gender"] and values["gender"] not in GENDERS:
        error = "Please pick a gender from the list."
    if values["seeking"] and values["seeking"] not in SEEKING_OPTIONS:
        error = "Please pick who you're looking for from the list."

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

    # Preferences: height range
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


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}
        # A checkbox group, so it arrives as repeated fields rather than one
        # value; stored as CSV.
        values[PREF_BODY_TYPES_FIELD] = ",".join(
            request.form.getlist(PREF_BODY_TYPES_FIELD)
        )
        error, age = validate_profile(values)
        phys_error, phys = validate_physical(values)
        error = error or phys_error

        # Photos: sniff magic bytes rather than trusting the browser's
        # Content-Type, cap size and count. Validated up front so a bad
        # upload doesn't half-save the rest of the profile.
        uploads = []
        primary_file = request.files.get("profile_picture")
        extra_files = request.files.getlist("photos")
        candidates = [(True, primary_file)] if primary_file and primary_file.filename else []
        candidates += [(False, f) for f in extra_files if f and f.filename]
        for is_primary, f in candidates:
            data = f.read(PHOTO_MAX_BYTES + 1)
            if len(data) > PHOTO_MAX_BYTES:
                error = error or "Each photo must be under 2 MB."
                break
            mime = sniff_image_mime(data)
            if mime is None or mime not in PHOTO_ALLOWED_MIMES:
                error = error or "Photos must be JPEG, PNG, or WebP."
                break
            uploads.append((is_primary, mime, data))
        else:
            if uploads:
                existing_count = db.execute(
                    "SELECT COUNT(*) AS n FROM photos WHERE user_id = ?", (user_id,)
                ).fetchone()["n"]
                if existing_count + len(uploads) > PHOTO_MAX_PER_USER:
                    error = error or f"You can have at most {PHOTO_MAX_PER_USER} photos."

        if error is None:
            db.execute(
                """
                UPDATE profiles SET
                    name = ?, age = ?, gender = ?, seeking = ?, location = ?,
                    height_cm = ?, body_type = ?, fitness_level = ?,
                    hair_color = ?, eye_color = ?, tattoos = ?,
                    pref_height_min = ?, pref_height_max = ?,
                    pref_body_types = ?, pref_fitness_level = ?,
                    pref_hair_color = ?, pref_eye_color = ?, pref_tattoos = ?,
                    bio = ?, interests = ?, hobbies = ?, wants = ?, needs = ?,
                    relationship_type = ?, updated_at = NOW()
                WHERE user_id = ?
                """,
                (
                    values["name"], age, values["gender"], values["seeking"],
                    values["location"],
                    phys["height_cm"], phys["body_type"], phys["fitness_level"],
                    phys["hair_color"], phys["eye_color"], phys["tattoos"],
                    phys["pref_height_min"], phys["pref_height_max"],
                    phys[PREF_BODY_TYPES_FIELD], phys["pref_fitness_level"],
                    phys["pref_hair_color"], phys["pref_eye_color"],
                    phys["pref_tattoos"],
                    values["bio"], values["interests"],
                    values["hobbies"], values["wants"], values["needs"],
                    values["relationship_type"], user_id,
                ),
            )
            for is_primary, mime, data in uploads:
                if is_primary:
                    db.execute("UPDATE photos SET is_primary = FALSE WHERE user_id = ?", (user_id,))
                db.insert_returning_id(
                    "INSERT INTO photos (user_id, data, mime, is_primary) VALUES (?, ?, ?, ?)",
                    (user_id, data, mime, is_primary),
                )
            db.commit()
            flash("Profile saved.")
            return redirect(url_for("view_profile", user_id=user_id))

        flash(error)
        profile = dict(values)
    else:
        profile = dict(
            db.execute(
                "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        )

    # Shown as tiles so you can see what you already have while editing.
    photos = db.execute(
        "SELECT id FROM photos WHERE user_id = ? ORDER BY is_primary DESC, id",
        (user_id,),
    ).fetchall()
    strength_pct, strength_hint = profile_strength(profile, len(photos))
    chips, chosen = interest_choices(profile.get("interests"))

    return render_template(
        "profile_edit.html",
        profile=profile,
        photos=photos,
        strength_pct=strength_pct,
        strength_hint=strength_hint,
        bio_max=BIO_MAX_CHARS,
        interest_chips=chips,
        interest_chosen=chosen,
        relationship_types=RELATIONSHIP_TYPES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
        body_types=BODY_TYPES,
        fitness_levels=FITNESS_LEVELS,
        hair_colors=HAIR_COLORS,
        eye_colors=EYE_COLORS,
        tattoo_levels=TATTOO_LEVELS,
        height_min=HEIGHT_MIN_CM,
        height_max=HEIGHT_MAX_CM,
        sample_profile=sample_profile_data(),
        photo_max_bytes=PHOTO_MAX_BYTES,
        photo_max_per_user=PHOTO_MAX_PER_USER,
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

    if row is None:
        flash("That profile does not exist.")
        return redirect(url_for("live_search"))

    user = current_user()
    can_view = can_view_photos(user_id, user["id"], user["is_admin"])
    photos = (
        get_db()
        .execute(
            "SELECT id, is_primary FROM photos WHERE user_id = ? ORDER BY is_primary DESC, id",
            (user_id,),
        )
        .fetchall()
        if can_view
        else []
    )

    return render_template(
        "profile_view.html",
        profile=row,
        is_own=(user_id == session["user_id"]),
        can_view_photos=can_view,
        photos=photos,
    )


@app.route("/admin/profiles/new", methods=["GET", "POST"])
@admin_required
def admin_new_profile():
    db = get_db()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}
        values[PREF_BODY_TYPES_FIELD] = ",".join(
            request.form.getlist(PREF_BODY_TYPES_FIELD)
        )

        error = None
        phys = None
        if not username or len(username) < 3:
            error = "Username must be at least 3 characters."
        elif password and len(password) < 8:
            error = "Password must be at least 8 characters (or leave it empty)."
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
                         eye_color, tattoos, pref_height_min, pref_height_max,
                         pref_body_types, pref_fitness_level, pref_hair_color,
                         pref_eye_color, pref_tattoos, bio,
                         interests, hobbies, wants, needs, relationship_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id, values["name"], age, values["gender"],
                        values["seeking"], values["location"],
                        phys["height_cm"], phys["body_type"],
                        phys["fitness_level"], phys["hair_color"],
                        phys["eye_color"], phys["tattoos"],
                        phys["pref_height_min"], phys["pref_height_max"],
                        phys[PREF_BODY_TYPES_FIELD],
                        phys["pref_fitness_level"], phys["pref_hair_color"],
                        phys["pref_eye_color"], phys["pref_tattoos"],
                        values["bio"],
                        values["interests"], values["hobbies"], values["wants"],
                        values["needs"], values["relationship_type"],
                    ),
                )
                db.commit()
            except psycopg.errors.UniqueViolation:
                db.rollback()
                error = "That username is already taken."
            else:
                flash(f"Profile for {values['name']} (@{username}) created.")
                return redirect(url_for("view_profile", user_id=new_id))

        flash(error)
        profile = dict(values)
        profile["username"] = username
    else:
        profile = {f: "" for f in PROFILE_FIELDS}
        profile[PREF_BODY_TYPES_FIELD] = ""
        profile["username"] = ""

    chips, chosen = interest_choices(profile.get("interests"))

    return render_template(
        "admin_profile_new.html",
        profile=profile,
        bio_max=BIO_MAX_CHARS,
        interest_chips=chips,
        interest_chosen=chosen,
        relationship_types=RELATIONSHIP_TYPES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
        body_types=BODY_TYPES,
        fitness_levels=FITNESS_LEVELS,
        hair_colors=HAIR_COLORS,
        eye_colors=EYE_COLORS,
        tattoo_levels=TATTOO_LEVELS,
        height_min=HEIGHT_MIN_CM,
        height_max=HEIGHT_MAX_CM,
        sample_profile=sample_profile_data(),
    )


def _tokens(*texts):
    """Split free-text fields into a set of lowercase keywords."""
    words = set()
    for text in texts:
        for tok in re.split(r"[,;/\n]+|\s+", (text or "").lower()):
            tok = tok.strip(".!?()\"'")
            if len(tok) > 2:
                words.add(tok)
    return words


def city_coords(location):
    """Look up coordinates for a location string like 'Berlin, Germany'."""
    if not location:
        return None
    key = location.split(",")[0].strip().lower()
    return CITY_COORDS.get(key)


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
    """
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


def searches_compatible(s1, s2):
    """True when two live searches satisfy each other's criteria.

    Both directions must hold: each person's gender must be one the other
    is looking for, each person's age must fall inside the other's
    requested range, each person's physical traits must satisfy the
    other's step-3 filters, and the distance between them must sit inside
    both radii. Relationship type only blocks when both named one and they
    differ. Unset fields are treated as "no preference".

    Each side can also switch a filter off (searches.use_gender/use_age/
    use_relationship/use_distance), which relaxes only that side's own
    check — the other person's filter still applies, so disabling one
    filter does not by itself guarantee a match. Missing keys (hand-built
    dicts, pre-migration rows) default to "on" via .get(key, True), which
    matches the column's own DEFAULT TRUE.
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

    if not (gender_ok(s1, s2["gender"]) and gender_ok(s2, s1["gender"])):
        return False
    if not (age_ok(s1, s2["age"]) and age_ok(s2, s1["age"])):
        return False
    if not (physical_ok(s1, s2) and physical_ok(s2, s1)):
        return False
    if (
        s1.get("use_relationship", True)
        and s2.get("use_relationship", True)
        and s1["relationship_type"]
        and s2["relationship_type"]
        and s1["relationship_type"] != s2["relationship_type"]
    ):
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
            """
            SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
            JOIN profiles p ON p.user_id = s.user_id
            WHERE s.status = 'waiting' AND s.user_id != ?
              AND s.created_at <= NOW() - (? * INTERVAL '1 second')
            ORDER BY s.created_at
            """,
            (user_id, MIN_SEARCH_SECONDS),
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
        "SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)
    ).fetchone()
    return me if me is not None and me["name"] else None


@app.route("/search", methods=["GET", "POST"])
@login_required
def live_search():
    """Step 1: choose the kind of connection you're searching for."""
    if require_profile() is None:
        flash("Fill in your profile first so others can match with you.")
        return redirect(url_for("edit_profile"))

    if request.method == "POST":
        wanted = request.form.get("relationship_type", "")
        if wanted not in RELATIONSHIP_TYPES:
            flash("Please choose what kind of connection you want.")
        else:
            return redirect(url_for("search_criteria", relationship_type=wanted))

    existing = get_db().execute(
        "SELECT * FROM searches WHERE user_id = ?", (session["user_id"],)
    ).fetchone()

    return render_template(
        "search_start.html",
        relationship_types=RELATIONSHIP_TYPES,
        existing=existing,
    )


@app.route("/search/criteria", methods=["GET", "POST"])
@login_required
def search_criteria():
    """Step 2: gender, age range, location + radius, interests — then search."""
    db = get_db()
    user_id = session["user_id"]
    me = require_profile()
    if me is None:
        flash("Fill in your profile first so others can match with you.")
        return redirect(url_for("edit_profile"))

    wanted = request.values.get("relationship_type", "")
    if wanted not in RELATIONSHIP_TYPES:
        return redirect(url_for("live_search"))

    existing = db.execute(
        "SELECT * FROM searches WHERE user_id = ?", (user_id,)
    ).fetchone()

    if request.method == "POST":
        seeking = request.form.get("seeking", "")
        interests = request.form.get("interests", "").strip()
        location = request.form.get("location", "").strip()

        # Set only when the combobox in step 2 resolved a geocoder pick; the
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

        error = None
        if seeking and seeking not in SEEKING_OPTIONS:
            error = "Please choose who you're looking for."

        try:
            age_min = int(request.form.get("age_min", 18))
            age_max = int(request.form.get("age_max", 120))
            radius_km = int(request.form.get("radius_km", RADIUS_MAX_KM))
        except ValueError:
            error = "Please check the age range and radius."
            age_min, age_max, radius_km = 18, 120, RADIUS_MAX_KM

        if error is None:
            if not 18 <= age_min <= age_max <= 120:
                error = "Age range must run from 18 up to 120."
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

        if error:
            flash(error)
        else:
            db.execute(
                """
                INSERT INTO searches
                    (user_id, seeking, age_min, age_max, relationship_type,
                     interests, location, lat, lng, radius_km,
                     pref_height_min, pref_height_max, pref_body_types,
                     pref_fitness_level, pref_hair_color, pref_eye_color,
                     pref_tattoos, status, match_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting', NULL, NOW())
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
                    -- Values carry over to the next search (the form above
                    -- is prefilled from this row), but the on/off switches
                    -- do not: the form shows every value as applying, so a
                    -- filter silently left off from a previous search would
                    -- contradict what the user just confirmed here.
                    use_gender = TRUE,
                    use_age = TRUE,
                    use_relationship = TRUE,
                    use_distance = TRUE,
                    status = 'waiting',
                    match_id = NULL,
                    created_at = NOW()
                """,
                (
                    user_id, seeking, age_min, age_max, wanted, interests,
                    location, lat, lng, radius_km,
                    phys["pref_height_min"], phys["pref_height_max"],
                    phys[PREF_BODY_TYPES_FIELD], phys["pref_fitness_level"],
                    phys["pref_hair_color"], phys["pref_eye_color"],
                    phys["pref_tattoos"],
                ),
            )
            db.commit()

            # No try_pair() here: the search is brand new, so it cannot be
            # paired yet anyway (see MIN_SEARCH_SECONDS). The waiting page's
            # poll picks it up once it ripens.
            return redirect(url_for("search_waiting"))

    return render_template(
        "search_criteria.html",
        me=me,
        existing=existing,
        wanted=wanted,
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
    )


# Small TTL cache so repeated keystrokes (and repeated users typing the same
# city) don't each hit the geocoder. Capped so a burst of unique queries
# can't grow this unboundedly across a long-running instance.
_PLACES_CACHE = {}
_PLACES_CACHE_TTL = 600
_PLACES_CACHE_MAX = 500


@app.route("/api/places")
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
    """Live pool readout for wizard step 4 — how many people fit the
    criteria you're about to save, plus suggestions if the answer is zero.

    Writes nothing: builds a synthetic search row in the exact shape
    searches_compatible() expects and reuses the existing engine as-is, so
    the count and suggestions here are guaranteed consistent with what
    /search/waiting will show after you actually start searching.
    """
    me = require_profile()
    if me is None:
        return {"error": "profile incomplete"}, 400

    wanted = request.form.get("relationship_type", "")
    if wanted not in RELATIONSHIP_TYPES:
        return {"error": "invalid relationship_type"}, 400

    seeking = request.form.get("seeking", "")
    location = request.form.get("location", "").strip()
    try:
        lat = float(request.form.get("location_lat", "")) if request.form.get("location_lat") else None
        lng = float(request.form.get("location_lng", "")) if request.form.get("location_lng") else None
    except ValueError:
        lat = lng = None

    try:
        age_min = int(request.form.get("age_min", 18))
        age_max = int(request.form.get("age_max", 120))
        radius_km = int(request.form.get("radius_km", RADIUS_MAX_KM))
    except ValueError:
        return {"error": "invalid age or radius"}, 400

    phys_values = dict(request.form)
    phys_values[PREF_BODY_TYPES_FIELD] = ",".join(request.form.getlist(PREF_BODY_TYPES_FIELD))
    _phys_error, phys = validate_physical(phys_values)

    mine = {
        "user_id": session["user_id"],
        "seeking": seeking,
        "age_min": age_min,
        "age_max": age_max,
        "relationship_type": wanted,
        "location": location,
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        "use_gender": True,
        "use_age": True,
        "use_relationship": True,
        "use_distance": True,
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
        """
        SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        WHERE s.status = 'waiting' AND s.user_id != ?
        """,
        (session["user_id"],),
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
    """Which other relationship types, if switched to, would open up
    matches — each verified through searches_compatible(), most people
    admitted first."""
    results, seen = [], set()
    for o in others:
        rt = o["relationship_type"]
        if not rt or rt == mine["relationship_type"] or rt in seen:
            continue
        seen.add(rt)
        trial = dict(mine)
        trial["relationship_type"] = rt
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
        """
        SELECT s.*, p.gender, p.age, p.height_cm, p.body_type, p.fitness_level, p.hair_color, p.eye_color, p.tattoos FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        WHERE s.status = 'waiting' AND s.user_id != ?
        """,
        (user_id,),
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
        "if_all_relaxed": relaxed(
            use_gender=False, use_age=False, use_relationship=False, use_distance=False
        ),
        "age_suggestion": _minimal_age_suggestion(mine, others),
        "distance_suggestion": _minimal_distance_suggestion(mine, others),
        "relationship_suggestions": _relationship_suggestions(mine, others),
        "gender_suggestions": _gender_suggestions(mine, others),
    }


def search_filter_rows(mine, others, blockers):
    """One dict per filter parameter, for a uniform template loop.

    Each row: key, label, value_text, enabled (None when not toggleable),
    constrains (does this filter currently reject someone?), note (an
    honest caveat, if any), and suggestion (the concrete fix, if any).
    Interests is included but is NOT a filter — searches_compatible()
    never reads it, it only breaks ties in try_pair() — so it is shown
    read-only with a note saying exactly that.
    """
    rows = []

    rows.append({
        "key": "gender",
        "label": "Who I'm looking for",
        "value_text": mine["seeking"] or "Anyone",
        "enabled": mine.get("use_gender", True),
        "constrains": blockers["if_any_gender"] > blockers["current_count"],
        "note": None,
        "suggestion": blockers["gender_suggestions"][0]
            if blockers["gender_suggestions"] else None,
    })

    rows.append({
        "key": "age",
        "label": "Age range",
        "value_text": f"{mine['age_min']}–{mine['age_max']}",
        "enabled": mine.get("use_age", True),
        "constrains": blockers["if_any_age"] > blockers["current_count"],
        "note": None,
        "suggestion": blockers["age_suggestion"],
    })

    rows.append({
        "key": "relationship",
        "label": "Connection",
        "value_text": mine["relationship_type"] or "Anything",
        "enabled": mine.get("use_relationship", True),
        "constrains": blockers["if_any_connection"] > blockers["current_count"],
        "note": None,
        "suggestion": blockers["relationship_suggestions"][0]
            if blockers["relationship_suggestions"] else None,
    })

    if not mine["location"]:
        distance_value = "Anywhere"
        distance_note = None
    elif mine["radius_km"] >= RADIUS_MAX_KM:
        distance_value = f"{mine['location']} · any distance"
        distance_note = None
    else:
        distance_value = f"{mine['location']} · within {mine['radius_km']} km"
        distance_note = None
    if mine["location"] and search_coords(mine) is None:
        distance_note = "We don't recognise this city, so distance isn't being applied."
    rows.append({
        "key": "distance",
        "label": "Distance",
        "value_text": distance_value,
        "enabled": mine.get("use_distance", True),
        "constrains": blockers["if_any_distance"] > blockers["current_count"],
        "note": distance_note,
        "suggestion": blockers["distance_suggestion"],
    })

    rows.append({
        "key": "interests",
        "label": "Interests",
        "value_text": mine["interests"] or "None listed",
        "enabled": None,
        "constrains": False,
        "note": "Not a filter — only used to rank who you're paired with first.",
        "suggestion": None,
    })

    return rows


@app.route("/search/waiting")
@login_required
def search_waiting():
    user_id = session["user_id"]
    mine, others = _search_pool(user_id)

    if mine is None or mine["status"] == "cancelled":
        return redirect(url_for("live_search"))
    if mine["status"] == "matched" and mine["match_id"]:
        return redirect(url_for("chat", match_id=mine["match_id"]))

    blockers = search_blockers(mine, others)

    return render_template(
        "search_waiting.html",
        search=mine,
        waiting=len(others),
        radius_max=RADIUS_MAX_KM,
        blockers=blockers,
        filter_rows=search_filter_rows(mine, others, blockers),
    )


@app.route("/search/status")
@login_required
def search_status():
    """Polled by the waiting page; reports whether a match exists yet.

    Returns immediately rather than holding the request open. Waking the
    exact instance that happens to hold a waiting request is not possible
    once the app is scaled out, so the waiting page polls on a short tick
    instead (see templates/search_waiting.html).
    """
    user_id = session["user_id"]

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
        (session["user_id"],),
    )
    db.commit()
    flash("Search stopped.")
    return redirect(url_for("live_search"))


# Whitelisted so the toggle route can build SQL identifiers from a request
# value without ever interpolating the value itself — only the mapped
# column name (one of these four fixed strings) reaches the query.
FILTER_TOGGLE_COLUMNS = {
    "gender": "use_gender",
    "age": "use_age",
    "relationship": "use_relationship",
    "distance": "use_distance",
}


@app.route("/search/filters/toggle", methods=["POST"])
@login_required
def search_filters_toggle():
    """Flip one filter on/off without touching the value behind it."""
    user_id = session["user_id"]
    column = FILTER_TOGGLE_COLUMNS.get(request.form.get("filter", ""))
    if column is None:
        flash("Unknown filter.")
        return redirect(url_for("search_waiting"))

    db = get_db()
    db.execute(
        f"UPDATE searches SET {column} = NOT {column} "
        "WHERE user_id = ? AND status = 'waiting'",
        (user_id,),
    )
    db.commit()
    # Disabling a filter can immediately make an existing waiting searcher
    # compatible, so retry pairing now rather than waiting for the next poll.
    try_pair(user_id)
    return redirect(url_for("search_waiting"))


@app.route("/search/filters/apply", methods=["POST"])
@login_required
def search_filters_apply():
    """Apply the current suggested fix for one filter.

    The suggestion is recomputed here from the live pool rather than
    trusted from the submitted form, so a stale page can't write a value
    that no longer helps (or never did).
    """
    user_id = session["user_id"]
    key = request.form.get("filter", "")

    mine, others = _search_pool(user_id)
    if mine is None or mine["status"] != "waiting":
        return redirect(url_for("search_waiting"))
    blockers = search_blockers(mine, others)

    db = get_db()
    if key == "age" and blockers["age_suggestion"]:
        sug = blockers["age_suggestion"]
        db.execute(
            "UPDATE searches SET age_min = ?, age_max = ? "
            "WHERE user_id = ? AND status = 'waiting'",
            (sug["age_min"], sug["age_max"], user_id),
        )
    elif key == "distance" and blockers["distance_suggestion"]:
        sug = blockers["distance_suggestion"]
        db.execute(
            "UPDATE searches SET radius_km = ? WHERE user_id = ? AND status = 'waiting'",
            (sug["radius_km"], user_id),
        )
    elif key == "relationship" and blockers["relationship_suggestions"]:
        sug = blockers["relationship_suggestions"][0]
        db.execute(
            "UPDATE searches SET relationship_type = ? "
            "WHERE user_id = ? AND status = 'waiting'",
            (sug["relationship_type"], user_id),
        )
    elif key == "gender" and blockers["gender_suggestions"]:
        sug = blockers["gender_suggestions"][0]
        db.execute(
            "UPDATE searches SET seeking = ? WHERE user_id = ? AND status = 'waiting'",
            (sug["seeking"], user_id),
        )
    else:
        flash("That suggestion is no longer available — refresh and try again.")
        return redirect(url_for("search_waiting"))

    db.commit()
    try_pair(user_id)
    return redirect(url_for("search_waiting"))


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

    if phase != "deciding":
        return match

    users = db.execute(
        "SELECT id, is_bot FROM users WHERE id IN (?, ?)",
        (match["user_a"], match["user_b"]),
    ).fetchall()
    is_bot = {u["id"]: u["is_bot"] for u in users}

    decision_a, decision_b = match["decision_a"], match["decision_b"]
    if is_bot.get(match["user_a"]) and not decision_a:
        decision_a = "continue"
    if is_bot.get(match["user_b"]) and not decision_b:
        decision_b = "continue"

    grace_over = (now - match["paired_at"]).total_seconds() >= (
        REVEAL_SECONDS + TIMED_CHAT_SECONDS + DECISION_GRACE_SECONDS
    )

    new_status = None
    if decision_a == "unmatch" or decision_b == "unmatch":
        new_status = "ended"
    elif decision_a == "continue" and decision_b == "continue":
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
    user_id = session["user_id"]
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
    user_id = session["user_id"]
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
    }.get(match_phase(match), ())
    if choice in allowed:
        col = "decision_a" if user_id == match["user_a"] else "decision_b"
        db = get_db()
        db.execute(f"UPDATE matches SET {col} = ? WHERE id = ?", (choice, match_id))
        db.commit()
        match = resolve_match(match_id) or match

    wants_json = "application/json" in request.headers.get("Accept", "")
    if wants_json:
        return match_state_payload(match, user_id)
    return redirect(url_for("chat", match_id=match_id))


@app.route("/chats")
@login_required
def chats():
    user = current_user()
    query = """
        SELECT m.*,
               pa.name AS name_a, pb.name AS name_b,
               (SELECT body FROM messages WHERE match_id = m.id
                ORDER BY id DESC LIMIT 1) AS last_message
        FROM matches m
        JOIN profiles pa ON pa.user_id = m.user_a
        JOIN profiles pb ON pb.user_id = m.user_b
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
        rooms.append(room)
    rooms.sort(key=lambda r: (r["phase"] == "ended", -r["id"]))

    return render_template("chats.html", rooms=rooms)


@app.route("/chat/<int:match_id>")
@login_required
def chat(match_id):
    match, profiles = get_match_participants(match_id)
    user = current_user()
    if match is None:
        flash("That chatroom does not exist.")
        return redirect(url_for("chats"))

    is_participant = user["id"] in (match["user_a"], match["user_b"])
    if not is_participant and not user["is_admin"]:
        flash("That chatroom is private.")
        return redirect(url_for("chats"))

    if is_participant:
        match = resolve_match(match_id) or match
    phase = match_phase(match)

    messages = get_db().execute(
        """
        SELECT msg.*, p.name AS sender_name FROM messages msg
        JOIN profiles p ON p.user_id = msg.sender_id
        WHERE msg.match_id = ?
        ORDER BY msg.id
        """,
        (match_id,),
    ).fetchall()

    state = match_state_payload(match, user["id"]) if is_participant else None

    # Avatar for the chat header. Photos stay locked until both sides
    # continue, so this is None for most of a timed room and the header
    # falls back to the placeholder — the same gate /photo enforces, asked
    # here so the template never has to guess.
    other_photo_id = None
    if is_participant:
        other_id = match["user_b"] if user["id"] == match["user_a"] else match["user_a"]
        if can_view_photos(other_id, user["id"], user["is_admin"]):
            row = get_db().execute(
                "SELECT id FROM photos WHERE user_id = ? ORDER BY id LIMIT 1",
                (other_id,),
            ).fetchone()
            other_photo_id = row["id"] if row else None

    return render_template(
        "chat.html",
        match=match,
        profiles=profiles,
        messages=messages,
        me_id=session["user_id"],
        is_participant=is_participant,
        phase=phase,
        state=state,
        other_photo_id=other_photo_id,
        reveal_seconds=REVEAL_SECONDS,
        timed_seconds=TIMED_CHAT_SECONDS,
    )


def message_dict(row):
    return {
        "id": row["id"],
        "sender_id": row["sender_id"],
        "sender_name": row["sender_name"],
        "body": row["body"],
        "created_at": row["created_at"].isoformat(),
    }


def fetch_messages_after(match_id, after):
    return get_db().execute(
        """
        SELECT msg.*, p.name AS sender_name FROM messages msg
        JOIN profiles p ON p.user_id = msg.sender_id
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

    if user["id"] in (match["user_a"], match["user_b"]):
        match = resolve_match(match_id) or match
        maybe_bot_reply(match, profiles)

    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0

    rows = fetch_messages_after(match_id, after)
    return {"messages": [message_dict(r) for r in rows]}


@app.route("/chat/<int:match_id>/send", methods=["POST"])
@login_required
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
    sender_id = session["user_id"]
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

    db = get_db()
    new_id = db.insert_returning_id(
        "INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
        (match_id, sender_id, body),
    )
    db.commit()

    if wants_json:
        row = db.execute(
            """
            SELECT msg.*, p.name AS sender_name FROM messages msg
            JOIN profiles p ON p.user_id = msg.sender_id
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

    return Response(
        bytes(row["data"]),
        mimetype=row["mime"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=3600",
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


@app.get("/healthz")
def healthz():
    """Readiness for Cloud Run's startup probe.

    Retries the schema init, so a database that was merely slow to accept
    connections recovers on its own rather than needing a redeploy.
    """
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
