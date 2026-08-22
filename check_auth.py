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


def clear_rate_limits():
    """Start from a clean budget: these checks make far more attempts from
    one address than a person ever would."""
    with app.test_request_context():
        db = A.get_db()
        db.execute("TRUNCATE rate_hits")
        db.commit()


clear_rate_limits()


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
        "accept_terms": "1",
        "accept_sensitive": "1",
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
    # Earlier checks have already spent some of this address's hourly /forgot
    # budget. Without a reset the two posts below can straddle the limit, and
    # then they differ for that reason rather than the one under test.
    clear_rate_limits()
    real = c.post("/forgot", data={"email": f"{name}@example.test",
                                   "csrf_token": token(c, "/forgot")},
                  follow_redirects=True)
    fake = c.post("/forgot", data={"email": "nobody-here@example.test",
                                   "csrf_token": token(c, "/forgot")},
                  follow_redirects=True)
    # Byte-equality stopped being the right comparison once every response
    # started carrying a per-request CSP nonce and CSRF token. Those differ
    # between any two renders and say nothing about the address; normalise
    # them out and the question is again "does this page reveal whether the
    # account exists".
    def anonymise(resp):
        html = resp.get_data(as_text=True)
        html = re.sub(r'nonce="[^"]+"', 'nonce="N"', html)
        html = re.sub(r'name="csrf_token" value="[^"]+"',
                      'name="csrf_token" value="T"', html)
        return html

    check("/forgot answers identically for unknown addresses",
          anonymise(real) == anonymise(fake))

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

# --- 7. blocking --------------------------------------------------------
def make_searcher(name_hint):
    """A user with a profile and a ripe, wide-open waiting search."""
    with app.test_request_context():
        db = A.get_db()
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash, status) VALUES (?, ?, 'active')",
            (f"{name_hint}_{uuid.uuid4().hex[:8]}", "x"),
        )
        db.execute(
            """INSERT INTO profiles (user_id, name, age, gender, seeking, location)
               VALUES (?, ?, 30, 'Woman', 'Everyone', 'Berlin')""",
            (uid, name_hint),
        )
        db.execute(
            """INSERT INTO searches
                 (user_id, seeking, age_min, age_max, location, lat, lng, radius_km,
                  status, use_gender, use_age, use_distance, use_physical, created_at)
               VALUES (?, 'Everyone', 18, 39, 'Berlin', 52.52, 13.405, 500,
                       'waiting', FALSE, FALSE, FALSE, FALSE,
                       NOW() - INTERVAL '60 seconds')""",
            (uid,),
        )
        db.commit()
    return uid


def reopen_search(uid):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """UPDATE searches SET status='waiting', match_id=NULL,
               created_at = NOW() - INTERVAL '60 seconds' WHERE user_id=?""", (uid,)
        )
        db.commit()


def empty_the_pool():
    """Leave only the searchers this section creates.

    The demo bots and every earlier check's leftovers are still waiting, and
    with ALLOW_BOT_MATCHES on locally they are all pairable — so "did a match
    form" says nothing. Clearing the pool makes the partner's identity the
    assertion, which is what actually matters here.
    """
    with app.test_request_context():
        db = A.get_db()
        db.execute("UPDATE searches SET status='cancelled' WHERE status='waiting'")
        db.commit()


def partner_of(user_id, match_id):
    if match_id is None:
        return None
    with app.test_request_context():
        row = A.get_db().execute(
            """SELECT CASE WHEN user_a=? THEN user_b ELSE user_a END AS other
               FROM matches WHERE id=?""",
            (user_id, match_id),
        ).fetchone()
    return None if row is None else row["other"]


empty_the_pool()
ann, ben = make_searcher("ann"), make_searcher("ben")
with app.test_request_context():
    paired = A.try_pair(ann)
check("two real searchers pair with each other", partner_of(ann, paired) == ben)

# Block, then confirm they can never be paired again.
with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE matches SET status='ended' WHERE user_a=? OR user_b=?", (ann, ann))
    db.commit()
    A.apply_block(ann, ben)
empty_the_pool()
reopen_search(ann)
reopen_search(ben)
with app.test_request_context():
    again = A.try_pair(ann)
check("a blocked pair is never matched again", again is None,
      f"paired with {partner_of(ann, again)}")
with app.test_request_context():
    check("blocking is symmetric", A.is_blocked_between(ben, ann))
    check("a block hides photos both ways",
          not A.can_view_photos(ann, ben, False) and not A.can_view_photos(ben, ann, False))
    check("an admin can still see reported content",
          A.can_view_photos(ann, ben, True))

