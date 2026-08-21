"""Verify the landing page's busyness line is true at every tier.

    python check_landing.py

The line under the headline is the last thing a visitor reads before
deciding whether to sign up, which makes it the most tempting place in the
app to overstate. It is built from four tiers (landing_pulse()), and the
only thing worth testing is that each one says something the database
actually supports -- and that the quiet ones do not borrow the live tier's
pulsing dot, which claims someone is here *now*.
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
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")


def clear():
    """Empty the pool of everything the pulse counts.

    Every tier is a count over real (non-demo) accounts, so leaving a single
    leftover test user behind makes the next assertion measure the wrong
    thing -- which it did, loudly, the first time this ran against a
    development database with 786 of them in it. Demo members stay: proving
    they are never counted is one of the checks below. The admin stays too,
    since deleting it would break every other suite.
    """
    with app.test_request_context():
        db = A.get_db()
        db.execute("DELETE FROM users WHERE is_bot = FALSE AND is_admin = FALSE")
        db.execute("UPDATE searches SET status = 'cancelled' WHERE status = 'waiting'")
        db.commit()


def member(*, searching=False, joined_days_ago=0, searched_days_ago=None, is_bot=False):
    with app.test_request_context():
        db = A.get_db()
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash, is_bot, status, created_at) "
            "VALUES (?, 'x', ?, 'active', NOW() - (? * INTERVAL '1 day'))",
            (f"pulse_{uuid.uuid4().hex[:8]}", is_bot, joined_days_ago))
        db.execute("INSERT INTO profiles (user_id, name, age, gender, seeking) "
                   "VALUES (?, 'P', 30, 'Woman', 'Everyone')", (uid,))
        if searching or searched_days_ago is not None:
            ago = searched_days_ago if searched_days_ago is not None else 0
            db.execute(
                """INSERT INTO searches (user_id, seeking, status, created_at, last_seen)
                   VALUES (?, 'Everyone', ?, NOW() - (? * INTERVAL '1 day'), NOW())""",
                (uid, "waiting" if searching else "cancelled", ago))
        db.commit()
        return uid


def pulse():
    with app.test_request_context():
        return A.landing_pulse()


# --- tier 4: nothing to report --------------------------------------------
clear()
p = pulse()
check("with nobody registered it invites rather than counts",
      not p["live"] and not any(c.isdigit() for c in p["text"]), p["text"])

# --- tier 3: members, but only once there are enough ----------------------
clear()
member(joined_days_ago=30)
p = pulse()
check("one member is still not a number worth showing",
      not any(c.isdigit() for c in p["text"]), p["text"])

clear()
for _ in range(A.MEMBER_COUNT_FLOOR):
    member(joined_days_ago=30)
p = pulse()
with app.test_request_context():
    real = A.get_db().execute(
        "SELECT COUNT(*) AS n FROM users WHERE is_bot = FALSE AND status = 'active'"
    ).fetchone()["n"]
check("past the floor it shows a count", any(c.isdigit() for c in p["text"]) and not p["live"],
      p["text"])
# The point of the whole exercise: the figure on the page is the figure in the
# table, not a floor, not a nudge. (real is a little above the floor here --
# clear() leaves the admin account, which is a real active user too.)
check("the number shown is the number in the database", str(real) in p["text"],
      f"db={real} text={p['text']!r}")

# --- demo members must never be counted -----------------------------------
clear()
for _ in range(40):
    member(joined_days_ago=1, is_bot=True)
p = pulse()
check("40 demo accounts do not become a member count",
      not any(c.isdigit() for c in p["text"]), p["text"])

# --- tier 2: searched today ----------------------------------------------
clear()
member(searched_days_ago=0)
p = pulse()
check("a search today is reported, without the live dot",
      "1" in p["text"] and not p["live"], p["text"])

# --- tier 1: live now, and only this tier gets the dot --------------------
clear()
member(searching=True)
p = pulse()
check("someone searching now earns the live dot", p["live"] and "1" in p["text"], p["text"])

clear()
print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all landing checks passed")
