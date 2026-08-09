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

## Heartlink — dating website (local demo)

A Flask dating site with registration, login, and member profiles.

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

The **Matches** page finds compatible profiles: both people's gender
preferences must accept each other, then candidates are ranked by shared
interests/hobbies, matching relationship goals, age proximity, and same
location — with the top match highlighted and the reasons listed.

**Login is currently bypassed:** every visitor is signed in automatically
as the seeded `admin` account and lands straight on the browse page. The
`/login` and `/register` pages just forward into the site. (The account
and password-hashing plumbing is still in place, so a real login flow can
be re-enabled later.)

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