# A third party is unaffected: ann still pairs, just never with ben.
cal = make_searcher("cal")
reopen_search(ann)
with app.test_request_context():
    third = A.try_pair(ann)
check("a block doesn't affect anyone else", partner_of(ann, third) == cal,
      f"paired with {partner_of(ann, third)}")

# --- 8. reporting -------------------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    target = make_searcher("subject")
    resp = c.post(
        f"/report/{target}",
        data={"reason": "harassment", "detail": "test report", "block": "1",
              "csrf_token": token(c, f"/report/{target}")},
        follow_redirects=False,
    )
    check("a report is accepted", resp.status_code == 302, f"HTTP {resp.status_code}")
    with app.test_request_context():
        row = A.get_db().execute(
            "SELECT * FROM reports WHERE reporter_id = ?", (uid,)
        ).fetchone()
    check("the report is stored", row is not None and row["reason"] == "harassment")
    with app.test_request_context():
        check("report + block applies the block", A.is_blocked_between(uid, target))

    resp = c.post(f"/report/{target}",
                  data={"reason": "not-a-real-reason",
                        "csrf_token": token(c, f"/report/{target}")})
    check("an invented reason is refused", resp.status_code == 200,
          f"HTTP {resp.status_code}")

# --- 9. account deletion ------------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    resp = c.post("/settings/delete", data={"password": "wrong password",
                                            "csrf_token": token(c, "/settings")},
                  follow_redirects=False)
    with app.test_request_context():
        st = A.get_db().execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone()
    check("deletion needs the right password", st["status"] == "active")

    c.post("/settings/delete", data={"password": "correct horse battery",
                                     "csrf_token": token(c, "/settings")})
    with app.test_request_context():
        st = A.get_db().execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone()
    check("deletion is scheduled, not immediate", st["status"] == "pending_deletion")
    check("a pending-deletion user can still sign in to cancel",
          c.get("/settings", follow_redirects=False).status_code == 200)

    c.post("/settings/delete/cancel", data={"csrf_token": token(c, "/settings")})
    with app.test_request_context():
        st = A.get_db().execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone()
    check("deletion can be cancelled", st["status"] == "active")

# The purge, and what it does to the other person's conversation.
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    partner = make_searcher("partner")
    with app.test_request_context():
        db = A.get_db()
        a, b = sorted((uid, partner))
        mid = db.insert_returning_id(
            "INSERT INTO matches (user_a, user_b, status) VALUES (?, ?, 'active')", (a, b)
        )
        db.execute("INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
                   (mid, uid, "a message from the leaving user"))
        db.execute("INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, ?)",
                   (mid, partner, "a reply from the one who stays"))
        db.execute("""UPDATE users SET status='pending_deletion',
                      deletion_requested_at = NOW() - INTERVAL '30 days' WHERE id=?""", (uid,))
        db.commit()
        purged = A.purge_due_deletions()
    check("an expired grace period purges the account", purged >= 1, f"{purged} purged")
    with app.test_request_context():
        db = A.get_db()
        gone = db.execute("SELECT username, email, dob, status FROM users WHERE id=?",
                          (uid,)).fetchone()
        prof = db.execute("SELECT 1 AS h FROM profiles WHERE user_id=?", (uid,)).fetchone()
        kept = db.execute("SELECT COUNT(*) AS n FROM messages WHERE match_id=?",
                          (mid,)).fetchone()["n"]
        orphan = db.execute(
            "SELECT sender_id FROM messages WHERE match_id=? AND sender_id IS NULL",
            (mid,)).fetchone()
    check("the account is anonymised", gone is not None and gone["username"].startswith("deleted_")
          and gone["email"] is None and gone["status"] == "deleted")
    check("the other person's conversation survives intact", kept == 2, f"{kept} messages")
    check("the deleted sender is detached, not deleted", orphan is not None)
    check("the profile and its contents are gone", prof is None)
    check("no personal data survives", gone["email"] is None and gone["dob"] is None)

