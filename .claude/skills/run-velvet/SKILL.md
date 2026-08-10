---
name: run-velvet
description: Launch and drive the Velvet Flask dating app locally — install deps, bootstrap PostgreSQL, seed demo data, start the server, log in as a demo user, and screenshot a page. Use this whenever the task involves running, starting, serving, opening, or previewing the app; taking a screenshot of a page; reproducing a bug in the running app; or confirming a change works end-to-end rather than only in tests. Also use it when a route, template, or DB change needs to be seen in a browser.
---

# Running Velvet

Velvet is a single-module Flask 3 app (`app.py`) over PostgreSQL, with server-rendered
Jinja templates. There is no ORM and no migration tool — `app.py` creates its own schema
on first connect, so a bare empty database is all it needs.

A fresh container has none of this set up: no Python deps, no running Postgres, no
`velvet` database, no data. The steps below are the verified cold-start path. Run them in
order; each one is quick and idempotent enough to re-run safely.

## 1. Python dependencies

```bash
pip install -q --ignore-installed blinker -r requirements.txt
```

`--ignore-installed blinker` is the important part. Debian ships a system `blinker` whose
dist-info has no RECORD file, so pip cannot uninstall it to satisfy Flask's dependency and
aborts the whole install with "Cannot uninstall blinker 1.7.0". Ignoring it lets pip
install its own copy alongside. Without the flag nothing gets installed and the failure
looks unrelated to blinker at first glance.

## 2. PostgreSQL

```bash
service postgresql start
sleep 3 && pg_isready
su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\" -c 'CREATE DATABASE velvet;'"
```

The app defaults to `postgres:postgres@127.0.0.1:5432/velvet` when `DATABASE_URL` is unset,
which is why the password is set to `postgres` rather than configuring the app. `CREATE
DATABASE` fails harmlessly if the database already exists — keep going.

If a task needs a different database, set `DATABASE_URL` before launching instead of
editing `app.py`.

## 3. Seed demo data

```bash
python seed_demo.py
```

This creates 20 members, all with password `demo12345`, each with a profile and an active
live search. Without it the app runs but every list page is empty, which makes UI changes
impossible to evaluate. Usernames are short handles (`mia_b`, `liam_k`, `paula_o`, …) —
the `users` table has **no email column**, so log in with `username`.

To pick one without guessing:

```bash
su postgres -c "psql -d velvet -tAc 'select username from users limit 1'"
```

## 4. Start the server

Launch it in the background so you keep the shell, and send output to a log you can read
when something fails:

```bash
python app.py > "$SCRATCHPAD/app.log" 2>&1   # run_in_background: true
```

It binds `0.0.0.0:5000` with the reloader and debugger on (`PORT` overrides the port).
Give it ~4 seconds, then confirm it is really up — a background launch that crashed on
import looks identical to a healthy one until you check:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/    # 302 -> /login when logged out
tail -5 "$SCRATCHPAD/app.log"
```

This is a remote container, so the user cannot open `localhost:5000` themselves. A
screenshot is the only way they see the result — plan to produce one.

## 5. Drive it

Launching proves the entrypoint resolves; it does not prove the feature works. Nearly every
interesting page is behind auth, so log in first and carry the cookie jar.

```bash
curl -s -c c.txt -b c.txt -L -d "username=mia_b&password=demo12345" \
  http://127.0.0.1:5000/login -o /dev/null -w "%{http_code} %{url_effective}\n"
for p in /browse /matches /chats /search; do
  curl -s -b c.txt -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:5000$p
done
```

A successful login redirects to `/browse`. Always include whatever route your change
actually touched — the four above are a general smoke test, not a substitute for exercising
the thing you edited.

## 6. Screenshot

`scripts/shot.mjs` logs in and screenshots a path. It needs Playwright's Node package once
per container (Chromium itself is already installed at `/opt/pw-browsers/chromium`; never
run `playwright install`):

```bash
cd "$SCRATCHPAD" && npm i -s playwright
node /home/user/claude/.claude/skills/run-velvet/scripts/shot.mjs /browse velvet.png
```

Arguments are `[path] [output] [username] [password]`, defaulting to `/browse`,
`velvet.png`, `mia_b`, `demo12345`.

Then **read the PNG back**. A dark-purple velvet page with a top nav is a healthy render;
a blank or white frame means the page errored or the login silently failed, and the
screenshot is the only place that shows it. Send the image to the user with `SendUserFile`
— for them it is the entire result.
