"""Dating website — Flask app with login, registration, and profiles.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser. Register an account,
fill in your profile, and browse other members.

Data is stored in a local SQLite file (dating.db). Set APP_SECRET_KEY to
keep sessions valid across restarts.
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
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dating.db")

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


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


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


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in PROFILE_FIELDS}

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
