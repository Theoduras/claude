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

with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE id IN (?, ?)", (a, b))
    db.commit()

print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all presence checks passed")
