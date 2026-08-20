"""The notification system, against real rows.

Four reasons to tell somebody something, three ways of telling them, and one
ledger underneath. What is checked here is the behaviour that is easy to get
subtly wrong and impossible to notice: who is told, who is *not*, how often,
and what each channel is allowed to carry.

Every "this goes out" check is paired with a "this stays quiet" control. A
notifier that tells everybody everything passes any test that only asks
whether something was sent.
"""
import base64
import os

import app as A
from app import app

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("ok    " if ok else "FAIL  ") + name + (("  — " + str(detail)) if detail else ""))


def db():
    return A.get_db()


def mkuser(tag, *, verified=True, bot=False, status="active"):
    uid = db().execute(
        """
        INSERT INTO users (username, password_hash, email, email_verified_at,
                           is_bot, status, created_at)
        VALUES (?, 'x', ?, ?, ?, ?, NOW() - INTERVAL '30 days') RETURNING id
        """,
        ("nt_" + tag + A.secrets.token_hex(3),
         f"nt_{tag}_{A.secrets.token_hex(3)}@example.test",
         A.dt.now(A.timezone.utc) if verified else None, bot, status),
    ).fetchone()["id"]
    db().execute(
        """
        INSERT INTO profiles (user_id, name, age, gender, seeking, location)
        VALUES (?, ?, 30, 'Man', 'Everyone', ?)
        """,
        (uid, tag, A.SINGLE_CITY or "Maastricht"),
    )
    db().execute(
        "INSERT INTO photos (user_id, data, mime, is_primary) VALUES (?, ?, 'image/png', TRUE)",
        (uid, b"\x89PNG\r\n\x1a\n"),
    )
    db().commit()
    return uid


def start_search(uid):
    """A live search, through the same helper both screens use."""
    place, lat, lng = A.pinned_place()
    A.save_search(
        uid, seeking="Everyone", age_min=18, age_max=99,
        relationship_type="Long-term relationship", interests="",
        location=place, lat=lat, lng=lng, radius_km=A.RADIUS_MAX_KM,
        pref_height_min=None, pref_height_max=None, pref_body_types="",
        pref_fitness_level="", pref_hair_color="", pref_eye_color="",
        pref_tattoos="", use_gender=False, use_age=False,
        use_distance=False, use_physical=False,
    )


def notices(uid, kind=None):
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    args = [uid]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    return db().execute(sql + " ORDER BY id", tuple(args)).fetchall()


