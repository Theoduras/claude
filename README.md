# Velvet

A Flask dating-site demo with registration, login, member profiles, live
matchmaking, and real-time chat.

This repo also contains an unrelated [Vast.ai API client](#vastai-api-client).

## Quick start

**Windows** — paste into PowerShell; clones to `~\velvet`, installs
dependencies, seeds demo data, and starts the app:

```powershell
iwr -useb https://raw.githubusercontent.com/Theoduras/claude/claude/localhost-login-page-el4mjf/setup.ps1 -OutFile "$env:TEMP\setup.ps1"; powershell -ExecutionPolicy Bypass -File "$env:TEMP\setup.ps1"
```

Re-running it pulls the latest version first. Requires
[Git](https://git-scm.com/download/win) and
[Python](https://www.python.org/downloads/) (check "Add python.exe to PATH").

**Any platform:**

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://localhost:5000>.

## Using the site

Register an account and fill in your profile — name, age, gender, who you're
looking for, location, bio, interests, hobbies, wants, needs, and relationship
type. From there:

- **Live search** is instant matchmaking. Pick the kind of connection you want,
  then set your filters: who you're looking for, an age range, your location
  plus a search radius in km, and optional interests. Everyone searching sits in
  a pool, and the moment two searches satisfy each other *both ways*, the pair
  is created and both browsers jump into a shared chatroom.
- **Find a match** is the guided version: choose a relationship type, get 3
  ranked options with the reasons shown. People you've already matched with drop
  out of the list.
- **Matches** is the unfiltered view — every gender-compatible profile, ranked
  by shared interests, matching goals, age proximity, and location.
- **Chats** lists your rooms. Messages arrive in milliseconds via long polling,
  and the header shows `live` / `reconnecting…`. Rooms are private to the two
  matched members; the admin can read any room but not write in it.

Distances use a built-in table of city coordinates, so Berlin→Leipzig is 149 km.
Unrecognised cities aren't distance-filtered.

## Demo data

`seed_demo.py` adds 20 varied members (ages 20–41, mixed genders, cities, and
goals) who are all live-searching at once, so a search matches immediately:

```bash
python seed_demo.py            # add or refresh them (safe to re-run)
python seed_demo.py --reset    # wipe them and their chats, then re-add
```

They all log in with `demo12345` (e.g. `mia_b`, `liam_k`) — handy for watching a
chat from the other side in a second browser window.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `APP_SECRET_KEY` | random per boot | Set it to keep sessions valid across restarts |
| `APP_ADMIN_PASSWORD` | `admin12345` | Password for the auto-created `admin` account |
| `AUTO_LOGIN` | `0` | `1` skips login and browses as admin (local dev only) |
| `DATABASE_PATH` | `dating.db` beside `app.py` | Where the SQLite file lives |
| `PORT` / `FLASK_DEBUG` | `5000` / `1` | Bind port; `FLASK_DEBUG=0` for production |

`dating.db` is git-ignored. **This is a local demo** — the default admin
password and auto-login make it unsafe to expose to the internet as-is.

## Design system

Velvet's identity is documented in `docs/style-guide.html` (open it in a
browser); all tokens live at the top of `templates/base.html`.

| Token | Value | Role |
| --- | --- | --- |
| `--ink` | `#0B0713` | Page ground — near-black with a violet bias |
| `--violet` / `--violet-crest` | `#8A2BE2` / `#A855F7` | Primary action, highlights |
| `--violet-deep` | `#3B0B66` | Fold shadow, gradient base |
| `--teal` / `--teal-crest` | `#12807F` / `#1DA6A2` | Secondary action, live state |
| `--champagne` | `#E8D3A9` | Light itself — values and focus rings |

Violet acts, teal responds: a violet control changes something about you, a teal
one belongs to the other person or to live state. The velvet texture is drawn
entirely in CSS — no image files.

## Deployment

See [docs/deploy-render.md](docs/deploy-render.md). `render.yaml` deploys to
Render's free tier, which has no persistent disk: `dating.db` resets on redeploy
and after ~15 minutes idle.

## Vast.ai API client

A minimal Python client and CLI for the [Vast.ai](https://vast.ai) REST API,
targeting the v0 API (`https://console.vast.ai/api/v0`). Verify request and
response shapes against the current [API docs](https://docs.vast.ai/api/), as
the API evolves.

The client reads your API key from `VAST_API_KEY`. It is never hardcoded in the
source and never written to logs. Get or rotate your key at
<https://console.vast.ai/account/>; treat it like a password, and rotate
immediately if it's ever exposed.

```bash
export VAST_API_KEY="your-key-here"

python vastai_client.py whoami
python vastai_client.py offers --max-price 0.5 --gpu-name RTX_4090
python vastai_client.py instances
python vastai_client.py create 1234567 --image pytorch/pytorch --disk 20
python vastai_client.py destroy 9876543
```

```python
from vastai_client import VastClient

client = VastClient()          # reads VAST_API_KEY
offers = client.search_offers(max_price=0.5)
```

`create` and `destroy` cost real money and terminate real machines. Test with
the read-only `offers` and `instances` commands first.