# --- 10. consent --------------------------------------------------------
with app.test_client() as c:
    name, _ = register(c)
    uid = uid_of(name)
    with app.test_request_context():
        row = A.get_db().execute(
            "SELECT * FROM consents WHERE user_id=? AND purpose=?",
            (uid, A.CONSENT_SENSITIVE)).fetchone()
    check("Article 9 consent is recorded at registration", row is not None)
    with app.test_request_context():
        terms = A.get_db().execute(
            "SELECT COUNT(*) AS n FROM legal_acceptances WHERE user_id=?", (uid,)
        ).fetchone()["n"]
    check("terms and privacy acceptance is versioned", terms == 2, f"{terms} rows")

    c.post("/settings/consent", data={"csrf_token": token(c, "/settings")})
    with app.test_request_context():
        row = A.get_db().execute(
            "SELECT withdrawn_at FROM consents WHERE user_id=? AND purpose=?",
            (uid, A.CONSENT_SENSITIVE)).fetchone()
    check("consent can be withdrawn", row["withdrawn_at"] is not None)

with app.test_client() as c:
    name, resp = register(c, accept_sensitive="")
    check("registration without Article 9 consent is refused", uid_of(name) is None)

with app.test_client() as c:
    name, resp = register(c, accept_terms="")
    check("registration without accepting terms is refused", uid_of(name) is None)

# --- 11. rate limiting --------------------------------------------------
clear_rate_limits()
with app.test_client() as c:
    codes = []
    for _ in range(8):
        r = c.post("/forgot", data={"email": "someone@example.test",
                                    "csrf_token": token(c, "/forgot")})
        codes.append(r.status_code)
    check("a flood of reset requests is throttled", 429 in codes,
          f"saw {sorted(set(codes))}")

# --- 12. widening a stuck search ----------------------------------------
def aged_searcher(label, age, age_min, age_max, height=None, **over):
    """A searcher with a specific age and age filter, everything else open.

    `height` matters for the physical checks: physical_ok() only blocks a
    candidate who actually has the trait, so a profile with no height is
    never excluded by a height filter.
    """
    with app.test_request_context():
        db = A.get_db()
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (f"wid_{label}_{uuid.uuid4().hex[:6]}", "x"))
        db.execute(
            """INSERT INTO profiles (user_id, name, age, gender, seeking, location, height_cm)
               VALUES (?, ?, ?, 'Woman', 'Everyone', 'Berlin', ?)""",
            (uid, label, age, height))
        cols = dict(seeking="Everyone", age_min=age_min, age_max=age_max,
                    use_gender=False, use_age=True, use_distance=False,
                    use_physical=False)
        cols.update(over)
        db.execute(
            f"""INSERT INTO searches
                  (user_id, location, lat, lng, radius_km, status, created_at,
                   {','.join(cols)})
                VALUES (?, 'Berlin', 52.52, 13.405, 500, 'waiting',
                        NOW() - INTERVAL '60 seconds', {','.join(['?'] * len(cols))})""",
            (uid, *cols.values()))
        db.commit()
    return uid


def login_as(client, uid):
    """Attach a real session row to a client, for users made without the form."""
    with app.test_request_context():
        tok = A.secrets.token_urlsafe(32)
        db = A.get_db()
        db.execute("""INSERT INTO sessions (user_id, token_hash, expires_at)
                      VALUES (?, ?, NOW() + INTERVAL '1 day')""", (uid, A.hash_token(tok)))
        db.commit()
    with client.session_transaction() as s:
        s["sid"] = tok


def chip_state_for(uid):
    """The waiting screen's own view: chips, their priced options, and the
    "Search wider" offer -- read through chip_state(), so a check here fails
    if the screen would show something different."""
    with app.test_request_context():
        mine, others = A._search_pool(uid)
        return A.chip_state(mine, others)


def options_for(state, key):
    for chip in state["chips"]:
        if chip["key"] == key:
            return chip["options"]
    return []


def search_row(uid):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT * FROM searches WHERE user_id = ?", (uid,)).fetchone()


empty_the_pool()
me = aged_searcher("me", 28, 25, 30)      # wants 25-30
them = aged_searcher("them", 41, 18, 60)  # is 41, wants anyone

st = chip_state_for(me)
check("a stuck search is offered a way out",
      st["fits"] == 0 and st["relax_all"]["offer"],
      f"fits={st['fits']}, relax_all={st['relax_all']}")
check("the way out is priced with a real count",
      st["relax_all"]["count"] >= 1, str(st["relax_all"]))

age_opts = options_for(st, "age")
check("the blocking filter offers an alternative that reaches someone",
      any(o["count"] >= 1 for o in age_opts),
      str([(o["label"], o["count"]) for o in age_opts]))
check("the current value is marked as current",
      sum(1 for o in age_opts if o["current"]) == 1,
      str([o["label"] for o in age_opts if o["current"]]))

