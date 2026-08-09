"""Dating website — Flask app with login, registration, and profiles.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser. Register an account,
fill in your profile, and browse other members.

Data is stored in a local SQLite file (dating.db). Set APP_SECRET_KEY to
keep sessions valid across restarts.

An admin account is created automatically on startup (username "admin",
password from APP_ADMIN_PASSWORD, default "admin12345"). Anyone can
register an account and log in. Set AUTO_LOGIN=1 to skip the login page
during local development and browse as admin automatically.
"""

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

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dating.db")

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

RELATIONSHIP_TYPES = [
    "Long-term relationship",
    "Short-term relationship",
    "Friendship",
    "Casual dating",
    "Marriage",
    "Not sure yet",
]

PROFILE_FIELDS = [
    "name",
    "age",
    "gender",
    "seeking",
    "location",
    "bio",
    "interests",
    "hobbies",
    "wants",
    "needs",
    "relationship_type",
]


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
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
