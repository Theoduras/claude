#!/usr/bin/env bash
#
# Automatic installer: Velvet -> Cloud Run + Cloud SQL for PostgreSQL.
#
# Idempotent. Every step checks whether the resource already exists, so a
# re-run is a redeploy, not a failure. Safe to interrupt and restart.
#
#   ./scripts/deploy_gcp.sh --project my-project [--region us-central1] [--seed]
#
# Requires: gcloud (authenticated), an active billing account on the project.
# Manual walkthrough of the same steps: docs/deploy-gcp.md

set -euo pipefail

PROJECT_ID=""
REGION="us-central1"
INSTANCE="velvet-db"
SERVICE="velvet"
DB_NAME="velvet"
DB_USER="velvet_app"
TIER="db-g1-small"
DB_VERSION="POSTGRES_16"
MAX_INSTANCES=10
SEED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)       PROJECT_ID="$2"; shift 2 ;;
    --region)        REGION="$2"; shift 2 ;;
    --instance)      INSTANCE="$2"; shift 2 ;;
    --service)       SERVICE="$2"; shift 2 ;;
    --tier)          TIER="$2"; shift 2 ;;
    --max-instances) MAX_INSTANCES="$2"; shift 2 ;;
    --seed)          SEED=1; shift ;;
    -h|--help)       sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v gcloud >/dev/null || die "gcloud not found — https://cloud.google.com/sdk/docs/install"

[[ -n "$PROJECT_ID" ]] || PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
[[ -n "$PROJECT_ID" && "$PROJECT_ID" != "(unset)" ]] || die "no project: pass --project PROJECT_ID"

gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . \
  || die "not authenticated — run: gcloud auth login"

cd "$(dirname "$0")/.."
[[ -f app.py && -f Dockerfile ]] || die "run this from the Velvet repo"

gcloud config set project "$PROJECT_ID" --quiet >/dev/null
echo "project=$PROJECT_ID region=$REGION instance=$INSTANCE service=$SERVICE"

# ---------------------------------------------------------------- APIs
# Enabling an already-enabled API is a no-op, so this is unconditional.
log "Enabling APIs (a few minutes on a new project)"
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet

# ------------------------------------------------------------ Cloud SQL
if gcloud sql instances describe "$INSTANCE" --quiet >/dev/null 2>&1; then
  log "Cloud SQL instance $INSTANCE exists — reusing"
else
  log "Creating Cloud SQL instance $INSTANCE (10-15 min, one time)"
  gcloud sql instances create "$INSTANCE" \
    --database-version="$DB_VERSION" \
    --region="$REGION" \
    --tier="$TIER" \
    --storage-auto-increase \
    --quiet
fi

CONN_NAME="$(gcloud sql instances describe "$INSTANCE" --format='value(connectionName)')"
[[ -n "$CONN_NAME" ]] || die "could not read connectionName for $INSTANCE"

if gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" --quiet >/dev/null 2>&1; then
  echo "database $DB_NAME exists"
else
  log "Creating database $DB_NAME"
  gcloud sql databases create "$DB_NAME" --instance="$INSTANCE" --quiet
fi

# ---------------------------------------------------------------- Secrets
# The DB password is generated, never typed, and only ever leaves this script
# through Secret Manager. On a re-run the existing secret is reused so the
# password in Cloud SQL and the one in Secret Manager cannot drift apart.
secret_exists() { gcloud secrets describe "$1" --quiet >/dev/null 2>&1; }

create_secret() { # name, value
  if secret_exists "$1"; then
    echo "secret $1 exists"
  else
    printf '%s' "$2" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic --quiet
    echo "secret $1 created"
  fi
}

log "Provisioning secrets"
if secret_exists velvet-db-pass; then
  DB_PASS="$(gcloud secrets versions access latest --secret=velvet-db-pass)"
else
  DB_PASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32),end="")')"
  create_secret velvet-db-pass "$DB_PASS"
fi

# APP_SECRET_KEY must be fixed, not the app's per-process random fallback:
# with more than one instance, a cookie signed by one is rejected by the next.
create_secret velvet-secret-key "$(python3 -c 'import secrets;print(secrets.token_hex(32),end="")')"
create_secret velvet-admin-pass "$(python3 -c 'import secrets;print(secrets.token_urlsafe(18),end="")')"

# Applied every run: makes the Cloud SQL user match the stored secret whether
# the user is new or predates this script.
if gcloud sql users list --instance="$INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
  gcloud sql users set-password "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS" --quiet
else
  gcloud sql users create "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS" --quiet
fi

# ------------------------------------------------------------------- IAM
log "Granting the runtime service account access"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/cloudsql.client \
  --condition=None --quiet >/dev/null

for s in velvet-db-pass velvet-secret-key velvet-admin-pass; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor \
    --condition=None --quiet >/dev/null
done

# ---------------------------------------------------------------- Deploy
# --source builds with Cloud Build and pushes to Artifact Registry; the repo's
# Dockerfile wins over buildpack detection.
log "Building and deploying to Cloud Run"
gcloud run deploy "$SERVICE" \
  --source . \
  --region="$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances="$CONN_NAME" \
  --set-env-vars="INSTANCE_CONNECTION_NAME=${CONN_NAME},DB_USER=${DB_USER},DB_NAME=${DB_NAME},AUTO_LOGIN=0,FLASK_DEBUG=0" \
  --set-secrets="DB_PASS=velvet-db-pass:latest,APP_SECRET_KEY=velvet-secret-key:latest,APP_ADMIN_PASSWORD=velvet-admin-pass:latest" \
  --min-instances=0 \
  --max-instances="$MAX_INSTANCES" \
  --concurrency=80 \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"

# ------------------------------------------------------------------ Seed
if [[ "$SEED" == "1" ]]; then
  log "Seeding demo profiles through the Cloud SQL Auth Proxy"
  if command -v cloud-sql-proxy >/dev/null; then
    cloud-sql-proxy "$CONN_NAME" --port 55432 &
    PROXY_PID=$!
    trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
    sleep 8
    DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:55432/${DB_NAME}" python3 seed_demo.py
  else
    echo "cloud-sql-proxy not installed — skipping seed."
    echo "https://cloud.google.com/sql/docs/postgres/sql-proxy, then re-run with --seed"
  fi
fi

log "Deployed"
echo "  URL:      $URL"
echo "  admin pw: gcloud secrets versions access latest --secret=velvet-admin-pass"
echo
echo "Redeploy after changes: re-run this script (or gcloud run deploy $SERVICE --source . --region=$REGION)"
