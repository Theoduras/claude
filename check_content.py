"""Verify the admin can rewrite words and re-point icons, and nothing else.

    python check_content.py

Both screens follow the design editor's rule: overrides only, so an empty
table is exactly what shipped, and a string or a glyph changed in the source
still reaches the site unless someone deliberately overrode that one. The
checks pair "the override is honoured" with "the shipped value is what you get
without one", because a content system that always answers from the database
has quietly forked the product from its own source files.
"""

import os

os.environ.setdefault("ALLOW_BOT_MATCHES", "0")

import app as A
from app import app
from translations import TRANSLATIONS, DEFAULT_LANGUAGE

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")


def clear():
    with app.test_request_context():
        db = A.get_db()
        db.execute("DELETE FROM copy_overrides")
        db.execute("DELETE FROM icon_slots")
        db.commit()
    A.design_overrides(force=True)


def store_copy(lang, key, text):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """INSERT INTO copy_overrides (lang, key, text) VALUES (?, ?, ?)
               ON CONFLICT (lang, key) DO UPDATE SET text = EXCLUDED.text""",
            (lang, key, text))
        db.commit()
    A.design_overrides(force=True)


def store_icon(slot, glyph):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """INSERT INTO icon_slots (slot, glyph) VALUES (?, ?)
               ON CONFLICT (slot) DO UPDATE SET glyph = EXCLUDED.glyph""",
            (slot, glyph))
        db.commit()
    A.design_overrides(force=True)


clear()

# --- words ----------------------------------------------------------------
key = "nav.chats"
shipped_en = TRANSLATIONS["en"][key]
shipped_nl = TRANSLATIONS["nl"][key]

with app.test_request_context():
    check("with no override, say() is translate()",
          A.say("en", key) == shipped_en and A.say("nl", key) == shipped_nl)

store_copy("en", key, "Conversations")
with app.test_request_context():
    check("an override is honoured", A.say("en", key) == "Conversations")
    check("and does not leak into the other language",
          A.say("nl", key) == shipped_nl, A.say("nl", key))

# A key with a placeholder: the guard matters most on admin-written text.
with app.test_request_context():
    check("placeholders still fill in",
          "{n}" not in A.say("en", "pulse.live_many", n=4),
          A.say("en", "pulse.live_many", n=4))
store_copy("en", "pulse.live_many", "{nope} people are here")
with app.test_request_context():
    got = A.say("en", "pulse.live_many", n=4)
    check("a typo'd placeholder degrades instead of 500ing",
          got == "{nope} people are here", got)

# An unknown key stays unknown: an override cannot invent copy the app never
# asks for, and cannot be used to reach a key that is not in the catalogue.
store_copy("en", "not.a.real.key", "smuggled")
with app.test_request_context():
    check("an override for an unknown key is inert on real lookups",
          A.say("en", key) == "Conversations")

clear()
with app.test_request_context():
    check("clearing puts the shipped wording back", A.say("en", key) == shipped_en)

# --- icons ----------------------------------------------------------------
names, slots = A._icon_registry()
check("the glyph registry parsed", len(names) > 20, len(names))
check("the slot map parsed", len(slots) > 20, len(slots))
check("every shipped slot names a real glyph or nothing",
      all((not g) or g in names for g in slots.values()),
      [s for s, g in slots.items() if g and g not in names])

with app.test_request_context():
    check("with no override the slot keeps its glyph",
          A.icon_slot_override("tab.search") is None)

store_icon("tab.search", "heart")
with app.test_request_context():
    check("an override re-points the slot",
          A.icon_slot_override("tab.search") == "heart")

# The macro is what actually draws, so read it rather than the helper.
client = app.test_client()
page = client.get("/login").get_data(as_text=True)
check("a page still renders with an icon override", "<svg" in page)

clear()

# --- the routes -----------------------------------------------------------
for path in ("/admin/copy", "/admin/icons"):
    code = client.get(path).status_code
    check(f"{path} is not reachable signed out", code in (302, 303), code)

with app.test_request_context():
    admin = A.get_db().execute(
        "SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1").fetchone()
admin_id = admin["id"] if admin else None


def login_as(client, uid):
    with app.test_request_context():
        tok = A.secrets.token_urlsafe(32)
        db = A.get_db()
        db.execute("""INSERT INTO sessions (user_id, token_hash, expires_at)
                      VALUES (?, ?, NOW() + INTERVAL '1 day')""",
                   (uid, A.hash_token(tok)))
        db.commit()
    with client.session_transaction() as s:
        s["sid"] = tok


login_as(client, admin_id)
check("an admin can open the words screen",
      client.get("/admin/copy").status_code == 200)
check("and the icons screen",
      client.get("/admin/icons").status_code == 200)

page = client.get("/admin/copy").get_data(as_text=True)
token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]

client.post("/admin/copy",
            data={"csrf_token": token, "lang": "en",
                  "copy:" + key: "Threads"})
with app.test_request_context():
    check("saving through the form works", A.say("en", key) == "Threads")

client.post("/admin/copy",
            data={"csrf_token": token, "lang": "en", "copy:" + key: shipped_en})
with app.test_request_context():
    check("re-typing the shipped wording deletes the override rather than "
          "pinning it", A.say("en", key) == shipped_en)
with app.test_request_context():
    row = A.get_db().execute(
        "SELECT 1 AS hit FROM copy_overrides WHERE lang='en' AND key=?",
        (key,)).fetchone()
    check("and the row really is gone", row is None)

client.post("/admin/icons", data={"csrf_token": token, "slot:tab.search": "not-a-glyph"})
with app.test_request_context():
    check("a slot cannot be pointed at a glyph that does not exist",
          A.icon_slot_override("tab.search") is None)

client.post("/admin/icons", data={"csrf_token": token, "slot:tab.search": "heart"})
with app.test_request_context():
    check("but can be pointed at one that does",
          A.icon_slot_override("tab.search") == "heart")

clear()
print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all content checks passed")
