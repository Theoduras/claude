"""Verify the app speaks every language it offers, and that it stays one app.

    python check_i18n.py

Two different risks, and the second is the dangerous one:

1. Cosmetic — a key with no Dutch, a placeholder that survives in one
   language and not the other, a template asking for a key nobody defined.
   translate() falls back rather than raising, so none of these is a crash;
   they are a page that quietly says the wrong thing.

2. Structural — the profile option lists (gender, seeking, relationship
   type, body type...) are stored in the database and compared as strings by
   searches_compatible() and SEEKING_MATCHES. Translating a *stored value*
   would silently stop a Dutch member matching an English one, and nothing
   would look broken. Only the labels are translated. That is what the
   pairing checks at the bottom exist to hold.
"""

import os
import re

os.environ.setdefault("ALLOW_BOT_MATCHES", "0")

import app as A
from app import app
from translations import (
    LANGUAGE_CODES,
    OPTION_LABELS,
    TRANSLATIONS,
    missing_keys,
    normalize_language,
)

failures = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")


# --- 1. the catalogue ------------------------------------------------------
for code in LANGUAGE_CODES:
    check(f"{code} has every key", not missing_keys(code), missing_keys(code)[:5])

extra = {c: sorted(set(TRANSLATIONS[c]) - set(TRANSLATIONS["en"])) for c in LANGUAGE_CODES}
check("no language defines a key English does not",
      not any(extra.values()), {c: v for c, v in extra.items() if v})

# A placeholder that exists in one language and not another formats to a
# string with a literal {slot} in it, or drops the value silently.
slot_gaps = []
for key, en_text in TRANSLATIONS["en"].items():
    want = set(re.findall(r"\{(\w+)\}", en_text))
    for code in LANGUAGE_CODES:
        got = set(re.findall(r"\{(\w+)\}", TRANSLATIONS[code].get(key, "")))
        if want != got:
            slot_gaps.append(f"{key}/{code}")
check("placeholders match across languages", not slot_gaps, slot_gaps[:5])

# --- 2. what the code actually asks for ------------------------------------
used = set()
for root in ("templates", "."):
    for name in os.listdir(root):
        if not name.endswith((".html", ".py")) or name == "translations.py":
            continue
        text = open(os.path.join(root, name), encoding="utf-8").read()
        used |= set(re.findall(r'\bt\(\s*["\']([a-z_]+\.[a-z_0-9]+)["\']', text))
undefined = sorted(k for k in used if k not in TRANSLATIONS["en"])
check("every key the code asks for exists", not undefined, undefined[:5])

# --- 3. the switcher -------------------------------------------------------
check("a regional code maps to the language", normalize_language("nl-BE") == "nl")
check("an unknown code is refused", normalize_language("zz") is None)

client = app.test_client()
for target, expect in [("/chats", "/chats"),
                       ("//evil.example/x", "/"),
                       ("https://evil.example/x", "/"),
                       ("javascript:alert(1)", "/")]:
    r = client.get(f"/lang/nl?next={target}")
    check(f"redirect target {target!r} is same-site",
          r.headers.get("Location") == expect, r.headers.get("Location"))

# --- 4. the invariant that matters -----------------------------------------
# Stored option values must be canonical English whatever the reader speaks,
# or the two halves of a cross-language pair stop matching.
translated_values = set()
for code, labels in OPTION_LABELS.items():
    translated_values |= set(labels.values()) - set(labels)
overlap = translated_values & set(A.GENDERS + A.SEEKING_OPTIONS + A.RELATIONSHIP_TYPES)
check("no translated label collides with a stored value", not overlap, sorted(overlap)[:5])

with app.test_request_context("/"):
    from flask import session
    session["lang"] = "nl"
    dutch = A.opt_label_for("Men")
    session["lang"] = "en"
    english = A.opt_label_for("Men")
check("a stored value reads translated", dutch != "Men", dutch)
check("...and untranslated in English", english == "Men", english)

with app.app_context():
    db = A.get_db()
    for name in ("i18n_a", "i18n_b"):
        db.execute("DELETE FROM users WHERE username = ?", (name,))
    db.commit()
    ids = []
    for name, gender, seeking in (("i18n_a", "Woman", "Men"), ("i18n_b", "Man", "Women")):
        uid = db.insert_returning_id(
            "INSERT INTO users (username, password_hash, is_bot, status) "
            "VALUES (?, 'x', FALSE, 'active')", (name,))
        db.execute("INSERT INTO profiles (user_id, name, age, gender, seeking) "
                   "VALUES (?, ?, 30, ?, ?)", (uid, name, gender, seeking))
        db.execute(
            """INSERT INTO searches
                 (user_id, seeking, age_min, age_max, relationship_type, status,
                  use_gender, use_age, use_relationship, use_distance, use_physical,
                  created_at, last_seen)
               VALUES (?, ?, 18, 60, '', 'waiting', TRUE, FALSE, FALSE, FALSE, FALSE,
                       NOW() - INTERVAL '90 seconds', NOW())""",
            (uid, seeking))
        ids.append(uid)
    db.commit()
    a, b = ids

    stored = [r["seeking"] for r in db.execute(
        "SELECT seeking FROM searches WHERE user_id IN (?, ?) ORDER BY user_id", (a, b))]
    check("stored values are canonical English", stored == ["Men", "Women"], stored)
    check("a Dutch reader and an English reader still pair", A.try_pair(a) is not None)

    db.execute("DELETE FROM users WHERE id IN (?, ?)", (a, b))
    db.commit()

print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all i18n checks passed")
