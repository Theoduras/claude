"""Functional checks for the account, session, CSRF and age-gate behaviour.

    python check_auth.py

Uses Flask's test client, like smoke.py, so there is no server to start.
smoke.py proves routes render; this proves the security-relevant ones
actually behave. Needs a reachable database, same as the app.
"""

import re
import sys
import uuid

import app as A
from app import app

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def token(client, path="/login"):
    """Read a CSRF token out of a rendered page, the way a browser would."""
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def register(client, **over):
    name = over.pop("username", f"chk_{uuid.uuid4().hex[:10]}")
    data = {
        "username": name,
        "email": over.pop("email", f"{name}@example.test"),
        "dob": over.pop("dob", "1995-06-15"),
        "password": over.pop("password", "correct horse battery"),
        "confirm": over.pop("confirm", "correct horse battery"),
        "csrf_token": token(client, "/register"),
    }
    data.update(over)
    return name, client.post("/register", data=data, follow_redirects=False)


def uid_of(username):
    with app.test_request_context():
        row = A.get_db().execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ).fetchone()
        return None if row is None else row["id"]


def sessions_for(user_id):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]


# --- 1. registration and the age gate -----------------------------------
with app.test_client() as c:
    name, resp = register(c)
    check("register creates an account", uid_of(name) is not None)
    check("register signs you in", resp.status_code == 302, f"HTTP {resp.status_code}")

with app.test_client() as c:
    name, resp = register(c, dob="2015-01-01")
    check("under-18 is refused", resp.status_code == 403, f"HTTP {resp.status_code}")
    check("under-18 account is not created", uid_of(name) is None)
    # A second, adult date in the same session must not get through.
    name2, resp2 = register(c, dob="1990-01-01")
    check(
        "under-18 cannot retry with a different date",
        resp2.status_code == 403 and uid_of(name2) is None,
        f"HTTP {resp2.status_code}",
    )

with app.test_client() as c:
    name, resp = register(c, email="not-an-address")
    check("invalid email is refused", uid_of(name) is None)

# --- 2. CSRF ------------------------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    # A forged POST carrying the real session cookie but no token.
    resp = c.post("/logout")
    check("POST without a CSRF token is rejected", resp.status_code == 400,
          f"HTTP {resp.status_code}")
    resp = c.post("/logout", data={"csrf_token": "forged"})
    check("POST with a forged CSRF token is rejected", resp.status_code == 400,
          f"HTTP {resp.status_code}")
    resp = c.post("/logout", data={"csrf_token": token(c, "/profile/edit")})
    check("POST with a valid CSRF token succeeds", resp.status_code == 302,
          f"HTTP {resp.status_code}")

with app.test_client() as c:
    name, _ = register(c)
    # The header path, used by the three fetch call sites.
    resp = c.post("/logout", headers={"X-CSRF-Token": token(c, "/profile/edit")})
    check("X-CSRF-Token header is accepted", resp.status_code == 302,
          f"HTTP {resp.status_code}")

# --- 3. sessions --------------------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    check("a session row exists after registering", sessions_for(uid) == 1,
          f"{sessions_for(uid)} rows")

    with c.session_transaction() as s:
        check("cookie carries an opaque token, not a user id",
              "sid" in s and "user_id" not in s, str(sorted(s.keys())))

    c.post("/logout", data={"csrf_token": token(c, "/profile/edit")})
    check("logout deletes the session row", sessions_for(uid) == 0,
          f"{sessions_for(uid)} rows")

# Sign in on two "devices", then reset the password and confirm both die.
with app.test_client() as c1:
    name, _ = register(c1)
    uid = uid_of(name)
    with app.test_client() as c2:
        c2.post("/login", data={"username": name, "password": "correct horse battery",
                                "csrf_token": token(c2)}, follow_redirects=False)
        check("second device gets its own session", sessions_for(uid) == 2,
              f"{sessions_for(uid)} rows")

        with app.test_request_context():
            tok = A.issue_email_token(uid, "reset", 1)
        with app.test_client() as c3:
            resp = c3.post(
                f"/reset/{tok}",
                data={"password": "a whole new password", "confirm": "a whole new password",
                      "csrf_token": token(c3, f"/reset/{tok}")},
                follow_redirects=False,
            )
            check("reset succeeds", resp.status_code == 302, f"HTTP {resp.status_code}")
        # Only the session minted by the reset itself survives.
        check("reset revokes every other session", sessions_for(uid) == 1,
              f"{sessions_for(uid)} rows")
        resp = c2.get("/profile/edit", follow_redirects=False)
        check("the other device is signed out", resp.status_code == 302,
              f"HTTP {resp.status_code}")

# A reset token is single use.
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    with app.test_request_context():
        tok = A.issue_email_token(uid, "reset", 1)
    with app.test_client() as c2:
        c2.post(f"/reset/{tok}", data={"password": "first new password",
                                       "confirm": "first new password",
                                       "csrf_token": token(c2, f"/reset/{tok}")})
    with app.test_client() as c3:
        resp = c3.get(f"/reset/{tok}", follow_redirects=False)
        check("a spent reset token is refused", resp.status_code == 302,
              f"HTTP {resp.status_code}")

# --- 4. /forgot does not leak which addresses exist ----------------------
with app.test_client() as c:
    name, _ = register(c)
    c.post("/logout", data={"csrf_token": token(c, "/profile/edit")})
    real = c.post("/forgot", data={"email": f"{name}@example.test",
                                   "csrf_token": token(c, "/forgot")},
                  follow_redirects=True)
    fake = c.post("/forgot", data={"email": "nobody-here@example.test",
                                   "csrf_token": token(c, "/forgot")},
                  follow_redirects=True)
    check("/forgot answers identically for unknown addresses",
          real.get_data() == fake.get_data())

# --- 5. suspension takes effect mid-session -----------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    check("active user can reach the app",
          c.get("/profile/edit", follow_redirects=False).status_code == 200)
    with app.test_request_context():
        db = A.get_db()
        db.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (uid,))
        db.commit()
    resp = c.get("/profile/edit", follow_redirects=False)
    check("suspended user is ejected mid-session", resp.status_code == 302,
          f"HTTP {resp.status_code}")
    check("suspended user's session is dropped", sessions_for(uid) == 0,
          f"{sessions_for(uid)} rows")

    with app.test_request_context():
        db = A.get_db()
        db.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (uid,))
        db.commit()
    with app.test_client() as c2:
        c2.post("/login", data={"username": name, "password": "correct horse battery",
                                "csrf_token": token(c2)}, follow_redirects=False)
        check("suspended user cannot sign back in", sessions_for(uid) == 0,
              f"{sessions_for(uid)} rows")

# --- 6. email verification ----------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    with app.test_request_context():
        verified = A.get_db().execute(
            "SELECT email_verified_at FROM users WHERE id = ?", (uid,)
        ).fetchone()["email_verified_at"]
    check("a new account starts unverified", verified is None)

    with app.test_request_context():
        tok = A.issue_email_token(uid, "verify", 48)
    c.get(f"/verify/{tok}", follow_redirects=False)
    with app.test_request_context():
        verified = A.get_db().execute(
            "SELECT email_verified_at FROM users WHERE id = ?", (uid,)
        ).fetchone()["email_verified_at"]
    check("the verify link confirms the address", verified is not None)

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
if failed:
    print("failed: " + ", ".join(failed))
sys.exit(1 if failed else 0)