# Nothing is pushed while somebody already fits. Compatibility is mutual,
# so this needs its own pair -- `them` fits nobody either, since `me`
# rejects a 41-year-old just as surely.
empty_the_pool()
easy_a = aged_searcher("easya", 30, 18, 39)
easy_b = aged_searcher("easyb", 31, 18, 39)
st_easy = chip_state_for(easy_a)
check("no widening offered while someone already fits",
      st_easy["fits"] >= 1 and not st_easy["relax_all"]["offer"],
      f"fits={st_easy['fits']}, relax_all={st_easy['relax_all']}")

empty_the_pool()
me = aged_searcher("me", 28, 25, 30)
them = aged_searcher("them", 41, 18, 60)
age_opts = options_for(chip_state_for(me), "age")

with app.test_client() as c:
    login_as(c, me)
    before = search_row(me)

    check("applying a chip needs a CSRF token",
          c.post("/search/chips", data={"key": "age", "value": "25-41"}).status_code == 400)

    reach = [o for o in age_opts if o["count"] >= 1][0]
    r = c.post("/search/chips",
               data={"key": "age", "value": reach["value"],
                     "csrf_token": token(c, "/search/waiting")})
    after = search_row(me)
    check("applying a chip succeeds", r.status_code == 200, f"HTTP {r.status_code}")
    check("the accumulated wait is preserved",
          before["created_at"] == after["created_at"])
    check("applying a chip pairs immediately when it can",
          after["status"] == "matched", after["status"])

# A key the server does not recognise changes nothing and cannot reach SQL.
empty_the_pool()
solo = aged_searcher("solo", 30, 18, 39)
with app.test_client() as c:
    login_as(c, solo)
    was = search_row(solo)
    r = c.post("/search/chips",
               data={"key": "use_physical; DROP TABLE users", "value": "1",
                     "csrf_token": token(c, "/search/waiting")})
    now = search_row(solo)
    check("an invented chip key is refused",
          now["use_physical"] == was["use_physical"] and now["age_min"] == was["age_min"],
          f"HTTP {r.status_code}")
    with app.test_request_context():
        still = A.get_db().execute("SELECT 1 AS h FROM users LIMIT 1").fetchone()
    check("the database is intact", still is not None)

# Physical traits blocking: the body-type pills are the only way out, and
# "Search wider" drops them along with everything else optional.
empty_the_pool()
picky = aged_searcher("picky", 30, 18, 39, height=170, use_physical=True,
                      pref_height_min=200, pref_height_max=220)
short = aged_searcher("short", 30, 18, 39, height=165)
st2 = chip_state_for(picky)
check("a physical filter that blocks everyone is a stuck search",
      st2["fits"] == 0 and st2["relax_all"]["offer"],
      f"fits={st2['fits']}, relax_all={st2['relax_all']}")

with app.test_client() as c:
    login_as(c, picky)
    c.post("/search/chips", data={"key": "all", "value": "",
                                  "csrf_token": token(c, "/search/waiting")})
    check("Search wider switches the physical filter off",
          search_row(picky)["use_physical"] is False)

# GET /search/chips answers the waiting page's refresh with the same shape.
empty_the_pool()
a1 = aged_searcher("poll", 28, 25, 30)
a2 = aged_searcher("pollb", 41, 18, 60)
with app.test_client() as c:
    login_as(c, a1)
    data = c.get("/search/chips", headers={"Accept": "application/json"}).get_json()
    check("GET /search/chips reports the live state",
          data["fits"] == 0 and data["relax_all"]["offer"]
          and any(ch["key"] == "age" for ch in data["chips"]),
          str(data)[:200])


