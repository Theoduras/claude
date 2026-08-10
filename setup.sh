#!/usr/bin/env sh
# Velvet one-shot setup for Linux and macOS.
# Clones (or updates) the repo, starts Postgres in Docker, installs
# dependencies, seeds demo data, and starts the app.
#
#   sh setup.sh
#
# Run it from anywhere: it works on the clone in ~/velvet, creating it if
# needed. Run it from inside an existing clone and that clone is used as-is.

set -eu

REPO_URL="https://github.com/Theoduras/claude.git"
BRANCH="claude/localhost-login-page-el4mjf"
TARGET_DIR="${VELVET_DIR:-$HOME/velvet}"

fail() {
    printf '\033[31mERROR: %s\033[0m\n' "$1" >&2
    exit 1
}

have() {
    command -v "$1" >/dev/null 2>&1
}

python_cmd=""
for candidate in python3 python; do
    if have "$candidate"; then python_cmd="$candidate"; break; fi
done
[ -n "$python_cmd" ] || fail "Python 3 not found. Install it (macOS: 'brew install python', Debian/Ubuntu: 'sudo apt install python3 python3-pip'), then re-run this script."

have git || fail "Git not found. Install it (macOS: 'brew install git', Debian/Ubuntu: 'sudo apt install git'), then re-run this script."

have docker || fail "Docker not found. Velvet stores its data in PostgreSQL, which this script runs in a container. Install Docker (https://docs.docker.com/get-docker/), start it, then re-run this script."

# Docker Compose v2 is a subcommand; older standalone docker-compose still works.
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose "$@"; }
elif have docker-compose; then
    compose() { docker-compose "$@"; }
else
    fail "Docker is installed but Docker Compose is not available. Install the Compose plugin (https://docs.docker.com/compose/install/), then re-run this script."
fi

docker info >/dev/null 2>&1 || fail "Docker is installed but its engine isn't running. Start Docker (macOS: open Docker Desktop; Linux: 'sudo systemctl start docker'), then re-run this script. On Linux you may also need to be in the 'docker' group: 'sudo usermod -aG docker \$USER' then log out and back in."

# Already inside a clone? Use it. Otherwise clone/update ~/velvet.
if [ -d .git ] && [ -f app.py ]; then
    printf 'Using the clone in %s ...\n' "$(pwd)"
elif [ -d "$TARGET_DIR/.git" ]; then
    printf 'Updating existing copy in %s ...\n' "$TARGET_DIR"
    git -C "$TARGET_DIR" fetch origin "$BRANCH"
    git -C "$TARGET_DIR" checkout "$BRANCH"
    git -C "$TARGET_DIR" pull origin "$BRANCH"
    cd "$TARGET_DIR"
else
    printf 'Cloning into %s ...\n' "$TARGET_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

echo "Installing dependencies ..."
# PEP 668 marks system Python "externally managed" on newer distros; fall back
# to a local venv rather than telling the user to --break-system-packages.
if ! "$python_cmd" -m pip install --quiet -r requirements.txt 2>/dev/null; then
    echo "System Python refused the install; using a virtualenv in .venv instead ..."
    "$python_cmd" -m venv .venv
    python_cmd="$(pwd)/.venv/bin/python"
    "$python_cmd" -m pip install --quiet --upgrade pip
    "$python_cmd" -m pip install --quiet -r requirements.txt
fi

echo "Starting PostgreSQL in Docker ..."
compose up -d || fail "Could not start PostgreSQL. If something else is already using port 5432, stop it (or change the port mapping in docker-compose.yml) and re-run this script."

# The app's connection pool gives up after 30s, so seeding a database that is
# still starting fails. Wait for the container's own healthcheck instead.
printf 'Waiting for PostgreSQL to accept connections ...'
healthy=""
i=0
while [ "$i" -lt 60 ]; do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' velvet-db 2>/dev/null)" = "healthy" ]; then
        healthy="yes"
        break
    fi
    sleep 2
    printf '.'
    i=$((i + 1))
done
echo ""
[ -n "$healthy" ] || fail "PostgreSQL did not become ready in time. Check 'docker compose logs db' for details."

echo "Seeding 20 demo members into the live-search pool ..."
"$python_cmd" seed_demo.py

echo ""
printf '\033[32mStarting Velvet at http://localhost:5000 (Ctrl+C to stop)\033[0m\n'
printf '\033[90mThe database keeps running in Docker. Stop it with: docker compose down\033[0m\n'

# Open a browser if the platform has an obvious way to.
if have open; then
    open "http://localhost:5000" 2>/dev/null || true
elif have xdg-open; then
    xdg-open "http://localhost:5000" >/dev/null 2>&1 || true
fi

exec "$python_cmd" app.py
