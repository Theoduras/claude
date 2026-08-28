"""Verify a search only stays in the pool while its browser keeps polling.

    python check_presence.py

A `searches` row says 'waiting' until something changes it, and nothing does
when a searcher simply closes the tab. Without a heartbeat those abandoned
rows accumulate and the matcher happily pairs live people with them — the
searcher gets an "it's a match", a five-minute room, and nobody on the other
side. `searches.last_seen` is rewritten by every request the waiting screen
makes, and SEARCH_ALIVE_SECONDS of silence takes the row out of every pool
query at once (they all interpolate CANDIDATE_ELIGIBLE_SQL).

Runs with ALLOW_BOT_MATCHES off, the production setting: the point is what
happens to *real* searchers.
"""

import os
import uuid

os.environ.setdefault("ALLOW_BOT_MATCHES", "0")

import app as A
from app import app

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def make_searcher(label, gender, seeking):
    """A ripe, filter-free waiting search, fresh as of now.

    Every optional switch is off so compatibility can never be the reason a
    pair does or doesn't form — the only variable under test is last_seen.
    """
    with app.test_request_context():
        db = A.get_db()
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash, is_bot) VALUES (?, ?, FALSE)",
            (f"presence_{label}_{uuid.uuid4().hex[:8]}", "x"),
        )
        db.execute(
            """INSERT INTO profiles (user_id, name, age, gender, seeking)
               VALUES (?, ?, 30, ?, ?)""",
            (uid, label, gender, seeking),
        )
        db.execute(
            """INSERT INTO searches
                 (user_id, seeking, age_min, age_max, relationship_type, status,
                  use_gender, use_age, use_relationship, use_distance, use_physical,
                  created_at, last_seen)
               VALUES (?, ?, 18, 60, '', 'waiting',
                       FALSE, FALSE, FALSE, FALSE, FALSE,
                       NOW() - INTERVAL '60 seconds', NOW())""",
            (uid, seeking),
        )
        db.commit()
    return uid


def empty_the_pool():
    with app.test_request_context():
        db = A.get_db()
        db.execute("UPDATE searches SET status='cancelled' WHERE status='waiting'")
        db.commit()


def reopen(*uids):
    """Put both searches back to square one, ripe and freshly seen."""
    with app.test_request_context():
        db = A.get_db()
        for uid in uids:
            db.execute("DELETE FROM matches WHERE user_a = ? OR user_b = ?", (uid, uid))
            db.execute(
                """UPDATE searches
                   SET status='waiting', match_id=NULL,
                       created_at = NOW() - INTERVAL '60 seconds', last_seen = NOW()
                   WHERE user_id = ?""",
                (uid,),
            )
        db.commit()


def go_quiet(uid, seconds):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            "UPDATE searches SET last_seen = NOW() - (? * INTERVAL '1 second') WHERE user_id = ?",
            (seconds, uid),
        )
        db.commit()


def pair(uid):
    with app.test_request_context():
        return A.try_pair(uid)


def pool(uid):
    with app.test_request_context():
        _, others = A._search_pool(uid)
        return [o["user_id"] for o in others]


def landing_count():
    with app.test_request_context():
        return app.test_client().get("/").status_code


empty_the_pool()
a = make_searcher("a", "Woman", "Men")
b = make_searcher("b", "Man", "Women")

check("two people both polling still pair", pair(a) is not None)

reopen(a, b)
go_quiet(b, A.SEARCH_ALIVE_SECONDS * 5)
check("a searcher who stopped polling is not pairable", pair(a) is None)
check("and is gone from the preview pool too", b not in pool(a), f"pool={pool(a)}")

# The whole point of one shared fragment: the matcher and the preview cannot
# disagree about who is live, because they read the same clause.
check(
    "the liveness clause is part of the shared eligibility SQL",
    "last_seen" in A.CANDIDATE_ELIGIBLE_SQL,
    A.CANDIDATE_ELIGIBLE_SQL.strip(),
)

reopen(a, b)
go_quiet(b, A.SEARCH_ALIVE_SECONDS * 5)
with app.test_request_context():
    A.touch_search(b)
check("one heartbeat puts them straight back", pair(a) is not None)

# A missed tick or two must not eject someone mid-search.
reopen(a, b)
go_quiet(b, A.SEARCH_ALIVE_SECONDS // 2)
check("a brief gap is forgiven", pair(a) is not None)

# touch_search() must never revive a search the user actually stopped.
reopen(a, b)
with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE searches SET status='cancelled' WHERE user_id = ?", (b,))
    db.commit()
    A.touch_search(b)
    still = db.execute("SELECT status FROM searches WHERE user_id = ?", (b,)).fetchone()["status"]
check("a heartbeat cannot resurrect a cancelled search", still == "cancelled", still)

check("the landing page still renders its count", landing_count() == 200)



# --- the search survives leaving the waiting screen ----------------------
#
# The heartbeat is no longer the waiting screen alone: base.html's poll runs
# on every signed-in page, only while the tab is visible, and that is what
# "still online" means here. What follows is the pair of promises that makes
# -- a search that keeps running while you are anywhere in the app, and one
# that pauses (rather than vanishing) once you are not.

def make_full_member(label, gender, seeking):
    """A searcher who can actually reach /search: complete profile, a photo,
    and the matching explainer already acknowledged."""
    uid = make_searcher(label, gender, seeking)
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            "INSERT INTO photos (user_id, data, mime, is_primary) VALUES (?, ?, 'image/png', TRUE)",
            (uid, b"\x89PNG\r\n\x1a\n"),
        )
        db.execute(
            "UPDATE users SET match_intro_seen_at = NOW() WHERE id = ?", (uid,))
        db.execute(
            "UPDATE searches SET relationship_type = 'Long-term relationship' WHERE user_id = ?",
            (uid,),
        )
        db.commit()
    return uid


