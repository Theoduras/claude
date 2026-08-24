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
import re

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
        db.execute("DELETE FROM design_rules")
        db.execute("DELETE FROM app_settings WHERE key = 'design_mode'")
        db.execute("DELETE FROM app_settings WHERE key = 'design_custom_css'")
        db.commit()
        A.design_overrides(force=True)


def sheet():
    """The stylesheet as it would be served right now."""
    with app.test_request_context():
        A.design_overrides(force=True)
        return dict(A._render_stylesheet())


def set_mode(mode):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """INSERT INTO app_settings (key, value) VALUES ('design_mode', ?)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (mode,))
        db.commit()
        # Inside the context: the refresh reads through get_db(), and outside
        # one it raises into design_overrides()'s deliberate swallow -- so the
        # cache silently keeps the old mode.
        A.design_overrides(force=True)


def store(name, value, mode="dark"):
    with app.test_request_context():
        db = A.get_db()
        db.execute(
            """
            INSERT INTO design_tokens (mode, name, value) VALUES (?, ?, ?)
            ON CONFLICT (mode, name) DO UPDATE SET value = EXCLUDED.value
            """,
            (mode, name, value),
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

# The payload has to be something the shipped stylesheet does not already
# contain. "display: none" was the first attempt and is worthless: the file
# has a `::-webkit-details-marker { display: none; }` rule of its own, so
# that assertion fails against a correct route and would pass against a
# broken one given a different payload.
INJECTION = "red; } body { outline: 9px solid #ff00ff"
assert INJECTION.split("}")[1] not in sheet()["body"], "pick a payload the sheet lacks"
client.post("/admin/design", data={"csrf_token": token, "--text": INJECTION})
after = sheet()["body"]
check("an unsafe value is refused by the route, not only the helper",
      "#ff00ff" not in after and "outline: 9px" not in after)
with app.test_request_context():
    stored = A.get_db().execute(
        "SELECT value FROM design_tokens WHERE name = '--text'").fetchone()
check("and nothing was written for that token", stored is None, stored)

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
    db.execute("DELETE FROM design_palettes WHERE name LIKE ?", ("probe-%",))
    db.commit()

store("--violet", "#010203", mode="light")
client.post("/admin/design",
            data={"csrf_token": token, "action": "save_as",
                  "palette_name": "probe-one"})
with app.test_request_context():
    saved = A.get_db().execute(
        "SELECT id, tokens FROM design_palettes WHERE name = 'probe-one'").fetchone()
check("a palette stores what was live, and which world it was for",
      saved is not None
      and saved["tokens"].get("mode") == "light"
      and saved["tokens"].get("tokens", {}).get("--violet") == "#010203",
      saved and saved["tokens"])

# Changing the live design must not change the saved palette.
store("--violet", "#0A0B0C", mode="light")
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
        (A.json.dumps({"mode": "light",
                       "tokens": {"--violet": INJECTION,
                                  "--not-a-token": "#123456"}}),),
    )
    bad = db.execute(
        "SELECT id FROM design_palettes WHERE name = 'probe-bad'").fetchone()["id"]
    db.commit()
client.post("/admin/design",
            data={"csrf_token": token, "action": "restore", "palette_id": bad})
sheet_now = sheet()["body"]
check("a palette cannot smuggle an unsafe value past the validator",
      "#ff00ff" not in sheet_now and "outline: 9px" not in sheet_now)
check("nor an unknown token", "--not-a-token" not in sheet_now)
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM design_palettes WHERE name LIKE ?", ("probe-%",))
    db.commit()

# --- the two worlds ------------------------------------------------------
clear()
check("the light block was parsed out of the stylesheet",
      len(A.DESIGN_MODE_DEFAULTS.get("light", {})) > 8,
      len(A.DESIGN_MODE_DEFAULTS.get("light", {})))
check("dark and light disagree about the page ground",
      A.DESIGN_MODE_DEFAULTS["light"]["--ink"] != A.DESIGN_DEFAULTS["--ink"])
check("but agree about anything structural, by falling through",
      A._mode_defaults("light")["--radius"] == A.DESIGN_DEFAULTS["--radius"])

check("the site starts in light, which is the shipped design",
      A.design_mode() == "light", A.design_mode())
set_mode("dark")
check("and the switch is honoured", A.design_mode() == "dark")
check("without changing the stylesheet's bytes",
      sheet()["body"] == base["body"],
      "both worlds are always in the sheet; <html> decides which paints")
set_mode("light")

# An override in one world must not leak into the other.
store("--ink", "#111111", mode="dark")
store("--ink", "#EEEEEE", mode="light")
body = sheet()["body"]
check("the dark override lands on :root",
      "\n:root {\n  --ink: #111111;" in body)
check("the light override lands on the light block only",
      '[data-mode="light"] {\n  --ink: #EEEEEE;' in body)
check("and neither is written into the other",
      body.count("#111111") == 1 and body.count("#EEEEEE") == 1)
clear()

# --- a visitor's own light/dark choice ------------------------------------
# The admin's setting is the site's default; /mode/<mode> is one person
# overriding it for their own eyes. Each "it is honoured" is paired with the
# thing it must not do.
set_mode("light")
visitor = app.test_client()

def mode_of(c, path="/faq"):
    """The data-mode actually painted on <html> for this client."""
    html = c.get(path).get_data(as_text=True)
    match = re.search(r'<html[^>]*data-mode="(\w+)"', html)
    return match.group(1) if match else None

check("a visitor with no choice gets the site default",
      mode_of(visitor) == "light", mode_of(visitor))

resp = visitor.get("/mode/dark?next=/faq")
check("choosing dark redirects back to the page you were reading",
      resp.status_code == 302 and resp.headers["Location"].endswith("/faq"),
      resp.headers.get("Location"))
check("...and the visitor's own pages paint dark",
      mode_of(visitor) == "dark", mode_of(visitor))
check("...without touching the site default",
      A.design_overrides(force=True).get("mode") == "light")
check("...so another visitor still sees light",
      mode_of(app.test_client()) == "light")

visitor.get("/mode/sepia?next=/faq")
check("a mode the stylesheet has no block for is refused",
      mode_of(visitor) == "dark", mode_of(visitor))

check("the switch cannot be used as an open redirect",
      visitor.get("/mode/light?next=//evil.example")
             .headers["Location"].endswith("/"))

visitor.get("/mode/light?next=/faq")
check("and switching back is one link",
      mode_of(visitor) == "light", mode_of(visitor))

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

# --- the inspector's element rules ----------------------------------------
# The palette answers "what colour is a button"; these answer "make this one
# thing different". Each check below is paired with its refusal, because a
# rules table that accepts everything passes any test that only asks whether
# a rule was applied -- and this one writes a *selector*, which is the part
# that can end the declaration block and open one of its own.
clear()


def rule(selector, prop, value, state="base", mode="light"):
    page = client.get("/admin/design").get_data(as_text=True)
    tok = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    return client.post(
        "/admin/design/rules",
        json={"selector": selector, "prop": prop, "value": value,
              "state": state, "mode": mode},
        headers={"X-CSRF-Token": tok})


check("no element rules means no element block",
      "elements, set in" not in sheet()["body"])

resp = rule(".btn", "border-radius", "999px")
check("a structural rule is accepted", resp.status_code == 200, resp.status_code)
body = sheet()["body"]
check("and reaches the stylesheet unscoped, so it paints in both worlds",
      "\n.btn {\n  border-radius: 999px;\n}" in body)

resp = rule(".btn", "background-color", "#ff0000", mode="light")
check("a colour rule is accepted", resp.status_code == 200, resp.status_code)
body = sheet()["body"]
check("and is filed under the mode it was chosen in",
      ':root[data-mode="light"] .btn {\n  background-color: #ff0000;\n}' in body)
check("so it cannot follow the reader into the other world",
      ':root:not([data-mode="light"]) .btn {\n  background-color: #ff0000;' not in body)

rule(".btn", "transform", "translateY(-2px)", state="hover")
check("a hover rule lands on :hover", ".btn:hover {\n  transform: translateY(-2px);\n}"
      in sheet()["body"])

# The selector is the dangerous field: a value that breaks out only wrecks
# its own block, while a selector that breaks out opens a rule over the
# whole site.
for evil in (".btn { } body { display: none",
             ".btn}", "@import url(//evil)", ".btn /*", "*", ".x:has(.y)",
             '.x[onclick="x"]', '.x[style="y"]'):
    resp = rule(evil, "border-radius", "4px")
    check(f"selector {evil[:22]!r} is refused", resp.status_code == 400, resp.status_code)
check("and none of them reached the sheet",
      "display: none\n" not in sheet()["body"]
      and "@import" not in sheet()["body"])

resp = rule(".btn", "position", "fixed")
check("a property the panels do not offer is refused",
      resp.status_code == 400, resp.status_code)
resp = rule(".btn", "border-radius", "4px; } body { display: none")
check("an unsafe value is refused here too", resp.status_code == 400, resp.status_code)
check("and neither reached the sheet",
      "position: fixed" not in sheet()["body"].split("elements, set in")[-1])

before = sheet()["digest"]
rule(".btn", "border-radius", "")
check("clearing a rule is a delete, not an empty declaration",
      "border-radius: 999px" not in sheet()["body"].split("elements, set in")[-1])
check("and moves the digest, so cached pages refetch",
      sheet()["digest"] != before)

# A member must not be able to write CSS for everybody -- and with a CSRF
# token their own session accepts, so this tests the authorisation rather
# than stopping at the check every POST already gets. The earlier probe was
# deleted, so this needs one of its own.
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE username = 'rules-probe'")
    rules_probe = db.insert_returning_id(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("rules-probe", "x"))
    db.commit()
rules_client = app.test_client()
login_as(rules_client, rules_probe)
# The meta tag rather than a form field: base.html renders it on every page,
# so this does not depend on the member happening to have a form in front of
# them -- which, behind the verification gate, they may not.
member_page = rules_client.get("/", follow_redirects=True).get_data(as_text=True)
member_token = member_page.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
resp = rules_client.post("/admin/design/rules",
                         json={"selector": ".btn", "prop": "color",
                               "value": "#ff00aa", "state": "base"},
                         headers={"X-CSRF-Token": member_token})
check("a member cannot write an element rule",
      resp.status_code in (302, 303, 403, 404), resp.status_code)
check("and nothing they sent reached the sheet", "#ff00aa" not in sheet()["body"])
with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE username = 'rules-probe'")
    db.commit()

# --- the custom CSS block -------------------------------------------------
page = client.get("/admin/design").get_data(as_text=True)
token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]

resp = client.post("/admin/design/custom",
                   data={"csrf_token": token, "css": ".zzz { color: #abcdef; }"})
check("custom CSS is accepted", resp.status_code in (302, 303), resp.status_code)
check("and is appended last, so it wins",
      sheet()["body"].rstrip().endswith(".zzz { color: #abcdef; }"))

for bad, why in ((".x { color: red;", "an unbalanced brace"),
                 ("/* never closed", "an unclosed comment"),
                 ("@import url(//evil);", "an @import"),
                 ("</style><script>alert(1)</script>", "a tag break-out")):
    client.post("/admin/design/custom", data={"csrf_token": token, "css": bad})
    check(f"custom CSS with {why} is refused", bad not in sheet()["body"])

client.post("/admin/design/custom", data={"csrf_token": token, "css": ""})
check("clearing custom CSS empties it", "#abcdef" not in sheet()["body"])

# --- reset ----------------------------------------------------------------
rule(".btn", "border-radius", "999px")
check("a rule is there to clear", "elements, set in" in sheet()["body"])
resp = client.post("/admin/design/rules/reset", data={"csrf_token": token})
check("reset drops every element rule", "elements, set in" not in sheet()["body"])
store("--ink", "#0A0A0A")
check("and leaves the palette alone", "--ink: #0A0A0A;" in sheet()["body"])

clear()
print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all design checks passed")
