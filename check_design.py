"""Verify the admin design editor changes the real stylesheet, safely.

    python check_design.py

The editor writes into the sheet every visitor downloads, so the two things
worth holding are that a change *arrives* -- new bytes, new digest, so a
browser holding a year-long cached copy fetches the new one -- and that it
cannot arrive as anything but a token value.

Every "this is applied" check is paired with a "this is refused" control. A
design editor that accepts everything passes any test that only asks whether
a saved colour shows up.
"""

import os

os.environ.setdefault("ALLOW_BOT_MATCHES", "0")

import app as A
from app import app

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")


def clear():
    with app.test_request_context():
        db = A.get_db()
        db.execute("DELETE FROM design_tokens")
        db.commit()
    A.design_overrides(force=True)


def sheet():
    """The stylesheet as it would be served right now."""
    with app.test_request_context():
        A.design_overrides(force=True)
        return dict(A._render_stylesheet())


def store(name, value):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """
            INSERT INTO design_tokens (name, value) VALUES (?, ?)
            ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value
            """,
            (name, value),
        )
        db.commit()
    A.design_overrides(force=True)


clear()

# --- the tokens are read from the stylesheet, not restated ----------------
check("the :root block parsed", len(A.DESIGN_DEFAULTS) > 10, len(A.DESIGN_DEFAULTS))
check("--ink is a known token with the file's own default",
      A.DESIGN_DEFAULTS.get("--ink") == "#0B0713", A.DESIGN_DEFAULTS.get("--ink"))

offered = {name for _g, tokens in A.design_editable() for name, *_ in tokens}
check("every offered token exists in the stylesheet",
      offered <= set(A.DESIGN_DEFAULTS), sorted(offered - set(A.DESIGN_DEFAULTS)))
check("the height curve is not offered for editing",
      not (offered & A.DESIGN_LOCKED), sorted(offered & A.DESIGN_LOCKED))

# --- an empty table is the shipped design --------------------------------
base = sheet()
check("no overrides means no override block",
      "set in /admin/design" not in base["body"])

# --- a stored token reaches the sheet, and moves the digest ---------------
store("--ink", "#123456")
after = sheet()
check("the override is in the served CSS", "--ink: #123456;" in after["body"])
check("the file's own value is still visible above it",
      "#0B0713" in after["body"])
check("the digest changed, so a cached page refetches",
      after["digest"] != base["digest"], f"{base['digest']} -> {after['digest']}")

# --- and removing it puts the sheet back byte for byte -------------------
clear()
restored = sheet()
check("clearing the table restores the original bytes",
      restored["body"] == base["body"] and restored["digest"] == base["digest"])

# --- a token the stylesheet no longer defines is ignored ------------------
store("--not-a-token", "#ff0000")
check("an unknown token is never emitted",
      "--not-a-token" not in sheet()["body"])
clear()

# --- the value validator --------------------------------------------------
for value in ["#FF0000", "rgba(1, 2, 3, .5)", "clamp(1rem, 2vw, 3rem)", "18px"]:
    check(f"accepts {value!r}", A.design_value_ok(value))

for value in ["red; } body { display: none",
              "red } .btn { opacity: 0 ",
              "url(x) /* comment */",
              "@import url(http://evil.example)",
              "<script>",
              "",
              "x" * (A.DESIGN_VALUE_MAX + 1)]:
    check(f"refuses {value[:28]!r}", not A.design_value_ok(value))

# --- and the route enforces it, not just the helper -----------------------
with app.test_request_context():
    db = A.get_db()
    admin = db.execute(
        "SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1"
    ).fetchone()
admin_id = admin["id"] if admin else None

client = app.test_client()
check("there is an admin account to test the route with", admin_id is not None)

resp = client.get("/admin/design")
check("the editor is not reachable signed out",
      resp.status_code in (302, 303), resp.status_code)


def login_as(client, uid):
    """Attach a real session row, the way check_auth.py does."""
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
check("an admin can open the editor", client.get("/admin/design").status_code == 200)

resp = client.post("/admin/design", data={"--ink": "#0A0A0A"})
check("a POST without a CSRF token is refused", resp.status_code == 400, resp.status_code)
check("and nothing was written", "--ink: #0A0A0A;" not in sheet()["body"])

page = client.get("/admin/design").get_data(as_text=True)
token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]

