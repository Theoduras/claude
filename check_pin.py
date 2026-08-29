"""Verify every profile and search lands in the one city Velvt operates in.

    python check_pin.py

The location controls are gone from the UI, which is the easy half. The half
that matters is that the server does not trust a posted location either: the
field is not rendered, so anything arriving under that name is a stale draft
or a hand-rolled POST, and honouring it would put a profile in a city where
nobody can match it.

Set SINGLE_CITY to None to go multi-city and these checks skip themselves.
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


if not A.SINGLE_CITY:
    print("SINGLE_CITY is None — multi-city flow, nothing to pin.")
    raise SystemExit(0)

CITY = A.SINGLE_CITY
LAT, LNG = A.CITY_COORDS[CITY.lower()]
ELSEWHERE = ["Berlin", "Vienna", "Zurich", "", "Not A Place"]

check("the pinned city has real coordinates", (LAT, LNG) != (None, None), f"{CITY} {LAT},{LNG}")

# pinned_place() is the one gate every entry point goes through.
for posted in ELSEWHERE:
    loc, lat, lng = A.pinned_place(posted, 52.52, 13.405)
    check(f"pinned_place ignores {posted!r}", (loc, lat, lng) == (CITY, LAT, LNG), f"{loc} {lat},{lng}")


def csrf_from(client, path):
    """A token minted for this client's *current* session.

    Signing in rotates the session (session fixation defence), so a token
    taken before login is correctly rejected afterwards -- it has to be
    re-read from a page served to the signed-in session.
    """
    page = client.get(path).get_data(as_text=True)
    return page.split('name="csrf_token" value="')[1].split('"')[0]


def signed_in_client():
    """A member with a complete-enough profile to reach the search screens."""
    with app.test_request_context():
        db = A.get_db()
        name = f"pin_{uuid.uuid4().hex[:8]}"
        uid = db.insert_returning_id(
            "INSERT INTO users (username, email, password_hash, is_bot, status, "
            "match_intro_seen_at) VALUES (?, ?, ?, FALSE, 'active', NOW())",
            (name, f"{name}@example.test",
             A.generate_password_hash("pinpin12345")))
        db.execute(
            """INSERT INTO profiles (user_id, name, age, gender, seeking, location)
               VALUES (?, 'Pin', 30, 'Woman', 'Everyone', 'Berlin')""", (uid,))
        db.execute("INSERT INTO photos (user_id, data, mime, is_primary) "
                   "VALUES (?, ?, 'image/png', TRUE)", (uid, b"\x89PNG\r\n\x1a\n" + b"0" * 32))
        db.commit()
    client = app.test_client()
    client.post("/login", data={"email": f"{name}@example.test", "password": "pinpin12345",
                                "csrf_token": csrf_from(client, "/login")})
    return client, uid


client, uid = signed_in_client()
token = csrf_from(client, "/settings")


def stored_profile_location():
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT location FROM profiles WHERE user_id = ?", (uid,)).fetchone()["location"]


def stored_search():
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT location, lat, lng FROM searches WHERE user_id = ?", (uid,)).fetchone()


check("a profile seeded elsewhere starts elsewhere", stored_profile_location() == "Berlin",
      stored_profile_location())

# 1. the member profile form
client.post("/profile/edit", data={
    "csrf_token": token, "name": "Pin", "age": "30", "gender": "Woman",
    "seeking": "Everyone", "location": "Berlin"})
check("the profile form stores the pinned city", stored_profile_location() == CITY,
      stored_profile_location())

# 2. screen 1 of the search wizard
client.post("/search", data={
    "csrf_token": token, "relationship_type": "Friendship", "seeking": "Everyone",
    "age_min": "18", "age_max": "60", "location": "Vienna",
    "location_lat": "48.21", "location_lng": "16.37", "radius_km": "500"})
row = stored_search()
check("the wizard stores the pinned city",
      row is not None and (row["location"], row["lat"], row["lng"]) == (CITY, LAT, LNG), dict(row) if row else None)

# 3. the criteria screen
client.post("/search/criteria", data={
    "csrf_token": token, "seeking": "Everyone", "age_min": "18", "age_max": "60",
    "location": "Zurich", "location_lat": "47.37", "location_lng": "8.54",
    "radius_km": "500", "use_gender": "1", "use_age": "1"})
row = stored_search()
check("the criteria screen stores the pinned city",
      (row["location"], row["lat"], row["lng"]) == (CITY, LAT, LNG), dict(row))

# 4. the preview must count against the place the save will use
# A 1km radius around Berlin would exclude the entire (Maastricht) pool if the
# posted city were honoured; pinned, the radius is around Maastricht instead and
# the preview counts the same people the save would.
r = client.post("/search/preview", data={
    "csrf_token": token, "relationship_type": "Friendship", "seeking": "Everyone",
    "age_min": "18", "age_max": "60", "location": "Berlin",
    "location_lat": "52.52", "location_lng": "13.405", "radius_km": "1"})
check("the preview answers on a foreign city", r.status_code == 200, r.status_code)
payload = r.get_json() or {}
check("the preview does not echo the posted city",
      "Berlin" not in str(payload), str(payload)[:120])

# 5. the UI stops asking
page = client.get("/profile/edit").get_data(as_text=True)
check("the profile form renders no location input",
      'name="location"' not in page and CITY in page)
# ?new=1 because /search now returns a running search to the waiting screen
# rather than re-asking the wizard's questions -- and the wizard is what this
# is about.
page = client.get("/search?new=1").get_data(as_text=True)
check("the wizard has no location step", 'name="location"' not in page)
steps = page.count('class="wiz-step"')
check("...and renumbered itself from six steps to five", steps == 5, f"{steps} steps")
page = client.get("/search/criteria").get_data(as_text=True)
check("the criteria screen has no distance switch", 'name="use_distance"' not in page)

# 6. and the waiting screen does not describe everyone by their city
with app.test_request_context():
    row = A.get_db().execute("SELECT * FROM searches WHERE user_id = ?", (uid,)).fetchone()
    chips = A.search_chips(dict(row))
check("no city chip on the waiting screen",
      not any(c["key"] == "location" for c in chips), [c["key"] for c in chips])

with app.test_request_context():
    db = A.get_db()
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()

print()
if failures:
    print(f"{len(failures)} check(s) failed: " + ", ".join(failures))
    raise SystemExit(1)
print("all pin checks passed")
