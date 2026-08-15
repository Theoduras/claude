"""The retention schedule, against real rows aged past their limits.

Every case is paired with a control that must survive -- a purge job that
deletes everything passes any test that only checks that something went.
"""
import app as A
from app import app

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("ok    " if ok else "FAIL  ") + name + (("  — " + str(detail)) if detail else ""))


def q(sql, params=()):
    return A.get_db().execute(sql, params).fetchall()


def mkuser(tag):
    uid = A.get_db().execute(
        "INSERT INTO users (username, password_hash, status) VALUES (?, 'x', 'active')"
        " RETURNING id", ("ret_" + tag + A.secrets.token_hex(3),)).fetchone()["id"]
    A.get_db().execute(
        "INSERT INTO profiles (user_id, name, age, gender, seeking)"
        " VALUES (?, ?, 30, 'Man', 'Everyone')", (uid, tag))
    return uid


def mkmatch(a, b, status, ended_days_ago=None):
    if ended_days_ago is None:
        return A.get_db().execute(
            "INSERT INTO matches (user_a, user_b, status, paired_at)"
            " VALUES (?, ?, ?, NOW()) RETURNING id", (a, b, status)).fetchone()["id"]
    return A.get_db().execute(
        """INSERT INTO matches (user_a, user_b, status, paired_at, ended_at)
           VALUES (?, ?, ?, NOW() - (? * INTERVAL '1 day'),
                   NOW() - (? * INTERVAL '1 day')) RETURNING id""",
        (a, b, status, ended_days_ago + 1, ended_days_ago)).fetchone()["id"]


def msg(mid, sender):
    A.get_db().execute(
        "INSERT INTO messages (match_id, sender_id, body) VALUES (?, ?, 'hi')", (mid, sender))


with app.test_request_context():
    db = A.get_db()
    OLD = A.ENDED_MATCH_RETENTION_DAYS + 5
    NEW = A.ENDED_MATCH_RETENTION_DAYS - 5

    # A unique constraint on (user_a, user_b) means every match needs its
    # own pair of people.
    def pair(tag):
        return mkuser(tag + "1"), mkuser(tag + "2")

    (s1, s2), (r1, r2) = pair("stale"), pair("recent")
    (l1, l2), (p1, p2) = pair("live"), pair("reported")

    stale = mkmatch(s1, s2, "ended", OLD)          # past the limit -> goes
    recent = mkmatch(r1, r2, "ended", NEW)         # inside the limit -> stays
    live = mkmatch(l1, l2, "active")               # not ended at all -> stays
    reported = mkmatch(p1, p2, "ended", OLD)       # open report -> stays
    for m, sender in ((stale, s1), (recent, r1), (live, l1), (reported, p1)):
        msg(m, sender)

    db.execute(
        """INSERT INTO reports (reporter_id, reported_id, match_id, reason, detail)
           VALUES (?, ?, ?, 'other', 'open complaint')""", (p1, p2, reported))

    # searches: resolved and old goes; resolved and fresh stays; waiting stays
    searchers = {}
    for st, age, tag in (("cancelled", 30, "old_cancelled"),
                         ("matched", 30, "old_matched"),
                         ("cancelled", 1, "fresh_cancelled"),
                         ("waiting", 400, "ancient_waiting")):
        uid = mkuser(tag)
        searchers[tag] = uid
        db.execute(
            """INSERT INTO searches (user_id, status, lat, lng, created_at)
               VALUES (?, ?, 52.5200066, 13.4049540, NOW() - (? * INTERVAL '1 day'))""",
            (uid, st, age))
    db.commit()

    before = {t: q("SELECT COUNT(*) AS n FROM " + t)[0]["n"]
              for t in ("matches", "messages", "searches")}

    counts = A.purge_expired_data()
    print("\npurge reported: %s\n" % counts)

    ids = [r["id"] for r in q("SELECT id FROM matches")]
    check("an ended match past its limit is purged", stale not in ids)
    check("an ended match inside its limit survives", recent in ids)
    check("an active match is never touched", live in ids)
    check("an ended match with an open report survives", reported in ids,
          "evidence must outlive the retention window")

    left = [r["match_id"] for r in q("SELECT match_id FROM messages")]
    check("the purged match's messages go with it", stale not in left)
    check("the surviving matches keep their messages",
          recent in left and reported in left)

    # Scoped to this run's own rows -- the table also holds the demo seed
    # and every earlier run's leftovers, so a table-wide count proves nothing.
    def search_for(tag):
        rows = q("SELECT * FROM searches WHERE user_id = ?", (searchers[tag],))
        return rows[0] if rows else None

    check("an old cancelled search is purged", search_for("old_cancelled") is None)
    check("an old matched search is purged", search_for("old_matched") is None)
    check("a still-waiting search is never purged on age alone",
          search_for("ancient_waiting") is not None)

    waiting = search_for("ancient_waiting")
    check("an old search's coordinates are coarsened, not cleared",
          waiting["lat"] is not None and float(waiting["lat"]) == 52.52,
          waiting["lat"])

    fresh = search_for("fresh_cancelled")
    check("a recent search keeps full precision",
          float(fresh["lat"]) == 52.5200066, fresh["lat"])

    # Idempotence: a daily job runs every day, including the days it has
    # nothing to do.
    again = A.purge_expired_data()
    check("a second run is a no-op",
          not any(again[k] for k in ("matches", "messages", "searches",
                                     "coordinates_coarsened", "reports")),
          str(again))

    check("the job reports what it actually did",
          counts["matches"] >= 1 and counts["messages"] >= 1, str(counts))

print()
bad = [n for n, ok in RESULTS if not ok]
print("%d/%d checks passed" % (len(RESULTS) - len(bad), len(RESULTS)))
for n in bad:
    print("  failed: " + n)
raise SystemExit(1 if bad else 0)
