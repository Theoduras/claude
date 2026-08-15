"""Verify seeded demo members never reach a real person's search pool.

    python check_bots.py

Runs itself twice in subprocesses, once with ALLOW_BOT_MATCHES off (what
production does) and once with it on (what local development needs), because
the flag is read at import time.

This is the check that matters most in the whole suite: getting it wrong
means a real person spends five minutes talking to a canned script and is
told it was a match.
"""

import os
import subprocess
import sys
import uuid

MODE = os.environ.get("_CHECK_BOTS_MODE")


def _run_mode(allow):
    env = dict(os.environ, _CHECK_BOTS_MODE="1", ALLOW_BOT_MATCHES="1" if allow else "0")
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    return subprocess.run([sys.executable, __file__], env=env).returncode


if not MODE:
    print("### bots excluded (production default) ###")
    rc1 = _run_mode(allow=False)
    print("\n### bots allowed (local development) ###")
    rc2 = _run_mode(allow=True)
    print("\nPASS" if rc1 == rc2 == 0 else "\nFAIL")
    sys.exit(rc1 or rc2)


# --- one mode, in-process ------------------------------------------------
import app as A
from app import app

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def make_searcher(label, is_bot):
    """A user with a profile and a ripe, filter-free waiting search.

    Every use_* switch is off so compatibility can never be the reason a
    pair does or doesn't form — the only variable under test is is_bot.
    """
    with app.test_request_context():
        db = A.get_db()
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash, is_bot) VALUES (?, ?, ?)",
            (f"botchk_{label}_{uuid.uuid4().hex[:8]}", "x", is_bot),
        )
        db.execute(
            """INSERT INTO profiles (user_id, name, age, gender, seeking, location)
               VALUES (?, ?, 30, 'Woman', 'Everyone', 'Berlin')""",
            (uid, label),
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


def empty_the_pool():
    with app.test_request_context():
        db = A.get_db()
        db.execute("UPDATE searches SET status='cancelled' WHERE status='waiting'")
        db.commit()


def reopen(uid):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """UPDATE searches SET status='waiting', match_id=NULL,
               created_at=NOW() - INTERVAL '60 seconds' WHERE user_id=?""", (uid,)
        )
        db.commit()


def partner_of(uid, match_id):
    if match_id is None:
        return None
    with app.test_request_context():
        row = A.get_db().execute(
            """SELECT CASE WHEN user_a=? THEN user_b ELSE user_a END AS other
               FROM matches WHERE id=?""", (uid, match_id)).fetchone()
    return None if row is None else row["other"]


print(f"ALLOW_BOT_MATCHES = {A.ALLOW_BOT_MATCHES}")
print(f"eligibility SQL   = {A.CANDIDATE_ELIGIBLE_SQL.strip()}")

# --- a lone real searcher against a pool of nothing but bots -------------
empty_the_pool()
me = make_searcher("real", is_bot=False)
bots = [make_searcher(f"bot{i}", is_bot=True) for i in range(3)]

with app.test_request_context():
    got = A.try_pair(me)
partner = partner_of(me, got)

if A.ALLOW_BOT_MATCHES:
    check("bots are pairable when the flag is on", partner in bots,
          f"partner {partner}")
else:
    check("a real user is never paired with a bot", got is None,
          f"paired with {partner}")

# --- the landing page's public count -------------------------------------
with app.test_request_context():
    db = A.get_db()
    total = db.execute(
        "SELECT COUNT(*) AS n FROM searches WHERE status='waiting'").fetchone()["n"]
    shown = db.execute(
        f"""SELECT COUNT(*) AS n FROM searches s JOIN users u ON u.id=s.user_id
            WHERE s.status='waiting' {A.CANDIDATE_ELIGIBLE_SQL}""").fetchone()["n"]

if A.ALLOW_BOT_MATCHES:
    check("the landing count includes bots when they're pairable", shown == total,
          f"{shown} of {total}")
else:
    check("the landing count advertises only pairable searchers", shown < total,
          f"{shown} of {total} waiting")

# --- a real partner still pairs, always ----------------------------------
# The pool is cleared first so `mate` is the only candidate in either mode:
# with the flag on, the leftover bots above are still waiting and would
# otherwise be picked, which says nothing about the case under test.
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM matches WHERE user_a=? OR user_b=?", (me, me))
    db.commit()
empty_the_pool()
reopen(me)
mate = make_searcher("mate", is_bot=False)
with app.test_request_context():
    got2 = A.try_pair(me)
check("two real people still pair", partner_of(me, got2) == mate,
      f"partner {partner_of(me, got2)}")

sys.exit(1 if failures else 0)
