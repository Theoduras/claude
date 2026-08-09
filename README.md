# Vast.ai API client

A minimal Python client and CLI for the [Vast.ai](https://vast.ai) REST API.

## Setup

```bash
pip install -r requirements.txt
```

## Authentication

The client reads your API key from the `VAST_API_KEY` environment variable.
It is never hardcoded in the source and never written to logs.

```bash
export VAST_API_KEY="your-key-here"
```

Get or rotate your key at <https://console.vast.ai/account/>. Treat the key
like a password: don't commit it, don't paste it into chats or issues. If a
key is ever exposed, rotate it immediately.

## Usage

```bash
python vastai_client.py whoami
python vastai_client.py offers --max-price 0.5 --gpu-name RTX_4090
python vastai_client.py instances
python vastai_client.py create 1234567 --image pytorch/pytorch --disk 20
python vastai_client.py destroy 9876543
```

You can also import the client in your own code:

```python
from vastai_client import VastClient

client = VastClient()          # reads VAST_API_KEY
offers = client.search_offers(max_price=0.5)
```

## Velvet — dating website (local demo)

A Flask dating site with registration, login, and member profiles.

### Design system

Velvet's identity is documented in `docs/style-guide.html` (open it in a
browser). The short version:

| Token | Value | Role |
| --- | --- | --- |
| `--ink` | `#0B0713` | Page ground — near-black with a violet bias |
| `--violet` / `--violet-crest` | `#8A2BE2` / `#A855F7` | Primary action, highlights |
| `--violet-deep` | `#3B0B66` | Fold shadow, gradient base |
| `--teal` / `--teal-crest` | `#12807F` / `#1DA6A2` | Secondary action, live state |
| `--champagne` | `#E8D3A9` | Light itself — values and focus rings |

Violet acts, teal responds: a violet control changes something about you, a
teal one belongs to the other person or to live state. Headings are a
high-contrast serif, controls and labels are sans, and numbers are tabular.

The velvet texture is drawn in CSS — no image files — as three layers on
`body` and `.card`: soft radial gradients place the light, blurred conic
gradients form the pleats, and an inline SVG `feTurbulence` grain raked to
94° gives the cut pile its nap. Primary buttons sweep a highlight on hover,
because brushing velvet changes how it catches light. All tokens live at the
top of `templates/base.html`.

**Windows quick start** — paste this into PowerShell; it clones the repo to
`~\heartlink`, installs dependencies, opens your browser, and starts the app:

```powershell
iwr -useb https://raw.githubusercontent.com/Theoduras/claude/claude/localhost-login-page-el4mjf/setup.ps1 -OutFile "$env:TEMP\setup.ps1"; powershell -ExecutionPolicy Bypass -File "$env:TEMP\setup.ps1"
```

Re-running it later pulls the latest version before starting. Requires
[Git](https://git-scm.com/download/win) and
[Python](https://www.python.org/downloads/) (check "Add python.exe to PATH").

**Manual start** on any platform:

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://localhost:5000>. Fill in your profile (name, age, gender,
who you're looking for, location, bio, interests, hobbies, wants, needs,
relationship type) and browse other members' profiles.

**Live search** is instant matchmaking, in two steps:

1. **Choose the kind of connection** you're after (long-term, casual,
   friendship, …) — this is the first and only thing on the entry page.
2. **Set your filters:** who you're looking for, an age range on a
   two-handle slider, your location plus a **search radius in km** on its
   own slider (at the maximum it means "anywhere"), and optional interests.

Everyone searching sits in a pool, and as soon as two searches satisfy each
other *both ways* — each is the gender the other wants, each falls inside
the other's age range, the distance between their cities fits inside **both**
radii, and their relationship goals don't conflict — the pair is created and
both browsers jump straight into a shared chatroom. The waiting page holds
an open request, so the second person is pulled in the moment the first one
matches them.

Distances come from a built-in table of city coordinates (great-circle
maths, no external geocoding service), so "Berlin" to "Leipzig" is 149 km.
An unrecognised city simply isn't distance-filtered.

Example: a man seeking women 18–25, a woman seeking men 18–25, and a man
seeking men 18–25 all search at once — the first two are paired, and the
third keeps waiting because nobody in the pool is looking for men.

### Demo data

`seed_demo.py` fills the site with 20 varied members (ages 20–41, mixed
genders, cities and goals) who are **all live-searching at the same
time**, so a search finds a partner immediately:

```bash
python seed_demo.py            # add/refresh them (safe to re-run)
python seed_demo.py --reset    # wipe them and their chats, then re-add
```

They all log in with the password `demo12345` (e.g. `mia_b`, `liam_k`),
which is handy for watching a chat from the other side in a second
browser window. The Windows setup script runs the seeder automatically.

**Find a match** is a guided two-step flow: first choose which kind of
relationship you're after (your profile's choice is pre-selected), then
you get **3 options** — people who want that same relationship type, whose
gender preferences mutually match yours, ranked best-fit first with the
reasons shown. People you've already matched with are filtered out, so
the options refresh as you go.

The **Matches** page is the unfiltered view: every gender-compatible
profile ranked by shared interests/hobbies, matching relationship goals,
age proximity, and same location.

Hitting **Match & chat** on a match stores the pairing and opens a shared
**chatroom** for the two profiles, with message bubbles per side and full
history kept in the database. All rooms are listed under **Chats**. While
login is bypassed, the chat form lets you pick which of the two matched
profiles is speaking, so you can play both sides from one browser.

**Accounts and login:** anyone can register (username + password, min 8
chars) and log in; registering walks you straight into the profile
editor. The seeded `admin` account logs in with `admin12345` (override
via `APP_ADMIN_PASSWORD`). When the admin creates a profile they can set
an optional password so that member can log in themselves; without one
the profile exists but has no login access. For local development,
`AUTO_LOGIN=1` skips the login page and browses as admin.

Chat messages are always sent as the logged-in user, and chatrooms are
private to the two matched members — the admin can view (not write in)
any room. The chat updates in real time: messages send without a page
reload, and the browser holds an open long-poll request that the server
releases the instant a message is stored, so the other side sees it in
milliseconds (no polling delay). Dropped connections retry automatically
and the header shows `live` / `reconnecting…`.

Data is stored in a local SQLite file (`dating.db`, git-ignored). Set
`APP_SECRET_KEY` to keep login sessions valid across restarts. This is a
local demo — the default admin password and auto-login make it unsafe to
expose to the internet as-is.

## Notes

- Endpoints target the Vast.ai v0 API (`https://console.vast.ai/api/v0`).
  Verify request/response shapes against the current
  [API docs](https://docs.vast.ai/api/), as the API evolves.
- `create` and `destroy` cost real money / terminate real machines. Test with
  `offers` and `instances` (read-only) first.