resp = client.post("/admin/design",
                   data={"csrf_token": token, "--ink": "#0A0A0A"})
check("a valid save is accepted", resp.status_code in (302, 303), resp.status_code)
check("and reaches the stylesheet", "--ink: #0A0A0A;" in sheet()["body"])

resp = client.post("/admin/design",
                   data={"csrf_token": token, "--text": "red; } body { display: none"})
check("an unsafe value is refused by the route, not only the helper",
      "display: none" not in sheet()["body"])

resp = client.post("/admin/design",
                   data={"csrf_token": token, "action": "reset"})
check("reset empties the overrides", sheet()["body"] == base["body"])

# A member is not an admin, whatever the nav happens to render.
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE username = 'design-probe'")
    probe = db.insert_returning_id(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("design-probe", "x"),
    )
    db.commit()

member_client = app.test_client()
login_as(member_client, probe)
check("a signed-in member cannot open the editor",
      member_client.get("/admin/design").status_code in (302, 303))

member_client.post("/admin/design", data={"csrf_token": token, "--ink": "#BADBAD"})
check("nor save through it", "--ink: #BADBAD;" not in sheet()["body"])

with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE username = 'design-probe'")
    db.commit()

# --- saved palettes -------------------------------------------------------
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM design_palettes WHERE name LIKE 'probe-%'")
    db.commit()

store("--violet", "#010203")
client.post("/admin/design",
            data={"csrf_token": token, "action": "save_as",
                  "palette_name": "probe-one"})
with app.test_request_context():
    saved = A.get_db().execute(
        "SELECT id, tokens FROM design_palettes WHERE name = 'probe-one'").fetchone()
check("a palette stores what was live", saved is not None
      and saved["tokens"].get("--violet") == "#010203", saved and saved["tokens"])

# Changing the live design must not change the saved palette.
store("--violet", "#0A0B0C")
client.post("/admin/design",
            data={"csrf_token": token, "action": "restore",
                  "palette_id": saved["id"]})
check("restoring puts the palette's value back",
      "--violet: #010203;" in sheet()["body"])
check("and does not keep what was live alongside it",
      "#0A0B0C" not in sheet()["body"])

client.post("/admin/design",
            data={"csrf_token": token, "action": "delete",
                  "palette_id": saved["id"]})
with app.test_request_context():
    gone = A.get_db().execute(
        "SELECT 1 AS hit FROM design_palettes WHERE name = 'probe-one'").fetchone()
check("a deleted palette is gone", gone is None)

resp = client.post("/admin/design",
                   data={"csrf_token": token, "action": "restore",
                         "palette_id": "not-a-number"})
check("a non-numeric palette id is handled, not a 500",
      resp.status_code in (302, 303), resp.status_code)

# A palette carrying a value the validator refuses must not restore it.
with app.test_request_context():
    db = A.get_db()
    db.execute(
        "INSERT INTO design_palettes (name, tokens) VALUES ('probe-bad', ?)",
        (A.json.dumps({"--violet": "red; } body { display: none",
                       "--not-a-token": "#123456"}),),
    )
    bad = db.execute(
        "SELECT id FROM design_palettes WHERE name = 'probe-bad'").fetchone()["id"]
    db.commit()
client.post("/admin/design",
            data={"csrf_token": token, "action": "restore", "palette_id": bad})
sheet_now = sheet()["body"]
check("a palette cannot smuggle an unsafe value past the validator",
      "display: none" not in sheet_now)
check("nor an unknown token", "--not-a-token" not in sheet_now)
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM design_palettes WHERE name LIKE 'probe-%'")
    db.commit()

# --- the preview frame can actually frame ---------------------------------
headers = client.get("/faq").headers
check("pages may be framed by this origin",
      headers.get("X-Frame-Options") == "SAMEORIGIN", headers.get("X-Frame-Options"))
check("and the CSP says the same",
      "frame-ancestors 'self'" in headers.get("Content-Security-Policy", ""))

# Every previewable path must render for an admin -- a preview that 302s
# somewhere else is worse than one that is not offered at all.
for group, pages in A.DESIGN_PREVIEW:
    for label, path in pages:
        code = client.get(path).status_code
        check(f"preview {group}/{label} ({path}) renders", code == 200, code)

clear()
print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all design checks passed")
