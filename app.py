"""Dating website — Flask app with login, registration, and profiles.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser. Register an account,
fill in your profile, and browse other members.

Data is stored in a local SQLite file (dating.db, or wherever DATABASE_PATH
points). Set APP_SECRET_KEY to keep sessions valid across restarts.

An admin account is created automatically on startup (username "admin",
password from APP_ADMIN_PASSWORD, default "admin12345"). Anyone can
register an account and log in. Set AUTO_LOGIN=1 to skip the login page
during local development and browse as admin automatically.
"""

import math
import os
import re
import secrets
import sqlite3
import threading
import time

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

DATABASE = os.environ.get("DATABASE_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dating.db"
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
}

# Offered in the location picker, nicely cased.
CITY_CHOICES = [
    "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart",
    "Düsseldorf", "Leipzig", "Dresden", "Hannover", "Bremen", "Nuremberg",
    "Essen", "Dortmund", "Vienna", "Zurich", "Amsterdam", "Basel", "Salzburg",
]

RADIUS_MAX_KM = 500  # slider maximum; at the top it means "anywhere"

RELATIONSHIP_TYPES = [
    "Long-term relationship",
    "Short-term relationship",
    "Friendship",
    "Casual dating",
    "Marriage",
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


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
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
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_a, user_b),
            CHECK (user_a < user_b)
        );

        -- One row per member currently looking for a live match.
        CREATE TABLE IF NOT EXISTS searches (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            seeking TEXT NOT NULL DEFAULT '',
            age_min INTEGER NOT NULL DEFAULT 18,
            age_max INTEGER NOT NULL DEFAULT 120,
            relationship_type TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            radius_km INTEGER NOT NULL DEFAULT 500,
            status TEXT NOT NULL DEFAULT 'waiting',
            match_id INTEGER REFERENCES matches(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    # Migrate databases created before later columns existed.
    for stmt in (
        "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN gender TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN seeking TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE searches ADD COLUMN location TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE searches ADD COLUMN radius_km INTEGER NOT NULL DEFAULT 500",
        "ALTER TABLE profiles ADD COLUMN height_cm INTEGER",
        "ALTER TABLE profiles ADD COLUMN body_type TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN fitness_level TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN hair_color TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN eye_color TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN tattoos TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN pref_height_min INTEGER",
        "ALTER TABLE profiles ADD COLUMN pref_height_max INTEGER",
        "ALTER TABLE profiles ADD COLUMN pref_body_types TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN pref_fitness_level TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN pref_hair_color TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN pref_eye_color TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profiles ADD COLUMN pref_tattoos TEXT NOT NULL DEFAULT ''",
    ):
        try:
            db.execute(stmt)
        except sqlite3.OperationalError:
            pass

    admin = db.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if admin is None:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
        )
        db.execute(
            "INSERT INTO profiles (user_id, name) VALUES (?, 'Site Admin')",
            (cur.lastrowid,),
        )
    else:
        db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin[0],))

    db.commit()
    db.close()


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
            return redirect(url_for("browse"))
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
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if admin is not None:
        session["user_id"] = admin["id"]


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("browse"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("browse"))

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
                cur = db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.execute(
                    "INSERT INTO profiles (user_id) VALUES (?)", (cur.lastrowid,)
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "That username is already taken."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Welcome! Now set up your profile.")
                return redirect(url_for("edit_profile"))

        flash(error)

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("browse"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("browse"))

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


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}
        error, age = validate_profile(values)

        if error is None:
            db.execute(
                """
                UPDATE profiles SET
                    name = ?, age = ?, gender = ?, seeking = ?, location = ?,
                    bio = ?, interests = ?, hobbies = ?, wants = ?, needs = ?,
                    relationship_type = ?, updated_at = datetime('now')
                WHERE user_id = ?
                """,
                (
                    values["name"], age, values["gender"], values["seeking"],
                    values["location"], values["bio"], values["interests"],
                    values["hobbies"], values["wants"], values["needs"],
                    values["relationship_type"], user_id,
                ),
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

    return render_template(
        "profile_edit.html",
        profile=profile,
        relationship_types=RELATIONSHIP_TYPES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
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
        return redirect(url_for("browse"))

    return render_template(
        "profile_view.html",
        profile=row,
        is_own=(user_id == session["user_id"]),
    )


@app.route("/admin/profiles/new", methods=["GET", "POST"])
@admin_required
def admin_new_profile():
    db = get_db()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}

        error = None
        if not username or len(username) < 3:
            error = "Username must be at least 3 characters."
        elif password and len(password) < 8:
            error = "Password must be at least 8 characters (or leave it empty)."
        else:
            error, age = validate_profile(values)

        if error is None:
            try:
                # Without a password the account can't log in until one
                # is set; with one, the person can sign in right away.
                cur = db.execute(
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
                        (user_id, name, age, gender, seeking, location, bio,
                         interests, hobbies, wants, needs, relationship_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cur.lastrowid, values["name"], age, values["gender"],
                        values["seeking"], values["location"], values["bio"],
                        values["interests"], values["hobbies"], values["wants"],
                        values["needs"], values["relationship_type"],
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "That username is already taken."
            else:
                flash(f"Profile for {values['name']} (@{username}) created.")
                return redirect(url_for("view_profile", user_id=cur.lastrowid))

        flash(error)
        profile = dict(values)
        profile["username"] = username
    else:
        profile = {f: "" for f in PROFILE_FIELDS}
        profile["username"] = ""

    return render_template(
        "admin_profile_new.html",
        profile=profile,
        relationship_types=RELATIONSHIP_TYPES,
        genders=GENDERS,
        seeking_options=SEEKING_OPTIONS,
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


def genders_compatible(me, other):
    """True when both profiles' gender preferences accept each other.

    An unset gender or preference is treated as open, so incomplete
    profiles still get matches.
    """

    def accepts(seeker, candidate):
        if not seeker["seeking"] or not candidate["gender"]:
            return True
        return candidate["gender"] in SEEKING_MATCHES[seeker["seeking"]]

    return accepts(me, other) and accepts(other, me)


def match_score(me, other):
    """Score a candidate: shared keywords, goals, and age proximity."""
    score = 0
    reasons = []

    shared = _tokens(me["interests"], me["hobbies"]) & _tokens(
        other["interests"], other["hobbies"]
    )
    if shared:
        score += 15 * len(shared)
        reasons.append("Shared interests: " + ", ".join(sorted(shared)))

    if me["relationship_type"] and me["relationship_type"] == other["relationship_type"]:
        score += 30
        reasons.append("You both want: " + me["relationship_type"].lower())

    if me["age"] and other["age"]:
        gap = abs(me["age"] - other["age"])
        if gap <= 10:
            score += 10 - gap
            if gap <= 3:
                reasons.append("Close in age")

    if me["location"] and other["location"] and (
        me["location"].strip().lower() == other["location"].strip().lower()
    ):
        score += 25
        reasons.append("Same location: " + other["location"])

    return score, reasons


MATCH_OPTION_COUNT = 3

# Serializes live-search pairing so two simultaneous searchers can't both
# claim the same partner, and wakes anyone waiting for a match.
SEARCH_LOCK = threading.Lock()
SEARCH_EVENT = threading.Condition()
SEARCH_WAIT_TIMEOUT = 25.0


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


def searches_compatible(s1, s2):
    """True when two live searches satisfy each other's criteria.

    Both directions must hold: each person's gender must be one the other
    is looking for, each person's age must fall inside the other's
    requested range, and the distance between them must sit inside both
    radii. Relationship type only blocks when both named one and they
    differ. Unset fields are treated as "no preference".
    """

    def gender_ok(searcher, candidate_gender):
        if not searcher["seeking"] or not candidate_gender:
            return True
        return candidate_gender in SEEKING_MATCHES[searcher["seeking"]]

    def age_ok(searcher, candidate_age):
        if candidate_age is None:
            return True
        return searcher["age_min"] <= candidate_age <= searcher["age_max"]

    if not (gender_ok(s1, s2["gender"]) and gender_ok(s2, s1["gender"])):
        return False
    if not (age_ok(s1, s2["age"]) and age_ok(s2, s1["age"])):
        return False
    if (
        s1["relationship_type"]
        and s2["relationship_type"]
        and s1["relationship_type"] != s2["relationship_type"]
    ):
        return False

    # Distance must fit inside both people's radius. An unknown city or a
    # radius at the maximum means "anywhere".
    gap = distance_km(s1["location"], s2["location"])
    if gap is not None:
        for search in (s1, s2):
            if search["radius_km"] < RADIUS_MAX_KM and gap > search["radius_km"]:
                return False
    return True


def try_pair(user_id):
    """Pair this searcher with a waiting, mutually-compatible one.

    Returns the match id when a pair is formed (or already was), else None.
    """
    db = get_db()
    matched_id = None

    with SEARCH_LOCK:
        mine = db.execute(
            """
            SELECT s.*, p.gender, p.age FROM searches s
            JOIN profiles p ON p.user_id = s.user_id
            WHERE s.user_id = ?
            """,
            (user_id,),
        ).fetchone()

        if mine is None:
            return None
        if mine["status"] == "matched":
            return mine["match_id"]
        if mine["status"] != "waiting":
            return None

        others = db.execute(
            """
            SELECT s.*, p.gender, p.age FROM searches s
            JOIN profiles p ON p.user_id = s.user_id
            WHERE s.status = 'waiting' AND s.user_id != ?
            ORDER BY s.created_at
            """,
            (user_id,),
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
            return None

        partner_id = best[1]["user_id"]
        a, b = sorted((user_id, partner_id))
        existing = db.execute(
            "SELECT id FROM matches WHERE user_a = ? AND user_b = ?", (a, b)
        ).fetchone()
        if existing:
            matched_id = existing["id"]
        else:
            matched_id = db.execute(
                "INSERT INTO matches (user_a, user_b) VALUES (?, ?)", (a, b)
            ).lastrowid

        db.execute(
            "UPDATE searches SET status = 'matched', match_id = ? WHERE user_id IN (?, ?)",
            (matched_id, user_id, partner_id),
        )
        db.commit()

    # Wake the partner's waiting page immediately.
    with SEARCH_EVENT:
        SEARCH_EVENT.notify_all()
    return matched_id


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

        if error:
            flash(error)
        else:
            db.execute(
                """
                INSERT INTO searches
                    (user_id, seeking, age_min, age_max, relationship_type,
                     interests, location, radius_km, status, match_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', NULL, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    seeking = excluded.seeking,
                    age_min = excluded.age_min,
                    age_max = excluded.age_max,
                    relationship_type = excluded.relationship_type,
                    interests = excluded.interests,
                    location = excluded.location,
                    radius_km = excluded.radius_km,
                    status = 'waiting',
                    match_id = NULL,
                    created_at = datetime('now')
                """,
                (
                    user_id, seeking, age_min, age_max, wanted, interests,
                    location, radius_km,
                ),
            )
            db.commit()

            match_id = try_pair(user_id)
            if match_id:
                flash("It's a match! You were paired instantly — say hi.")
                return redirect(url_for("chat", match_id=match_id))
            return redirect(url_for("search_waiting"))

    return render_template(
        "search_criteria.html",
        me=me,
        existing=existing,
        wanted=wanted,
        seeking_options=SEEKING_OPTIONS,
        city_choices=CITY_CHOICES,
        radius_max=RADIUS_MAX_KM,
    )


def search_blockers(user_id):
    """Explain why a waiting search hasn't matched: what each rule rejects.

    Returns counts of pool members that would match if a single filter were
    relaxed, so the waiting page can suggest a concrete fix.
    """
    db = get_db()
    mine = db.execute(
        """
        SELECT s.*, p.gender, p.age FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        WHERE s.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if mine is None:
        return {}

    others = db.execute(
        """
        SELECT s.*, p.gender, p.age FROM searches s
        JOIN profiles p ON p.user_id = s.user_id
        WHERE s.status = 'waiting' AND s.user_id != ?
        """,
        (user_id,),
    ).fetchall()

    def relaxed(**overrides):
        loosened = dict(mine)
        loosened.update(overrides)
        return sum(1 for o in others if searches_compatible(loosened, o))

    return {
        "pool": len(others),
        "if_any_distance": relaxed(radius_km=RADIUS_MAX_KM),
        "if_any_age": relaxed(age_min=18, age_max=120),
        "if_any_connection": relaxed(relationship_type=""),
        "if_any_gender": relaxed(seeking=""),
        # When no single change is enough, say what dropping every filter
        # except gender would give.
        "if_all_relaxed": relaxed(
            radius_km=RADIUS_MAX_KM, age_min=18, age_max=120, relationship_type=""
        ),
    }


@app.route("/search/waiting")
@login_required
def search_waiting():
    row = get_db().execute(
        "SELECT * FROM searches WHERE user_id = ?", (session["user_id"],)
    ).fetchone()

    if row is None or row["status"] == "cancelled":
        return redirect(url_for("live_search"))
    if row["status"] == "matched" and row["match_id"]:
        return redirect(url_for("chat", match_id=row["match_id"]))

    waiting_count = get_db().execute(
        "SELECT COUNT(*) AS n FROM searches WHERE status = 'waiting'"
    ).fetchone()["n"]

    return render_template(
        "search_waiting.html",
        search=row,
        waiting=waiting_count,
        radius_max=RADIUS_MAX_KM,
        blockers=search_blockers(session["user_id"]),
    )


@app.route("/search/status")
@login_required
def search_status():
    """Long-polled by the waiting page; returns as soon as a match exists."""
    user_id = session["user_id"]

    def snapshot():
        # Retry pairing on each pass so a searcher who arrived while we
        # were waiting still gets picked up.
        try_pair(user_id)
        return get_db().execute(
            "SELECT status, match_id FROM searches WHERE user_id = ?", (user_id,)
        ).fetchone()

    row = snapshot()
    if row is None:
        return {"status": "none"}

    if row["status"] == "waiting" and request.args.get("wait") == "1":
        deadline = time.monotonic() + SEARCH_WAIT_TIMEOUT
        while row is not None and row["status"] == "waiting":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            with SEARCH_EVENT:
                SEARCH_EVENT.wait(min(remaining, 1.0))
            row = snapshot()

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


@app.route("/find", methods=["GET", "POST"])
@login_required
def find():
    """Step 1: pick the relationship type you're looking for."""
    me = get_db().execute(
        "SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)
    ).fetchone()

    if me is None or not me["name"]:
        flash("Fill in your profile first so we can find your matches.")
        return redirect(url_for("edit_profile"))

    if request.method == "POST":
        wanted = request.form.get("relationship_type", "")
        if wanted not in RELATIONSHIP_TYPES:
            flash("Please choose what you're looking for.")
        else:
            return redirect(url_for("find_results", relationship_type=wanted))

    return render_template(
        "find.html",
        relationship_types=RELATIONSHIP_TYPES,
        current_choice=me["relationship_type"],
    )


@app.route("/find/results")
@login_required
def find_results():
    """Step 2: three candidates who want the same kind of relationship."""
    db = get_db()
    wanted = request.args.get("relationship_type", "")
    if wanted not in RELATIONSHIP_TYPES:
        return redirect(url_for("find"))

    me = db.execute(
        "SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)
    ).fetchone()
    if me is None or not me["name"]:
        flash("Fill in your profile first so we can find your matches.")
        return redirect(url_for("edit_profile"))

    # Only people after the same kind of relationship, and not already
    # matched with me.
    candidates = db.execute(
        """
        SELECT p.*, u.username FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id != ?
          AND p.name != ''
          AND p.relationship_type = ?
          AND p.user_id NOT IN (
              SELECT CASE WHEN user_a = ? THEN user_b ELSE user_a END
              FROM matches WHERE ? IN (user_a, user_b)
          )
        """,
        (session["user_id"], wanted, session["user_id"], session["user_id"]),
    ).fetchall()

    scored = []
    for cand in candidates:
        if not genders_compatible(me, cand):
            continue
        score, reasons = match_score(me, cand)
        scored.append({"profile": cand, "score": score, "reasons": reasons})

    scored.sort(key=lambda m: m["score"], reverse=True)

    return render_template(
        "find_results.html",
        wanted=wanted,
        options=scored[:MATCH_OPTION_COUNT],
        total=len(scored),
    )


@app.route("/matches")
@login_required
def matches():
    db = get_db()
    me = db.execute(
        "SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)
    ).fetchone()

    if me is None or not me["name"]:
        flash("Fill in your profile first so we can find your matches.")
        return redirect(url_for("edit_profile"))

    candidates = db.execute(
        """
        SELECT p.*, u.username FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id != ? AND p.name != ''
        """,
        (session["user_id"],),
    ).fetchall()

    scored = []
    for cand in candidates:
        if not genders_compatible(me, cand):
            continue
        score, reasons = match_score(me, cand)
        scored.append({"profile": cand, "score": score, "reasons": reasons})

    scored.sort(key=lambda m: m["score"], reverse=True)

    return render_template(
        "matches.html",
        top=scored[0] if scored else None,
        others=scored[1:],
    )


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
            SELECT p.*, u.username FROM profiles p
            JOIN users u ON u.id = p.user_id
            WHERE p.user_id = ?
            """,
            (uid,),
        ).fetchone()
        for uid in (match["user_a"], match["user_b"])
    ]
    return match, profiles


@app.route("/match/<int:other_id>", methods=["POST"])
@login_required
def create_match(other_id):
    db = get_db()
    me_id = session["user_id"]

    if other_id == me_id:
        flash("You can't match with yourself.")
        return redirect(url_for("matches"))

    other = db.execute(
        "SELECT user_id, name FROM profiles WHERE user_id = ?", (other_id,)
    ).fetchone()
    if other is None:
        flash("That profile does not exist.")
        return redirect(url_for("matches"))

    a, b = sorted((me_id, other_id))
    existing = db.execute(
        "SELECT id FROM matches WHERE user_a = ? AND user_b = ?", (a, b)
    ).fetchone()
    if existing:
        return redirect(url_for("chat", match_id=existing["id"]))

    cur = db.execute(
        "INSERT INTO matches (user_a, user_b) VALUES (?, ?)", (a, b)
    )
    db.commit()
    flash(f"It's a match! You and {other['name']} can chat now.")
    return redirect(url_for("chat", match_id=cur.lastrowid))


@app.route("/chats")
@login_required
def chats():
    user = current_user()
    query = """
        SELECT m.id, m.created_at,
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
    return render_template("chats.html", rooms=rows)


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

    messages = get_db().execute(
        """
        SELECT msg.*, p.name AS sender_name FROM messages msg
        JOIN profiles p ON p.user_id = msg.sender_id
        WHERE msg.match_id = ?
        ORDER BY msg.id
        """,
        (match_id,),
    ).fetchall()

    return render_template(
        "chat.html",
        match=match,
        profiles=profiles,
        messages=messages,
        me_id=session["user_id"],
        is_participant=is_participant,
    )


# Wakes long-polling /messages requests the moment a message is sent.
NEW_MESSAGE = threading.Condition()


def message_dict(row):
    return {
        "id": row["id"],
        "sender_id": row["sender_id"],
        "sender_name": row["sender_name"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


LONG_POLL_TIMEOUT = 25.0


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


@app.route("/chat/<int:match_id>/messages")
@login_required
def chat_messages(match_id):
    """JSON feed of messages newer than ?after=<id>.

    With ?wait=1 the request is held open (long polling) until a message
    arrives or LONG_POLL_TIMEOUT passes, so the browser sees new messages
    the instant they are sent instead of on the next poll tick.
    """
    match, _ = get_match_participants(match_id)
    user = current_user()
    if match is None:
        return {"error": "not found"}, 404
    if user["id"] not in (match["user_a"], match["user_b"]) and not user["is_admin"]:
        return {"error": "forbidden"}, 403

    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0

    rows = fetch_messages_after(match_id, after)

    if not rows and request.args.get("wait") == "1":
        deadline = time.monotonic() + LONG_POLL_TIMEOUT
        while not rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            with NEW_MESSAGE:
                NEW_MESSAGE.wait(min(remaining, 1.0))
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
    if not body:
        return fail("Message can't be empty.", 400)

    db = get_db()
    cur = db.execute(
        "INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
        (match_id, sender_id, body),
    )
    db.commit()

    # Release anyone long-polling this room.
    with NEW_MESSAGE:
        NEW_MESSAGE.notify_all()

    if wants_json:
        row = db.execute(
            """
            SELECT msg.*, p.name AS sender_name FROM messages msg
            JOIN profiles p ON p.user_id = msg.sender_id
            WHERE msg.id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return {"message": message_dict(row)}

    return redirect(url_for("chat", match_id=match_id))


@app.route("/browse")
@login_required
def browse():
    profiles = get_db().execute(
        """
        SELECT p.*, u.username FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id != ? AND p.name != ''
        ORDER BY p.updated_at DESC
        """,
        (session["user_id"],),
    ).fetchall()

    me = get_db().execute(
        "SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)
    ).fetchone()

    return render_template(
        "browse.html",
        profiles=profiles,
        profile_incomplete=(me is not None and me["name"] == ""),
    )


init_db()

if __name__ == "__main__":
    # threaded=True so long-polling chat requests don't block the server.
    # host/port/debug are overridable for deployment (Render sets PORT;
    # FLASK_DEBUG=0 turns off the reloader/debugger in production). In
    # production, run behind gunicorn instead ("gunicorn app:app"), which
    # skips this block entirely.
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") not in ("0", "false", "no")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
