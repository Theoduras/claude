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


def offers_for(uid):
    with app.test_request_context():
        mine, others = A._search_pool(uid)
        b = A.search_blockers(mine, others)
        return b.get("current_count", 0), A.widen_options(b, mine)


def search_row(uid):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT * FROM searches WHERE user_id = ?", (uid,)).fetchone()


empty_the_pool()
me = aged_searcher("me", 28, 25, 30)      # wants 25-30
them = aged_searcher("them", 41, 18, 60)  # is 41, wants anyone

fits, offers = offers_for(me)
actions = [o["action"] for o in offers]
check("a stuck search is offered a way out", fits == 0 and "widen:age" in actions,
      f"fits={fits}, offered {actions}")
check("the offer names the smallest widening that works",
      any(o["action"] == "widen:age" and "25–41" in o["label"] for o in offers),
      str([o["label"] for o in offers]))
check("the offer counts who it would actually reach",
      all(o["count"] >= 1 for o in offers))

# Nothing is offered while somebody already fits.
_, open_offers = offers_for(them)
check("no offers while someone already fits", open_offers == [],
      f"offered {[o['action'] for o in open_offers]}")

with app.test_client() as c:
    login_as(c, me)
    before = search_row(me)

    check("widening needs a CSRF token",
          c.post("/search/widen", data={"action": "widen:age"}).status_code == 400)

    # A value in the body must be ignored: the server re-derives its own.
    r = c.post("/search/widen",
               data={"action": "widen:age", "age_min": 0, "age_max": 99,
                     "csrf_token": token(c, "/search/waiting")},
               follow_redirects=False)
    after = search_row(me)
    check("applying an offer succeeds", r.status_code == 302, f"HTTP {r.status_code}")
    check("the server's own value is applied, not the request's",
          (after["age_min"], after["age_max"]) == (25, 41),
          f"{after['age_min']}-{after['age_max']}")
    check("the accumulated wait is preserved",
          before["created_at"] == after["created_at"])
    check("widening pairs immediately when it can", after["status"] == "matched",
          after["status"])

# An action that isn't currently on offer changes nothing.
empty_the_pool()
solo = aged_searcher("solo", 30, 18, 39)
with app.test_client() as c:
    login_as(c, solo)
    was = search_row(solo)
    r = c.post("/search/widen",
               data={"action": "off:physical", "csrf_token": token(c, "/search/waiting")},
               follow_redirects=False)
    now = search_row(solo)
    check("an offer that isn't available is refused",
          now["use_physical"] == was["use_physical"] and now["age_min"] == was["age_min"],
          f"HTTP {r.status_code}")
    r = c.post("/search/widen",
               data={"action": "off:everything; DROP TABLE users",
                     "csrf_token": token(c, "/search/waiting")})
    check("an invented action is refused", r.status_code in (302, 400),
          f"HTTP {r.status_code}")
    with app.test_request_context():
        still = A.get_db().execute("SELECT 1 AS h FROM users LIMIT 1").fetchone()
    check("the database is intact", still is not None)

# Physical traits blocking: no suggestion helper covers these, so the
# off-switch is the only thing that can help.
empty_the_pool()
picky = aged_searcher("picky", 30, 18, 39, height=170, use_physical=True,
                      pref_height_min=200, pref_height_max=220)
short = aged_searcher("short", 30, 18, 39, height=165)
fits2, offers2 = offers_for(picky)
check("a physical filter that blocks is offered as an off-switch",
      fits2 == 0 and "off:physical" in [o["action"] for o in offers2],
      f"fits={fits2}, offered {[o['action'] for o in offers2]}")

with app.test_client() as c:
    login_as(c, picky)
    c.post("/search/widen", data={"action": "off:physical",
                                  "csrf_token": token(c, "/search/waiting")})
    check("switching the physical filter off works",
          search_row(picky)["use_physical"] is False)

# /search/options answers the waiting page's refresh.
empty_the_pool()
a1 = aged_searcher("poll", 28, 25, 30)
a2 = aged_searcher("pollb", 41, 18, 60)
with app.test_client() as c:
    login_as(c, a1)
    data = c.get("/search/options").get_json()
    check("/search/options reports the live offers",
          data["fits"] == 0 and any(o["action"] == "widen:age" for o in data["options"]),
          str(data))


# --- 13. changing email --------------------------------------------------
def email_row(uid):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT email, pending_email, email_verified_at FROM users WHERE id = ?",
            (uid,),
        ).fetchone()


