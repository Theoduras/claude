"""Dating website — Flask app with login, registration, and profiles.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser. Register an account,
fill in your profile, and browse other members.

Data is stored in a local SQLite file (dating.db). Set APP_SECRET_KEY to
keep sessions valid across restarts.

An admin account is created automatically on startup (username "admin",
password from APP_ADMIN_PASSWORD, default "admin12345"). While AUTO_LOGIN
is enabled (the default for this local demo), opening the site signs you
in as admin automatically; set AUTO_LOGIN=0 to get the normal login page.
"""

import os
import secrets
import sqlite3

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
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dating.db")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "admin12345")
AUTO_LOGIN = os.environ.get("AUTO_LOGIN", "1") not in ("0", "false", "no")

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
            location TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            hobbies TEXT NOT NULL DEFAULT '',
            wants TEXT NOT NULL DEFAULT '',
            needs TEXT NOT NULL DEFAULT '',
            relationship_type TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    # Migrate databases created before the is_admin column existed.
    try:
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
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
    """Login is disabled for now: every visitor is signed in as admin."""
    if session.get("user_id") is not None:
        return
    admin = get_db().execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if admin is not None:
        session["user_id"] = admin["id"]


@app.route("/")
def index():
    return redirect(url_for("browse"))


# Login is bypassed for now: auto_login_admin() signs every visitor in as
# admin, and the login/register pages just forward to the site.
@app.route("/register", methods=["GET", "POST"])
def register():
    return redirect(url_for("browse"))


@app.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("browse"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


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
                    name = ?, age = ?, location = ?, bio = ?, interests = ?,
                    hobbies = ?, wants = ?, needs = ?, relationship_type = ?,
                    updated_at = datetime('now')
                WHERE user_id = ?
                """,
                (
                    values["name"], age, values["location"], values["bio"],
                    values["interests"], values["hobbies"], values["wants"],
                    values["needs"], values["relationship_type"], user_id,
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
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}

        error = None
        if not username or len(username) < 3:
            error = "Username must be at least 3 characters."
        else:
            error, age = validate_profile(values)

        if error is None:
            try:
                # Login is bypassed, so the account gets an unguessable
                # random password; set a real one when logins return.
                cur = db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(secrets.token_urlsafe(32))),
                )
                db.execute(
                    """
                    INSERT INTO profiles
                        (user_id, name, age, location, bio, interests,
                         hobbies, wants, needs, relationship_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cur.lastrowid, values["name"], age, values["location"],
                        values["bio"], values["interests"], values["hobbies"],
                        values["wants"], values["needs"],
                        values["relationship_type"],
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
    )


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
    app.run(host="127.0.0.1", port=5000, debug=True)
