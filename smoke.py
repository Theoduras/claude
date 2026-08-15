"""Hit every GET route and report anything that 5xxs.

    python smoke.py

Uses Flask's test client, so there is no server to start and no port to pick.
Runs in a couple of seconds — fast enough to check a change without clicking
through the UI. It proves routes render, not that they render *correctly*;
it is a tripwire for tracebacks, not a substitute for looking at the page.

Needs a reachable database (DATABASE_URL), same as the app: importing app.py
opens the connection pool and creates the schema.
"""

import re
import sys
import uuid

import app as app_module
from app import app


def csrf_token(client):
    """Pull a CSRF token out of a rendered form.

    Every POST needs one now, so the smoke test has to behave like a browser
    rather than posting bare form data.
    """
    html = client.get("/register").get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else ""


def url_for_rule(rule, me_id):
    """Turn a rule into a concrete URL, or None if we can't fill its args."""
    if not rule.arguments:
        return str(rule)

    # Every <int:...> in this app is a user, match, or profile id. Our
    # throwaway user has no matches, so those legitimately 404 — which is a
    # fine, non-5xx answer and still exercises the view's lookup path.
    values = {}
    for arg in rule.arguments:
        if arg in ("user_id", "other_id"):
            values[arg] = me_id
        elif arg == "match_id":
            values[arg] = 1
        else:
            return None
    try:
        with app.test_request_context():
            from flask import url_for

            return url_for(rule.endpoint, **values)
    except Exception:
        return None


def main():
    failures = []
    skipped = []

    with app.test_client() as client:
        username = f"smoke_{uuid.uuid4().hex[:10]}"
        password = "smoketest123"

        resp = client.post(
            "/register",
            data={
                "username": username,
                "email": f"{username}@example.test",
                "dob": "1995-06-15",
                "password": password,
                "confirm": password,
                "accept_terms": "1",
                "accept_sensitive": "1",
                "csrf_token": csrf_token(client),
            },
            follow_redirects=False,
        )
        if resp.status_code >= 400:
            print(f"FAIL  /register returned {resp.status_code} — cannot continue")
            return 1

        # The cookie carries an opaque session token now, not the user id, so
        # ask the database who we just became.
        with app.test_request_context():
            row = app_module.get_db().execute(
                "SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,)
            ).fetchone()
        me_id = None if row is None else row["id"]
        if me_id is None:
            print("FAIL  /register did not create an account — cannot continue")
            return 1

        print(f"registered {username} (id={me_id})\n")

        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            if "GET" not in rule.methods or rule.endpoint == "static":
                continue

            url = url_for_rule(rule, me_id)
            if url is None:
                skipped.append((str(rule), "could not synthesize arguments"))
                continue

            try:
                resp = client.get(url, follow_redirects=True)
            except Exception as exc:  # a view raising is the thing we're hunting
                failures.append((url, f"raised {type(exc).__name__}: {exc}"))
                print(f"FAIL  {url}  raised {type(exc).__name__}")
                continue

            if resp.status_code >= 500:
                failures.append((url, f"HTTP {resp.status_code}"))
                print(f"FAIL  {url}  HTTP {resp.status_code}")
            else:
                print(f"ok    {url}  HTTP {resp.status_code}")

    if skipped:
        print("\nskipped:")
        for path, why in skipped:
            print(f"  {path} — {why}")

    print()
    if failures:
        print(f"{len(failures)} route(s) failed:")
        for url, why in failures:
            print(f"  {url}: {why}")
        return 1

    print("All routes responded without a server error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
