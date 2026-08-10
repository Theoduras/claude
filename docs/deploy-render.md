# Deploying Velvet to Render (live URL)

This repo includes a `render.yaml` Blueprint that deploys the Flask app
(`app.py`) behind gunicorn on Render's **free** tier.

## One-time setup

1. Sign up / log in at <https://dashboard.render.com> (free account).
2. **New** → **Blueprint**.
3. Connect your GitHub account if you haven't, then pick the
   `Theoduras/claude` repo and the `claude/localhost-login-page-el4mjf`
   branch (or whichever branch you're developing on — Render deploys
   whatever branch the Blueprint is pointed at).
4. Render reads `render.yaml` and shows one service, **velvet-dating**.
   Click **Apply**.
5. On the service's **Environment** tab, set `APP_ADMIN_PASSWORD` to a
   real password (it's marked `sync: false` in the blueprint so Render
   prompts for it instead of using the app's weak default).
   `APP_SECRET_KEY` is auto-generated for you.
6. First deploy takes a minute or two. When it's live, Render shows the
   URL — something like `https://velvet-dating.onrender.com`.

That URL is permanent (until you delete the service) and every push to
the connected branch triggers an automatic redeploy.

## About data on the free tier

The free plan has no persistent disk, and the instance **spins down
after ~15 minutes of no traffic**. The next request boots a fresh
instance with an empty filesystem — so the SQLite file (`dating.db`,
living next to `app.py`) resets at that point, and also on every
redeploy. Useful for showing off the UI and flows, not for data you
need to keep.

If/when you want data to actually stick around, switch to a paid
instance and add a persistent disk — bump `render.yaml`:

```yaml
plan: starter # or higher
disk:
  name: velvet-data
  mountPath: /var/data
  sizeGB: 1
envVars:
  - key: DATABASE_PATH
    value: /var/data/dating.db
  # ...keep the other envVars from the free config
```

`app.py` already reads `DATABASE_PATH` from the environment (falls back
to `dating.db` next to `app.py` when unset), so no code changes are
needed to make that switch — just edit `render.yaml` and redeploy.

## Seeding demo data

After each fresh boot (first deploy, or any time the instance spins
back up empty), open the service's **Shell** tab in the Render
dashboard and run:

```bash
python seed_demo.py
```

This adds 20 demo members who are all live-searching, so a search finds
a match immediately. `python seed_demo.py --reset` wipes and re-adds
them.

## Iterating

Push commits to the connected branch — Render rebuilds and redeploys
automatically. On the free tier, each redeploy also resets the
database, so re-run the seeder afterward if you want demo data back.

## Local development is unaffected

`python app.py` still works exactly as before: binds `0.0.0.0:5000` by
default (override with `PORT`), debug mode on by default (override with
`FLASK_DEBUG=0`), and uses `dating.db` next to `app.py` unless
`DATABASE_PATH` is set.
