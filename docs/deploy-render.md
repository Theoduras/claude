# Deploying Velvet to Render (live URL + persistent database)

This repo includes a `render.yaml` Blueprint that deploys the Flask app
(`app.py`) behind gunicorn, with the SQLite database on a persistent disk
so data survives restarts and redeploys.

## One-time setup

1. Sign up / log in at <https://dashboard.render.com> (free account is
   fine to start).
2. **New** → **Blueprint**.
3. Connect your GitHub account if you haven't, then pick the
   `Theoduras/claude` repo and the `claude/localhost-login-page-el4mjf`
   branch (or whichever branch you're developing on — Render deploys
   whatever branch the Blueprint is pointed at).
4. Render reads `render.yaml` and shows one service, **velvet-dating**.
   Click **Apply**.
5. On the service's **Environment** tab, set `APP_ADMIN_PASSWORD` to a
   real password (it's marked `sync: false` in the blueprint so Render
   prompts for it instead of storing a default). `APP_SECRET_KEY` is
   auto-generated for you.
6. First deploy takes a minute or two. When it's live, Render shows the
   URL — something like `https://velvet-dating.onrender.com`.

That URL is permanent (until you delete the service) and every push to
the connected branch triggers an automatic redeploy.

## Persistent data

`render.yaml` mounts a 1 GB disk at `/var/data` and points
`DATABASE_PATH` at `/var/data/dating.db`, so the SQLite file lives on
that disk instead of the app's ephemeral filesystem. It survives
redeploys and restarts.

This requires a **paid instance type** (`plan: starter`, ~$7/mo) —
Render's free web service tier doesn't support persistent disks, and
free instances spin down after 15 minutes of inactivity and come back
with a wiped filesystem, so the database would reset constantly. If you
want to stay on the free tier for now and accept that trade-off, delete
the `disk:` block and the `DATABASE_PATH` env var from `render.yaml`
before deploying — the app falls back to `dating.db` next to `app.py`,
which resets on every redeploy/spin-down.

## Seeding demo data (optional)

After the first deploy, open the service's **Shell** tab in the Render
dashboard and run:

```bash
python seed_demo.py
```

This adds 20 demo members who are all live-searching, so a search finds
a match immediately. Re-run any time (safe), or `python seed_demo.py
--reset` to wipe and re-add them.

## Iterating

Just keep pushing commits to the connected branch — Render rebuilds and
redeploys automatically, and the database on the persistent disk is
untouched by the redeploy.

## Local development is unaffected

`python app.py` still works exactly as before: binds `0.0.0.0:5000` by
default (override with `PORT`), debug mode on by default (override with
`FLASK_DEBUG=0`), and uses `dating.db` next to `app.py` unless
`DATABASE_PATH` is set.