def uniq_email(prefix):
    """Unique per run, not just per test -- these checks run against a
    persistent dev database, and a literal address confirmed by a past run
    would make 'already claimed' checks pass for the wrong reason."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.test"


clear_rate_limits()
with app.test_client() as c:
    alice, _ = register(c)
    aid = uid_of(alice)
    with app.test_client() as bc:
        bob, _ = register(bc)
    bob_email = email_row(uid_of(bob))["email"]
    original = email_row(aid)
    new_addr = uniq_email("alice-new")

    r = c.post("/settings/email",
               data={"email": new_addr, "password": "wrong password",
                     "csrf_token": token(c, "/settings")})
    check("changing email requires the current password",
          email_row(aid)["pending_email"] is None, f"HTTP {r.status_code}")

    r = c.post("/settings/email",
               data={"email": "not-an-address", "password": "correct horse battery",
                     "csrf_token": token(c, "/settings")})
    check("an invalid address is rejected",
          email_row(aid)["pending_email"] is None, f"HTTP {r.status_code}")

    r = c.post("/settings/email",
               data={"email": original["email"], "password": "correct horse battery",
                     "csrf_token": token(c, "/settings")})
    check("submitting your own current address is a no-op",
          email_row(aid)["pending_email"] is None)

    r = c.post("/settings/email",
               data={"email": new_addr, "password": "correct horse battery",
                     "csrf_token": "not-a-real-token"})
    check("changing email requires a CSRF token", r.status_code == 400)

    r = c.post("/settings/email",
               data={"email": bob_email, "password": "correct horse battery",
                     "csrf_token": token(c, "/settings")})
    check("an address already claimed by another account is rejected",
          email_row(aid)["pending_email"] is None, f"HTTP {r.status_code}")

    r = c.post("/settings/email",
               data={"email": new_addr, "password": "correct horse battery",
                     "csrf_token": token(c, "/settings")})
    mid = email_row(aid)
    check("a valid change sets pending_email, leaving email alone",
          mid["pending_email"] == new_addr and mid["email"] == original["email"])
    check("email_verified_at is untouched until confirmed",
          mid["email_verified_at"] == original["email_verified_at"])

    r = c.get("/settings/email/confirm/not-a-real-token", follow_redirects=False)
    check("an unknown confirm token is rejected without erroring", r.status_code == 302)
    check("a rejected token leaves the pending change in place",
          email_row(aid)["pending_email"] == new_addr)

    with app.test_request_context():
        real_tok = A.issue_email_token(aid, "email_change", 48)
    c.get(f"/settings/email/confirm/{real_tok}", follow_redirects=False)
    done = email_row(aid)
    check("confirming moves pending_email into email",
          done["email"] == new_addr and done["pending_email"] is None)
    check("confirming marks the new address verified", done["email_verified_at"] is not None)

    clear_rate_limits()  # the checks above already spent most of this account's budget
    again_addr = uniq_email("alice-again")
    c.post("/settings/email",
           data={"email": again_addr, "password": "correct horse battery",
                 "csrf_token": token(c, "/settings")})
    check("a follow-up change can be started",
          email_row(aid)["pending_email"] == again_addr)
    c.post("/settings/email/cancel", data={"csrf_token": token(c, "/settings")})
    check("cancelling clears the pending change", email_row(aid)["pending_email"] is None)

# Two accounts can both point pending_email at the same address -- nothing
# stops that, since only `email` itself is unique. Whoever confirms first
# should win it; the second confirm must fail cleanly, not corrupt a row or
# leave two accounts sharing an address. Two separate `with` statements, not
# one with both clients: Werkzeug's test client keeps its last request
# context pushed until the client's own `with` block exits or it makes
# another request, and that context lives on one shared stack -- two clients
# open at once step on each other's pushes and pops.
with app.test_client() as c1:
    carol, _ = register(c1)
with app.test_client() as c2:
    dana, _ = register(c2)
cid, did = uid_of(carol), uid_of(dana)
contested = uniq_email("contested")
with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE users SET pending_email = ? WHERE id IN (?, ?)",
               (contested, cid, did))
    db.commit()
    tok_c = A.issue_email_token(cid, "email_change", 48)
    tok_d = A.issue_email_token(did, "email_change", 48)
with app.test_client() as c1:
    c1.get(f"/settings/email/confirm/{tok_c}", follow_redirects=False)
with app.test_client() as c2:
    r2 = c2.get(f"/settings/email/confirm/{tok_d}", follow_redirects=False)
row_c, row_d = email_row(cid), email_row(did)
check("the first confirm to arrive wins the contested address",
      row_c["email"] == contested)
check("the second confirm is refused rather than erroring",
      r2.status_code == 302 and row_d["email"] != contested,
      f"HTTP {r2.status_code}")
check("the loser's pending_email is cleared rather than left dangling",
      row_d["pending_email"] is None)
with app.test_request_context():
    dupes = A.get_db().execute(
        "SELECT COUNT(*) AS n FROM users WHERE LOWER(email) = LOWER(?)",
        (contested,),
    ).fetchone()["n"]
check("the address ends up claimed by exactly one account", dupes == 1, str(dupes))

clear_rate_limits()
with app.test_client() as c:
    name, _ = register(c)
    codes = [
        c.post("/settings/email",
               data={"email": uniq_email(f"flood{i}"), "password": "correct horse battery",
                     "csrf_token": token(c, "/settings")}).status_code
        for i in range(7)
    ]
    check("repeated email-change attempts are throttled", 429 in codes,
          f"saw {sorted(set(codes))}")

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
if failed:
    print("failed: " + ", ".join(failed))
sys.exit(1 if failed else 0)