# --- security headers ------------------------------------------------------
# Every page, not just the ones that felt risky. A header set on one route
# and forgotten on the next is the shape this bug always takes.
with app.test_client() as c:
    r = c.get("/login")
    h = r.headers
    csp = h.get("Content-Security-Policy", "")
    check("a CSP is sent", "default-src 'self'" in csp, csp[:80])
    check("script-src is nonce-based, not unsafe-inline",
          "'nonce-" in csp and "'unsafe-inline'" not in csp.split("style-src")[0],
          csp[:120])
    # Header and markup must come from the SAME response -- the nonce is
    # regenerated per request, so comparing across two GETs always fails.
    nonce = csp.split("'nonce-")[1].split("'")[0]
    body = r.get_data(as_text=True)
    check("the page's own scripts carry that nonce",
          body.count("<script") == body.count('nonce="%s"' % nonce),
          f'{body.count("<script")} script tags, '
          f'{body.count(chr(34).join(["nonce=", nonce, ""]))} nonced')
    # 'self', not 'none', since /admin/design previews real pages in a frame.
    # The property worth holding is unchanged -- a cross-origin frame is
    # refused -- so this asserts that rather than the exact keyword, and
    # asserts the legacy header agrees with it.
    check("cross-origin framing is refused",
          "frame-ancestors 'self'" in csp and "frame-ancestors 'none'" not in csp)
    check("...and the legacy header says the same",
          h.get("X-Frame-Options") == "SAMEORIGIN", h.get("X-Frame-Options"))
    check("the referrer is trimmed cross-origin",
          h.get("Referrer-Policy") == "strict-origin-when-cross-origin")
    check("sniffing is off", h.get("X-Content-Type-Options") == "nosniff")
    check("camera and mic are denied", "camera=()" in h.get("Permissions-Policy", ""))
    check("HSTS is not sent over plain http", "Strict-Transport-Security" not in h)

    # A nonce that repeated across responses would be no better than none.
    n1 = c.get("/login").headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
    n2 = c.get("/login").headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
    check("the nonce is per-response", n1 != n2, f"{n1} vs {n2}")

# --- message length --------------------------------------------------------
# maxlength on the composer is advice to the browser. This is the rule.
empty_the_pool()
with app.test_request_context():
    db = A.get_db()
    ids = []
    for nm in ("cap_a", "cap_b"):
        uid = db.execute(
            "INSERT INTO users (username, password_hash, email_verified_at, status)"
            " VALUES (?, 'x', NOW(), 'active') RETURNING id",
            (nm + A.secrets.token_hex(4),)).fetchone()["id"]
        db.execute("INSERT INTO profiles (user_id, name, age, gender, seeking)"
                   " VALUES (?, ?, 30, 'Man', 'Everyone')", (uid, nm))
        ids.append(uid)
    mid = db.execute(
        """INSERT INTO matches (user_a, user_b, status, paired_at)
           VALUES (?, ?, 'active', NOW()) RETURNING id""", tuple(ids)).fetchone()["id"]
    db.commit()

with app.test_client() as c:
    login_as(c, ids[0])
    tok = token(c, f"/chat/{mid}")
    r = c.post(f"/chat/{mid}/send",
               data={"body": "x" * (A.MESSAGE_MAX_CHARS + 1), "csrf_token": tok},
               headers={"Accept": "application/json"})
    check("an over-long message is refused", r.status_code == 400, f"HTTP {r.status_code}")
    r = c.post(f"/chat/{mid}/send",
               data={"body": "x" * A.MESSAGE_MAX_CHARS, "csrf_token": tok},
               headers={"Accept": "application/json"})
    check("a message at the limit is accepted", r.status_code < 400, f"HTTP {r.status_code}")
    with app.test_request_context():
        n = A.get_db().execute(
            "SELECT COUNT(*) AS n FROM messages WHERE match_id = ?", (mid,)).fetchone()["n"]
    check("only the accepted one was stored", n == 1, f"{n} rows")
    html = c.get(f"/chat/{mid}").get_data(as_text=True)
    check("the composer advertises the same limit",
          f'maxlength="{A.MESSAGE_MAX_CHARS}"' in html)

# --- breach screening ------------------------------------------------------
# Stubbed at the HTTP boundary: the real range API cannot be reached from
# CI, and a check that silently passes because the network is down would be
# worse than no check. The stub answers in HIBP's own format.
_real_get = A.requests.get


def stub_hibp(password, count):
    digest = A.hashlib.sha1(password.encode()).hexdigest().upper()

    class Resp:
        text = "\r\n".join(
            ["0000000000000000000000000000000000A:3"]
            + ([f"{digest[5:]}:{count}"] if count is not None else []))

        def raise_for_status(self):
            pass

    A.requests.get = lambda url, timeout=None, headers=None: Resp()