with app.test_request_context():
    # ---------------------------------------------------------------- prefs
    someone = mkuser("prefs")
    prefs = A.notification_prefs(someone)

    check("a fresh account has an opinion about every kind",
          sorted(prefs) == sorted(A.NOTIFY_KIND_KEYS))
    check("messages are mailed by default", prefs["message"]["email"])
    check("feature announcements are not mailed by default",
          not prefs["feature"]["email"] and not prefs["feature"]["push"],
          "announcements are marketing; opt-in, not opt-out")
    check("...but they do land in the app",
          prefs["feature"]["browser"])

    # One change writes all four kinds, so "left at the default" and
    # "deliberately the same as the default" stop being the same row.
    A.save_notification_prefs(someone, {"message": {"browser": True}})
    stored = db().execute(
        "SELECT * FROM notification_prefs WHERE user_id = ?", (someone,)).fetchall()
    check("saving writes every kind, not only the changed one",
          len(stored) == len(A.NOTIFY_KIND_KEYS), len(stored))
    check("an unticked box is off, not absent",
          A.notification_prefs(someone)["message"]["email"] is False)

    # -------------------------------------------------------------- the ledger
    reader = mkuser("ledger")
    first = A.notify(reader, "reminder", "One", "body", url="/", dedupe_key="k")
    again = A.notify(reader, "reminder", "Two", "body", url="/", dedupe_key="k")
    check("a notice is recorded", first is not None)
    check("the same thing is not said twice", again is None,
          "NOTIFY_DEDUPE_MINUTES['reminder'] = %s" % A.NOTIFY_DEDUPE_MINUTES["reminder"])
    check("a different thing still is",
          A.notify(reader, "reminder", "Three", dedupe_key="other") is not None)

    demo = mkuser("bot", bot=True)
    check("demo members are never notified",
          A.notify(demo, "message", "hi") is None,
          "they auto-reply in chat, which is exactly what would notify them")
    gone = mkuser("suspended", status="suspended")
    check("a suspended account is not notified", A.notify(gone, "message", "hi") is None)

    try:
        A.notify(reader, "invented", "hi")
        bad_kind = False
    except ValueError:
        bad_kind = True
    check("an unknown kind is a bug, not a silent no-op", bad_kind)

    # ------------------------------------------------------------ email gating
    unverified = mkuser("unverified", verified=False)
    A.notify(unverified, "reminder", "Confirm first")
    row = notices(unverified)[0]
    check("an unconfirmed address is never mailed", row["email_due_at"] is None)

    verified = mkuser("verified")
    A.notify(verified, "reminder", "Mail me")
    row = notices(verified)[0]
    check("a confirmed address is queued for mail", row["email_due_at"] is not None)
    check("...but not immediately", row["email_due_at"] > row["created_at"],
          "%s minutes of grace" % A.NOTIFY_EMAIL_DELAY_MINUTES)

    off = mkuser("nomail")
    A.save_notification_prefs(off, {k: {"browser": True} for k in A.NOTIFY_KIND_KEYS})
    A.notify(off, "reminder", "Not by mail")
    check("mail is not queued for someone who said no",
          notices(off)[0]["email_due_at"] is None)
    check("...and the push queue lets go of it too",
          notices(off)[0]["pushed_at"] is not None,
          "or the task would rediscover it every run for an hour")

    # ---------------------------------------------------------------- messages
    writer, recipient = mkuser("writer"), mkuser("recipient")
    match_id = db().execute(
        "INSERT INTO matches (user_a, user_b, status, paired_at)"
        " VALUES (?, ?, 'active', NOW()) RETURNING id", (writer, recipient)
    ).fetchone()["id"]
    db().commit()

    A.notify_new_message(match_id, writer, recipient, "hello there")
    A.notify_new_message(match_id, writer, recipient, "and another")
    got = notices(recipient, "message")
    check("a new message notifies the other person", len(got) == 1, len(got))
    check("a burst of messages is still one notification", len(got) == 1)
    check("the sender is not notified about their own message",
          not notices(writer, "message"))
    check("the message text never leaves the chat",
          "hello there" not in (got[0]["title"] + got[0]["body"]),
          "a lock screen is read by whoever is holding the phone")
    check("the notice points at the conversation",
          got[0]["url"].endswith("/chat/%d" % match_id), got[0]["url"])

    # ------------------------------------------------------------ the pool
    # Someone who searched recently, is not searching now, and would fit.
    waiting_for_news = mkuser("candidate")
    start_search(waiting_for_news)
    db().execute("UPDATE searches SET status = 'cancelled' WHERE user_id = ?",
                 (waiting_for_news,))
    # Someone who is already in the pool: the matcher will pair them, so
    # telling them about a candidate is noise.
    already_looking = mkuser("looking")
    start_search(already_looking)
    # Someone the searcher has blocked.
    blocked = mkuser("blocked")
    start_search(blocked)
    db().execute("UPDATE searches SET status = 'cancelled' WHERE user_id = ?", (blocked,))
    # Someone whose own criteria rule the searcher out.
    picky = mkuser("picky")
    start_search(picky)
    db().execute(
        """UPDATE searches SET status = 'cancelled', use_age = TRUE,
                  age_min = 65, age_max = 80 WHERE user_id = ?""", (picky,))
    db().commit()

    searcher = mkuser("searcher")
    db().execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
                 (searcher, blocked))
    # Building the fixtures started four searches, and each one notified the
    # others -- which is the behaviour under test, so it has to be cleared
    # before the search that is actually being measured.
    db().execute(
        "DELETE FROM notifications WHERE kind = 'pool' AND user_id = ANY(?)",
        ([waiting_for_news, already_looking, blocked, picky],))
    db().commit()
    start_search(searcher)          # save_search() raises the pool notices

    check("a compatible member who is not searching is told",
          len(notices(waiting_for_news, "pool")) == 1)
    check("someone already searching is not", not notices(already_looking, "pool"),
          "they are in the pool; the matcher will pair them")
    check("a blocked member is not", not notices(blocked, "pool"))
    check("someone the search does not fit is not", not notices(picky, "pool"),
          "checked with the same searches_compatible() the matcher uses")
    check("the searcher is not told about their own search",
          not notices(searcher, "pool"))

    pool_notice = notices(waiting_for_news, "pool")[0]
    said = pool_notice["title"] + " " + pool_notice["body"]
    check("nobody is named in a pool notice",
          "searcher" not in said.lower() and str(searcher) not in said, said)

    # A second search moments later must not ping the same person again.
    other_searcher = mkuser("searcher2")
    start_search(other_searcher)
    check("a second search does not ping the same person again",
          len(notices(waiting_for_news, "pool")) == 1,
          "%s minutes" % A.NOTIFY_DEDUPE_MINUTES["pool"])

    # ------------------------------------------------------------ announcements
    before = len(notices(reader, "feature"))
    made = A.announce_feature("Photos reorder now", "Drag a tile.", "/profile/edit")
    check("an announcement reaches active members", made >= 1, made)
    check("...including this one", len(notices(reader, "feature")) == before + 1)
    check("demo members are left out", not notices(demo, "feature"))
    check("suspended accounts are left out", not notices(gone, "feature"))
    check("announcing the same thing twice tells nobody twice",
          A.announce_feature("Photos reorder now", "Drag a tile.", "/profile/edit") == 0)

    mailed_by_default = notices(reader, "feature")[-1]["email_due_at"]
    check("an announcement is not emailed unless asked for",
          mailed_by_default is None)

    # ---------------------------------------------------------------- flushing
    sent_mail = []
    real_send = A.send_email
    A.send_email = lambda to, subject, html: (sent_mail.append((to, subject, html)), True)[1]
    try:
        busy = mkuser("busy")
        A.notify(busy, "reminder", "First thing", dedupe_key="a")
        A.notify(busy, "message", "Second thing", dedupe_key="b")
        read_already = A.notify(busy, "reminder", "Third thing", dedupe_key="c")
        db().execute(
            "UPDATE notifications SET email_due_at = NOW() - INTERVAL '1 minute'"
            " WHERE user_id = ?", (busy,))
        db().execute("UPDATE notifications SET read_at = NOW() WHERE id = ?",
                     (read_already,))
        db().commit()

        A.flush_notification_email()
        mine = [m for m in sent_mail if m[0].startswith("nt_busy")]
        check("three things due become one email", len(mine) == 1, len(mine))
        check("...and it says how many", "2 things" in mine[0][1], mine[0][1])
        # Scoped to this run's rows: the flush is service-wide, so its return
        # count also carries whatever else the database happened to owe.
        check("something already read is never mailed",
              "Third thing" not in mine[0][2] and "First thing" in mine[0][2])
        check("...and its row is left alone rather than marked sent",
              db().execute("SELECT emailed_at FROM notifications WHERE id = ?",
                           (read_already,)).fetchone()["emailed_at"] is None)
        before = len(sent_mail)
        A.flush_notification_email()
        check("mail is not sent twice",
              not [m for m in sent_mail[before:] if m[0].startswith("nt_busy")])
        check("the email offers a way to turn it off",
              "settings" in mine[0][2].lower())
    finally:
        A.send_email = real_send

    # ------------------------------------------------------------------ push
    pushed = []

    def fake_send(sub, payload, priv, subject, **kw):
        pushed.append((sub["endpoint"], payload))
        return 201

    real_push, real_key = webpush_send_backup, key_backup = A.webpush.send, A.VAPID_PRIVATE_KEY
    A.webpush.send = fake_send
    A.VAPID_PRIVATE_KEY = A.VAPID_PRIVATE_KEY or "x" * 43
    A.VAPID_PUBLIC_KEY = A.VAPID_PUBLIC_KEY or "y" * 87
    try:
        phone = mkuser("phone")
        endpoint = "https://push.example.test/" + A.secrets.token_hex(4)
        db().execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
               VALUES (?, ?, 'p', 'a')""", (phone, endpoint))
        db().commit()

        # Counted per endpoint, not per run: an earlier run deliberately
        # leaves a row queued for retry, and the flush below is supposed to
        # pick that up too.
        def mine():
            return [p for p in pushed if p[0] == endpoint]

        A.notify(phone, "message", "Someone wrote", push_now=True)
        check("a message is pushed while it is still happening", len(mine()) == 1)
        check("...and the row records that it went",
              notices(phone, "message")[0]["pushed_at"] is not None)

        A.notify(phone, "pool", "Someone is searching", dedupe_key="pool")
        check("a pool notice is not pushed on the searcher's request",
              len(mine()) == 1, "it waits for the scheduled task")
        check("...and the task picks it up", A.flush_pending_push() >= 1)
        check("...which pushes it", len(mine()) == 2, len(mine()))

        # A subscription the push service has retired must be forgotten, not
        # retried forever.
        def gone_send(sub, payload, priv, subject, **kw):
            raise A.webpush.PushGone("410")

        A.webpush.send = gone_send
        A.notify(phone, "reminder", "Still there?", push_now=True)
        left = db().execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id = ?",
            (phone,)).fetchone()["n"]
        check("a retired subscription is deleted, not retried", left == 0)

        # A transport failure is not the same thing.
        A.webpush.send = fake_send
        db().execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
               VALUES (?, ?, 'p', 'a')""",
            (phone, "https://push.example.test/" + A.secrets.token_hex(4)))
        db().commit()

        def flaky(sub, payload, priv, subject, **kw):
            raise RuntimeError("push service is having a minute")

        A.webpush.send = flaky
        made = A.notify(phone, "message", "Try me", dedupe_key="retry", push_now=True)
        row = db().execute("SELECT * FROM notifications WHERE id = ?", (made,)).fetchone()
        check("a failed push leaves the row for another try",
              row["pushed_at"] is None)
        still = db().execute(
            "SELECT failures FROM push_subscriptions WHERE user_id = ?",
            (phone,)).fetchone()
        check("...and the subscription survives one bad minute",
              still is not None and still["failures"] == 1)
        check("sending a message does not fail when push does",
              made is not None)
    finally:
        A.webpush.send = real_push
        A.VAPID_PRIVATE_KEY = real_key

    # ------------------------------------------------------------- reminders
    stalled = mkuser("stalled")
    db().execute("DELETE FROM photos WHERE user_id = ?", (stalled,))     # cannot search
    finished = mkuser("finished")                                        # complete, no search
    db().commit()

    counts = A.queue_reminders()
    check("someone who still cannot search is reminded",
          len(notices(stalled, "reminder")) == 1, counts)
    check("someone whose profile is ready is not nagged",
          not notices(finished, "reminder"),
          "the gate and the nudge read the same profile_completeness()")
    A.queue_reminders()
    check("a reminder is sent once, not every run",
          len(notices(stalled, "reminder")) == 1)

    # --------------------------------------------------------------- the feed
    watcher = mkuser("watcher")
    A.save_notification_prefs(watcher, {
        "message": {"browser": True}, "pool": {"browser": False},
        "reminder": {"browser": True}, "feature": {"browser": True}})
    A.notify(watcher, "message", "Shown in the tab", dedupe_key="m")
    A.notify(watcher, "pool", "Not shown in the tab", dedupe_key="p")

    fresh = db().execute(
        """SELECT kind FROM notifications
           WHERE user_id = ? AND seen_at IS NULL""", (watcher,)).fetchall()
    kinds = {r["kind"] for r in fresh}
    check("both are recorded whatever the channels say", kinds == {"message", "pool"})
    check("the inbox is not a channel -- it holds what nobody was told",
          len(notices(watcher)) == 2)

    # ------------------------------------------------------------- deletion
    leaving = mkuser("leaving")
    A.notify(leaving, "reminder", "Goodbye")
    db().execute(
        """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
           VALUES (?, ?, 'p', 'a')""",
        (leaving, "https://push.example.test/" + A.secrets.token_hex(4)))
    db().execute(
        """UPDATE users SET status = 'pending_deletion',
           deletion_requested_at = NOW() - (? * INTERVAL '1 day') WHERE id = ?""",
        (A.DELETION_GRACE_DAYS + 1, leaving))
    db().commit()
    A.purge_due_deletions()
    check("deletion takes the notifications with it", not notices(leaving))
    check("...and the device it was pushing to",
          not db().execute("SELECT 1 AS h FROM push_subscriptions WHERE user_id = ?",
                           (leaving,)).fetchall())

    # ------------------------------------------------------ the wire format
    # The one hand-written protocol in the app. Encrypted here, decrypted the
    # way a browser would: if these two ever disagree, every push in
    # production is an undecryptable blob and nothing else would say so.
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    browser = ec.generate_private_key(ec.SECP256R1())
    browser_public = A.webpush.b64e(A.webpush._public_bytes(browser.public_key()))
    auth_secret = A.webpush.b64e(os.urandom(16))
    plain = b'{"title":"Someone wrote","url":"/chats"}'

    blob = A.webpush.encrypt(plain, browser_public, auth_secret)
    salt, key_length = blob[:16], blob[20]
    server_public, sealed = blob[21:21 + key_length], blob[21 + key_length:]
    shared = browser.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public))
    ikm = A.webpush._hkdf(
        A.webpush.b64d(auth_secret), shared,
        b"WebPush: info\x00" + A.webpush.b64d(browser_public) + server_public, 32)
    opened = AESGCM(
        A.webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    ).decrypt(
        A.webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12), sealed, None)

    check("a browser can decrypt what we encrypt", opened == plain + b"\x02",
          "RFC 8291, single record, 0x02 delimiter")
    check("the ephemeral key is different every message",
          A.webpush.encrypt(plain, browser_public, auth_secret)[21:21 + 65]
          != server_public)

    private, public = A.webpush.generate_keys()
    check("a minted VAPID pair matches itself",
          A.webpush.public_key_for(private) == public)
    header = A.webpush._vapid_header("https://fcm.googleapis.test/send/abc",
                                     private, "mailto:a@b.test")
    token = header.split("t=")[1].split(",")[0]
    claims = A.json.loads(A.webpush.b64d(token.split(".")[1]))
    check("the JWT is scoped to the push service's origin, not the endpoint",
          claims["aud"] == "https://fcm.googleapis.test", claims["aud"])
    check("the signature is a raw r||s pair, as ES256 requires",
          len(A.webpush.b64d(token.split(".")[2])) == 64)

print()
bad = [n for n, ok in RESULTS if not ok]
print("%d/%d checks passed" % (len(RESULTS) - len(bad), len(RESULTS)))
for n in bad:
    print("  failed: " + n)
raise SystemExit(1 if bad else 0)
