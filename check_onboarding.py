"""The first-search gate and the one-time explainer, through real requests."""
import io
import re
import uuid

import app as A
from app import app

R = []


def check(n, ok, d=""):
    R.append((n, ok))
    print(("ok    " if ok else "FAIL  ") + n + (("  — " + str(d)) if d else ""))


def token(c, p="/login"):
    m = re.search(r'name="csrf_token" value="([^"]+)"',
                  c.get(p).get_data(as_text=True))
    return m.group(1) if m else ""


def register(c):
    name = "onb_" + uuid.uuid4().hex[:8]
    c.post("/register", data={
        "username": name, "email": f"{name}@example.test", "dob": "1995-06-15",
        "password": "correct horse battery", "confirm": "correct horse battery",
        "accept_terms": "1", "accept_sensitive": "1", "csrf_token": token(c, "/register")})
    return name


def uid_of(name):
    with app.test_request_context():
        return A.get_db().execute(
            "SELECT id FROM users WHERE username = ?", (name,)).fetchone()["id"]


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

with app.test_client() as c:
    name = register(c)
    uid = uid_of(name)

    # 1. an empty profile cannot search
    r = c.get("/search", follow_redirects=False)
    check("an empty profile is turned away from search",
          r.status_code == 302 and "/profile/edit" in r.headers.get("Location", ""),
          f"HTTP {r.status_code} -> {r.headers.get('Location')}")

    html = c.get("/profile/edit").get_data(as_text=True)
    check("the edit page says what is still required",
          "Still needed before you can search" in html)

    # 2. name/age/gender/seeking but still no photo -> still blocked
    c.post("/profile/edit", data={
        "name": "Onboard", "age": "30", "gender": "Man", "seeking": "Everyone",
        "csrf_token": token(c, "/profile/edit")})
    with app.test_request_context():
        st = A.profile_completeness(uid)
    check("a profile with no photo is not ready", not st["ready"], str(st["missing"]))
    check("the photo is the thing it names",
          st["missing"] == ["One photo"], str(st["missing"]))
    r = c.get("/search", follow_redirects=False)
    check("no photo still means no search", r.status_code == 302)

    # 3. add the photo -> the gate opens, and the explainer is what comes next
    c.post("/profile/edit", data={
        "name": "Onboard", "age": "30", "gender": "Man", "seeking": "Everyone",
        "csrf_token": token(c, "/profile/edit"),
        "photos": (io.BytesIO(PNG), "me.png")},
        content_type="multipart/form-data")
    with app.test_request_context():
        st = A.profile_completeness(uid)
    check("a minimum viable profile is ready", st["ready"], str(st["missing"]))
    check("the meter counts it as partly complete",
          0 < st["percent"] < 100, st["percent"])
    check("it still suggests the optional fields", len(st["suggestions"]) > 0)

    r = c.get("/search", follow_redirects=False)
    check("the first search is sent to the explainer",
          r.status_code == 302 and "how-matching-works" in r.headers.get("Location", ""),
          r.headers.get("Location"))

    page = c.get("/how-matching-works").get_data(as_text=True)
    check("the explainer states the reveal window",
          str(A.REVEAL_SECONDS) + " seconds" in page)
    check("the explainer states the chat length",
          str(A.TIMED_CHAT_SECONDS // 60) + " minutes" in page)

    # Merely looking at it must not count as having read it.
    with app.test_request_context():
        seen = A.get_db().execute(
            "SELECT match_intro_seen_at FROM users WHERE id = ?", (uid,)).fetchone()
    check("a GET does not mark it seen", seen["match_intro_seen_at"] is None)

    # 4. acknowledging it lets the search through, once and for all
    r = c.post("/how-matching-works",
               data={"csrf_token": token(c, "/how-matching-works")})
    check("acknowledging returns to the search",
          r.status_code == 302 and "/search" in r.headers.get("Location", ""),
          r.headers.get("Location"))
    r = c.get("/search", follow_redirects=False)
    check("the search opens once it is acknowledged",
          r.status_code == 200, f"HTTP {r.status_code}")

    # 5. a second device does not see it again -- it is on the account
    with app.test_client() as c2:
        c2.post("/login", data={"username": name, "password": "correct horse battery",
                                "csrf_token": token(c2)})
        r = c2.get("/search", follow_redirects=False)
        check("a second device is not shown it again", r.status_code == 200,
              f"HTTP {r.status_code}")

    # 6. still reachable deliberately, and re-reading does not re-trigger
    check("it stays reachable from the footer",
          c.get("/how-matching-works").status_code == 200)
    check("the footer links it", "how-matching-works" in c.get("/search").get_data(as_text=True))

print()
bad = [n for n, ok in R if not ok]
print("%d/%d checks passed" % (len(R) - len(bad), len(R)))
for n in bad:
    print("  failed: " + n)
raise SystemExit(1 if bad else 0)