PW = "trustno1234"
try:
    stub_hibp(PW, 50000)
    check("a breached password is refused", A.password_problem(PW, PW) is not None)
    stub_hibp(PW, A.HIBP_MAX_APPEARANCES + 1)
    check("just over the threshold is refused", A.password_problem(PW, PW) is not None)
    stub_hibp(PW, A.HIBP_MAX_APPEARANCES)
    check("at the threshold is allowed", A.password_problem(PW, PW) is None)
    stub_hibp(PW, None)
    check("a password absent from the corpus is allowed",
          A.password_problem(PW, PW) is None)

    # Only the first five hex digits of the SHA-1 may leave this process.
    sent = {}

    class Resp2:
        text = ""

        def raise_for_status(self):
            pass

    A.requests.get = lambda url, timeout=None, headers=None: (
        sent.update(url=url, headers=headers), Resp2())[1]
    A.breach_count(PW)
    suffix = sent["url"].split("/range/")[1]
    check("only a 5-character prefix is sent", len(suffix) == 5, suffix)
    check("the full hash never leaves the process",
          A.hashlib.sha1(PW.encode()).hexdigest().upper() not in sent["url"])
    check("padding is requested so the reply length says nothing",
          sent["headers"].get("Add-Padding") == "true")

    # An outage must not become an outage here.
    def boom(*a, **k):
        raise A.requests.RequestException("unreachable")

    A.requests.get = boom
    check("breach screening fails open when HIBP is unreachable",
          A.password_problem(PW, PW) is None)
    check("length is still enforced during an outage",
          A.password_problem("short", "short") is not None)
finally:
    A.requests.get = _real_get

# --- security events -------------------------------------------------------
with app.test_request_context():
    A.get_db().execute("TRUNCATE security_events")
    A.get_db().commit()
clear_rate_limits()


def events(kind):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT * FROM security_events WHERE kind = ? ORDER BY id", (kind,)).fetchall()


with app.test_client() as c:
    nm, _ = register(c)
    pw = "correct horse battery"   # register()'s default; it returns the response, not this
    c.post("/logout", data={"csrf_token": token(c, "/profile/edit")})
    c.post("/login", data={"username": nm, "password": "definitely-wrong",
                           "csrf_token": token(c)})
    c.post("/login", data={"username": nm, "password": pw, "csrf_token": token(c)})

logins = events("login")
outcomes = [r["outcome"] for r in logins]
check("a failed login is recorded", "failure" in outcomes, str(outcomes))
check("a successful login is recorded", "success" in outcomes, str(outcomes))
check("the attempt's address is recorded", all(r["ip"] for r in logins))
check("the attempted password is never recorded",
      not any("definitely-wrong" in (r["detail"] or "") for r in logins))

with app.test_client() as c:
    c.post("/login", data={"username": nm, "password": pw})  # no CSRF token
check("a rejected CSRF request is recorded", len(events("csrf")) >= 1)

# The spike alarm: once when it crosses, then quiet.
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM security_events WHERE kind = 'login_failure_spike'")
    db.execute("DELETE FROM security_events WHERE kind = 'login'")
    for i in range(A.LOGIN_FAILURE_SPIKE - 1):
        db.execute("INSERT INTO security_events (kind, outcome, ip)"
                   " VALUES ('login', 'failure', ?)", (f"10.0.0.{i % 250}",))
    db.commit()
    check("no alert below the threshold", len(events("login_failure_spike")) == 0)

    A.security_event("login", "failure", ip="10.9.9.9")
    check("the alert fires when failures spike",
          len(events("login_failure_spike")) == 1)

    for _ in range(15):
        A.security_event("login", "failure", ip="10.9.9.9")
    check("the alert does not repeat during its cooldown",
          len(events("login_failure_spike")) == 1,
          f"{len(events('login_failure_spike'))} alerts")

# Instrumentation must never take a request down with it.
_broken = A.get_db


def explode():
    raise RuntimeError("database gone")


try:
    A.get_db = explode
    with app.test_request_context():
        A.security_event("login", "failure", ip="10.0.0.1")
    check("a failure to record an event is swallowed", True)
except Exception as exc:
    check("a failure to record an event is swallowed", False, repr(exc))
finally:
    A.get_db = _broken

# --- the health check ------------------------------------------------------
# Two paths on purpose: Google's frontend eats the literal /healthz before it
# reaches the container, so /healthz serves Cloud Run's startup probe (which
# dials the container directly) and /-/health is what anything watching from
# outside can actually reach. Both must answer, and both must sit outside the
# machinery that would otherwise redirect or refuse them.
for path in A.HEALTH_PATHS:
    r = app.test_client().get(path)
    check(f"{path} answers", r.status_code == 200 and b"ok" in r.data, str(r.status_code))
    check(f"{path} is exempt from CSRF", path in A.CSRF_EXEMPT_PATHS)

# A configured canonical host must not redirect them: the probe arrives on the
# container's own hostname, so a 308 here would fail every deploy.
_host = A.CANONICAL_HOST
try:
    A.CANONICAL_HOST = "velvt.nl"
    client = app.test_client()
    for path in A.HEALTH_PATHS:
        r = client.get(path, base_url="http://some-revision.a.run.app")
        check(f"{path} is not redirected to the canonical host",
              r.status_code == 200, str(r.status_code))
    r = client.get("/", base_url="http://some-revision.a.run.app")
    check("...while an ordinary path still is", r.status_code == 308, str(r.status_code))