def client_for(uid):
    client = app.test_client()
    login_as(client, uid)
    return client


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


def status_of(uid):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT status FROM searches WHERE user_id = ?", (uid,)
        ).fetchone()["status"]


def last_seen_age(uid):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT EXTRACT(EPOCH FROM (NOW() - last_seen)) AS age FROM searches WHERE user_id = ?",
            (uid,),
        ).fetchone()["age"]


empty_the_pool()
c = make_full_member("c", "Woman", "Men")
client = client_for(c)

# The poll every signed-in page runs is the heartbeat. Without this, reading
# a chat for two minutes silently ended the search.
reopen(c)
go_quiet(c, A.SEARCH_ALIVE_SECONDS // 2)
client.get("/notifications/feed")
check("the app-wide poll is a heartbeat", last_seen_age(c) < 5, f"{last_seen_age(c):.0f}s")

feed = client.get("/notifications/feed").get_json()
check("...and it reports the search as running", feed["search"]["state"] == "waiting",
      str(feed["search"]))

# But being back in the app is not the same as asking to search again: a
# paused search is reported, never quietly restarted.
go_quiet(c, A.SEARCH_ALIVE_SECONDS * 5)
feed = client.get("/notifications/feed").get_json()
check("a paused search is not revived by the poll",
      feed["search"]["state"] == "paused" and last_seen_age(c) > A.SEARCH_ALIVE_SECONDS,
      str(feed["search"]))

# ...nor by a heartbeat on a search the user stopped themselves.
with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE searches SET status='cancelled' WHERE user_id = ?", (c,))
    db.commit()
client.get("/notifications/feed")
check("the poll cannot resurrect a cancelled search", status_of(c) == "cancelled",
      status_of(c))

# --- /search shows the search rather than re-asking for it ---------------
reopen(c)
r = client.get("/search")
check("/search returns you to a running search",
      r.status_code == 302 and r.headers["Location"].endswith("/search/waiting"),
      f"{r.status_code} {r.headers.get('Location')}")

r = client.get("/search?new=1")
check("...but ?new=1 still gets the wizard", r.status_code == 200 and b"wiz-form" in r.data,
      str(r.status_code))

go_quiet(c, A.SEARCH_ALIVE_SECONDS * 5)
r = client.get("/search")
check("a paused search is offered back, not re-asked",
      r.status_code == 200 and b"/search/resume" in r.data, str(r.status_code))

# --- resuming ------------------------------------------------------------
def resume(client):
    with client.session_transaction() as s:
        pass
    page = client.get("/search")
    token = page.data.split(b'name="csrf_token" value="')[1].split(b'"')[0].decode()
    return client.post("/search/resume", data={"csrf_token": token})


r = resume(client)
check("resume puts it back in the pool",
      r.status_code == 302 and status_of(c) == "waiting"
      and last_seen_age(c) < 5, f"{r.status_code} {status_of(c)}")

with app.test_request_context():
    elapsed = A.get_db().execute(
        "SELECT EXTRACT(EPOCH FROM (NOW() - created_at)) AS age FROM searches WHERE user_id = ?",
        (c,)).fetchone()["age"]
check("...counting from the resume, not from yesterday", elapsed < 5, f"{elapsed:.0f}s")

# A search the searcher stopped is resumable too -- that is the whole point
# of keeping the row -- but not once they have withdrawn the consent that
# cancelled it, or the withdrawal would be undone by a single tap.
with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE searches SET status='cancelled' WHERE user_id = ?", (c,))
    db.execute(
        """INSERT INTO consents (user_id, purpose, withdrawn_at)
           VALUES (?, ?, NOW())
           ON CONFLICT (user_id, purpose) DO UPDATE SET withdrawn_at = NOW()""",
        (c, A.CONSENT_SENSITIVE))
    db.commit()
r = resume(client)
check("a withdrawn consent refuses the resume",
      status_of(c) == "cancelled", status_of(c))

with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE consents SET withdrawn_at = NULL WHERE user_id = ?", (c,))
    db.commit()
resume(client)
check("and with the consent back it resumes", status_of(c) == "waiting", status_of(c))

# --- matched: the app takes you to it, from wherever you are -------------
d = make_full_member("d", "Man", "Women")
reopen(c, d)
pair(c)
feed = client.get("/notifications/feed").get_json()
check("a live match is carried to every screen",
      feed["search"]["state"] == "matched" and "/chat/" in feed["search"].get("chat_url", ""),
      str(feed["search"]))

with app.test_request_context():
    db = A.get_db()
    db.execute("UPDATE matches SET status = 'ended', ended_at = NOW() WHERE user_a = ? OR user_b = ?",
               (c, c))
    db.commit()
feed = client.get("/notifications/feed").get_json()
check("a match that is over is not", "chat_url" not in feed["search"], str(feed["search"]))


with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE id IN (?, ?, ?, ?)", (a, b, c, d))
    db.commit()

print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all presence checks passed")
