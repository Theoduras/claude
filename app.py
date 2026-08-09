"""Minimal localhost web app with a basic login screen.

Run it:

    pip install -r requirements.txt
    python app.py

Then open http://localhost:5000 in your browser.

Demo credentials default to admin / password. Override them (and the
session secret) with environment variables:

    export APP_USERNAME="alice"
    export APP_PASSWORD="s3cret"
    export APP_SECRET_KEY="a-long-random-string"
"""

import os
import secrets

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

USERNAME = os.environ.get("APP_USERNAME", "admin")
PASSWORD_HASH = generate_password_hash(os.environ.get("APP_PASSWORD", "password"))


@app.route("/")
def index():
    if session.get("user"):
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == USERNAME and check_password_hash(PASSWORD_HASH, password):
            session["user"] = username
            return redirect(url_for("home"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/home")
def home():
    if not session.get("user"):
        return redirect(url_for("login"))
    return render_template("home.html", user=session["user"])


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