finally:
    A.CANONICAL_HOST = _host

# --- photo upload limits ------------------------------------------------
# The per-photo cap and the whole-request cap are two different refusals with
# two different failure modes, and only one of them can name the file that
# caused it. Both are checked, along with the relationship between them --
# a request cap below what the form is allowed to carry would refuse a save
# that every individual photo was within its rights to make.
import io as _io

MB = 1024 * 1024
_buf = _io.BytesIO()
try:
    from PIL import Image as _Image
    _Image.new("RGB", (64, 64), (120, 60, 200)).save(_buf, "JPEG")
    JPEG_HEAD = _buf.getvalue()
except ImportError:                       # Pillow is not a dependency of the app
    JPEG_HEAD = bytes.fromhex("ffd8ffe000104a46494600010100000100010000")


def jpeg(size_bytes):
    """A real JPEG header padded to length -- what the app measures."""
    return (_io.BytesIO(JPEG_HEAD + b"\x00" * (size_bytes - len(JPEG_HEAD))),
            "photo.jpg")


# Cloud Run refuses an HTTP/1 request over 32 MiB before it reaches the
# container, with its own error page rather than ours -- so a cap above that
# is not a cap this app enforces, and the 413 below would never be seen.
check("the request cap stays under what the platform allows",
      app.config["MAX_CONTENT_LENGTH"] < A.CLOUD_RUN_REQUEST_CEILING,
      "%d MB, ceiling %d MB" % (app.config["MAX_CONTENT_LENGTH"] // MB,
                                A.CLOUD_RUN_REQUEST_CEILING // MB))
# The browser is given a budget to check against so a save that is too big is
# a message on the form, not a page someone has to navigate back from. It has
# to be under the real cap, or the guard would wave through what the server
# then refuses.
with app.test_request_context():
    _ctx = A.inject_user()
check("the browser's budget is under the cap it protects",
      _ctx["upload_budget_bytes"] < app.config["MAX_CONTENT_LENGTH"],
      "%d MB of %d MB, the rest is the form's own fields"
      % (_ctx["upload_budget_bytes"] // MB,
         app.config["MAX_CONTENT_LENGTH"] // MB))
check("...and still fits a full-size photo",
      _ctx["upload_budget_bytes"] > A.PHOTO_MAX_BYTES)

check("...while still carrying a full-size photo",
      app.config["MAX_CONTENT_LENGTH"] > A.PHOTO_MAX_BYTES,
      "%d MB for a %d MB photo" % (app.config["MAX_CONTENT_LENGTH"] // MB,
                                   A.PHOTO_MAX_MB))
import translations as _T
check("the size in the copy is the size in the code",
      all("{size}" in _T.TRANSLATIONS[code]["msg.photo_too_big"]
          for code in _T.LANGUAGE_CODES),
      "in every language, so none of them can drift when the limit moves")

with app.test_request_context():
    db = A.get_db()
    up = db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, 'x') RETURNING id",
        ("upload_" + A.secrets.token_hex(3),)).fetchone()["id"]
    db.execute(
        "INSERT INTO profiles (user_id, name, age, gender, seeking)"
        " VALUES (?, 'Upload', 30, 'Man', 'Everyone')", (up,))
    db.commit()

up_client = app.test_client()
login_as(up_client, up)
_token = up_client.get("/profile/edit").get_data(as_text=True).split(
    'name="csrf-token" content="')[1].split('"')[0]


def save_photo(size_bytes):
    return up_client.post("/profile/edit", data={
        "csrf_token": _token, "name": "Upload", "age": "30",
        "gender": "Man", "seeking": "Everyone", "photos": jpeg(size_bytes),
    }, content_type="multipart/form-data", follow_redirects=True)


def stored():
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT COUNT(*) AS n FROM photos WHERE user_id = ?", (up,)
        ).fetchone()["n"]


save_photo(A.PHOTO_MAX_BYTES - MB)
check("a photo just inside the limit is stored", stored() == 1, str(stored()))

# --- what actually lands in the database --------------------------------
# The browser re-encodes before uploading, which saves the transfer. This is
# the half that decides what is *kept*, and it has to hold for a client that
# ran none of our JavaScript -- which is exactly what this test client is.
try:
    from PIL import Image as _PILImage
    import numpy as _np

    def _camera(w, h):
        """A photo the shape and weight of one off a phone."""
        rng = _np.random.default_rng(11)
        small = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=_np.uint8)
        big = _PILImage.fromarray(small).resize((w, h), _PILImage.BICUBIC)
        out = _io.BytesIO()
        big.save(out, "JPEG", quality=98, subsampling=0)
        return out.getvalue()

    raw = _camera(4032, 3024)
    with app.test_request_context():
        mime, kept = A.downscale_photo(raw, "image/jpeg")
    shrunk = _PILImage.open(_io.BytesIO(kept))

    check("a camera-sized photo is downscaled before it is stored",
          max(shrunk.size) <= A.PHOTO_STORE_MAX_EDGE,
          "%dx%d -> %dx%d" % (4032, 3024, shrunk.size[0], shrunk.size[1]))
    check("...which is most of its weight",
          len(kept) < len(raw) / 4,
          "%.1f MB -> %.1f MB" % (len(raw) / MB, len(kept) / MB))

    # Small in both senses -- inside the pixel cap *and* already light. Only
    # then is there nothing to gain, and recompressing would cost quality to
    # save nothing.
    _modest = _io.BytesIO()
    _PILImage.open(_io.BytesIO(_camera(1000, 750))).save(
        _modest, "JPEG", quality=70)
    modest = _modest.getvalue()
    with app.test_request_context():
        _, untouched = A.downscale_photo(modest, "image/jpeg")
    check("an already-modest photo is left exactly as it arrived",
          untouched == modest,
          "%dx%d, %d KB -- inside both thresholds"
          % (1000, 750, len(modest) // 1024))

    # A phone writes the GPS coordinates of where a photo was taken into it.
    # This app pins every profile to one city on purpose; storing someone's
    # street and handing it to whoever they match with would undo that, and
    # nothing on screen would look wrong.
    located = _io.BytesIO()
    shot = _PILImage.new("RGB", (3000, 2000), (10, 90, 160))
    _exif = shot.getexif()
    _exif[274] = 6                       # orientation: the camera was turned
    _exif[271] = "TestPhone"
    _gps = _exif.get_ifd(0x8825)
    _gps[1] = "N"
    _gps[2] = (52.0, 22.0, 0.0)
    shot.save(located, "JPEG", exif=_exif)

    before = _PILImage.open(_io.BytesIO(located.getvalue()))
    check("the fixture really does carry GPS",
          bool(before.getexif().get_ifd(0x8825)), "or the next check proves nothing")

    with app.test_request_context():
        _, cleaned = A.downscale_photo(located.getvalue(), "image/jpeg")
    after = _PILImage.open(_io.BytesIO(cleaned))
    check("a stored photo carries no EXIF, so no location",
          not dict(after.getexif()) and not after.getexif().get_ifd(0x8825))
    check("...and the rotation it carried was applied, not just dropped",
          after.size[0] < after.size[1],
          "%s landscape + orientation tag -> %s" % ((3000, 2000), after.size))

    with app.test_request_context():
        _, as_is = A.downscale_photo(b"\xff\xd8\xff\xe0" + b"\x00" * 4000,
                                     "image/jpeg")
    check("something undecodable is stored, not refused",
          as_is[:4] == b"\xff\xd8\xff\xe0",
          "it already passed the magic-byte check and the size cap")
except ImportError:                       # pragma: no cover
    # numpy is imported here too and is *not* in requirements.txt -- it is a
    # test and tools dependency only -- so naming that file as the remedy sent
    # you to install something that was already installed.
    check("Pillow and numpy are installed, so photos can be downscaled", False,
          "pip install pillow numpy")

reply = save_photo(A.PHOTO_MAX_BYTES + MB)
check("a photo over it is refused by name",
      "under %d MB" % A.PHOTO_MAX_MB in reply.get_data(as_text=True))
check("...and nothing of it is kept", stored() == 1, str(stored()))

# Past the whole-request cap there is no parsed form and no filename to
# blame, so this is the one that used to be a bare Werkzeug error page.
huge = up_client.post(
    "/profile/edit",
    data={"csrf_token": _token, "name": "Upload",
          "photos": jpeg(app.config["MAX_CONTENT_LENGTH"] + MB)},
    content_type="multipart/form-data")
check("an oversized request is refused with a 413", huge.status_code == 413,
      str(huge.status_code))
check("...on a page that explains itself",
      "Each photo can be up to" in huge.get_data(as_text=True))

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
if failed:
    print("failed: " + ", ".join(failed))
sys.exit(1 if failed else 0)
