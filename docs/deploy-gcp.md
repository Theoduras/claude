# Deploying Velvet to Google Cloud (Cloud Run + Cloud SQL)

Velvet runs as a stateless container on **Cloud Run**, with all data in
**Cloud SQL for PostgreSQL**. Cloud Run adds and removes instances on
demand, and because no state lives in the container, any instance can serve
any request.

**To do all of this in one command**, run the installer — it performs every
step below, skipping whatever already exists:

```bash
./scripts/deploy_gcp.sh --project your-project-id --region us-central1 --seed
```

Re-running it redeploys. The rest of this page is the same sequence by hand,
which is what to read when a step fails or you want to vary something.

Set `PROJECT_ID` and `REGION` once and the commands below can be pasted as-is:

```bash
export PROJECT_ID=your-project-id
export REGION=us-central1
export INSTANCE=velvet-db
gcloud config set project "$PROJECT_ID"
```

## 1. Enable the APIs

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

## 2. Create the database

```bash
gcloud sql instances create "$INSTANCE" \
  --database-version=POSTGRES_16 \
  --region="$REGION" \
  --tier=db-g1-small \
  --storage-auto-increase

gcloud sql databases create velvet --instance="$INSTANCE"

# Use a generated password rather than typing one in. Note the alphabet:
# `openssl rand -base64` emits "/" and "+", and a "/" in a password breaks any
# tool that builds a postgresql:// URI by string interpolation — libpq ends the
# userinfo segment at the slash and reports the password as an invalid "port".
# token_urlsafe stays within [A-Za-z0-9_-] and avoids the whole class of bug.
DB_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")')"
gcloud sql users create velvet_app --instance="$INSTANCE" --password="$DB_PASS"
```

`db-g1-small` is a starting point. Cloud SQL scales vertically with
`gcloud sql instances patch "$INSTANCE" --tier=...`, and read replicas can
be added later; neither requires an application change.

## 3. Store the secrets

```bash
printf '%s' "$DB_PASS" | gcloud secrets create velvet-db-pass --data-file=-
python3 -c 'import secrets; print(secrets.token_hex(32), end="")' \
  | gcloud secrets create velvet-secret-key --data-file=-
printf '%s' 'choose-a-real-admin-password' \
  | gcloud secrets create velvet-admin-pass --data-file=-
```

`APP_SECRET_KEY` **must** be set here rather than left to the app's random
fallback: with more than one instance running, a per-instance random key
would mean a session cookie issued by one instance is rejected by the next.

## 4. Grant the service account access

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/cloudsql.client

for s in velvet-db-pass velvet-secret-key velvet-admin-pass; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
done
```

## 5. Deploy

```bash
CONN_NAME="$(gcloud sql instances describe "$INSTANCE" --format='value(connectionName)')"

gcloud run deploy velvet \
  --source . \
  --region="$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances="$CONN_NAME" \
  --set-env-vars="INSTANCE_CONNECTION_NAME=${CONN_NAME},DB_USER=velvet_app,DB_NAME=velvet,AUTO_LOGIN=0,FLASK_DEBUG=0" \
  --set-secrets="DB_PASS=velvet-db-pass:latest,APP_SECRET_KEY=velvet-secret-key:latest,APP_ADMIN_PASSWORD=velvet-admin-pass:latest" \
  --min-instances=0 \
  --max-instances=10 \
  --concurrency=80
```

The app creates its schema and the admin account on boot, guarded by a
Postgres advisory lock so simultaneous instance starts don't collide.

Deploy again with the same command to ship changes — Cloud Run keeps the
URL and rolls traffic to the new revision.

## 6. Seed the demo profiles (optional)

The seeder needs to reach the database. Easiest is the Cloud SQL Auth Proxy
from your own machine:

```bash
cloud-sql-proxy "$CONN_NAME" &
DATABASE_URL="postgresql://velvet_app:${DB_PASS}@127.0.0.1:5432/velvet" \
  python seed_demo.py
```

`python seed_demo.py --reset` wipes the demo members and re-adds them.
Unlike the old setup, this is a **one-off** — the data persists, so it does
not need re-running after a deploy.

## Cloud Build triggers will undo this

If a Cloud Build trigger deploys the service on push, check what it runs. A
trigger that calls `gcloud run deploy --image …` **without**
`--set-env-vars`, `--set-secrets` and `--add-cloudsql-instances` creates a
revision with no database configuration at all. The app then falls back to
`127.0.0.1:5432`, every worker dies with `Connection refused`, and the service
returns 503 — even though the previous revision was healthy and nothing in the
code changed.

The revision's `managed-by: gcp-cloud-build-deploy-cloud-run` label is the
tell. Either disable the trigger (Cloud Build → Triggers) and deploy with
`scripts/deploy_gcp.sh`, or give the trigger's deploy step the same flags used
in §5. Do not leave both paths active with different configuration.

## Moving the instance to another region

Cloud SQL cannot change an instance's region, and the region is baked into the
connection name (`PROJECT:REGION:INSTANCE`) the app connects through. Cloud Run
in one region talking to Cloud SQL in another works, but pays the round trip on
every query. To move, create a new instance and re-seed — data in the old one
is not carried across:

```bash
NEW=velvet-db-eu
gcloud sql instances create "$NEW" \
  --database-version=POSTGRES_16 --region="$REGION" \
  --tier=db-g1-small --storage-auto-increase

gcloud sql databases create velvet --instance="$NEW"
DB_PASS="$(gcloud secrets versions access latest --secret=velvet-db-pass)"
gcloud sql users create velvet_app --instance="$NEW" --password="$DB_PASS"

./scripts/deploy_gcp.sh --project "$PROJECT_ID" --region "$REGION" \
  --instance "$NEW" --seed
```

Delete the old instance once the new one serves traffic — it bills while it
exists:

```bash
gcloud sql instances delete velvet-db
```

## Connection budget (the thing that bites at scale)

Total connections = `instances × workers × DB_POOL_MAX`. With the defaults
here (`max-instances=10`, 2 workers, pool max 5) that peaks at 100. Keep
that comfortably under the instance's `max_connections`, and when raising
`--max-instances`, either lower `DB_POOL_MAX` or put a pooler in front —
Cloud SQL **Managed Connection Pooling** (Enterprise Plus) or PgBouncer.

Tuning knobs, all environment variables: `DB_POOL_MIN`, `DB_POOL_MAX`,
`WEB_CONCURRENCY` (gunicorn workers), `WEB_THREADS`.

## Real-time chat latency

Chat and live-search update by polling every ~1.5 s
(`POLL_MS` in `templates/chat.html` and `templates/search_waiting.html`).

This replaced long-polling deliberately. Long-polling needs the instance
that *stores* a message to wake the instance *holding the recipient's open
request* — impossible with in-process signalling once there is more than
one instance. If sub-second delivery becomes a requirement, add
**Memorystore for Redis/Valkey** pub/sub for cross-instance fan-out (needs
Direct VPC egress, and a minimum spend) and reinstate the held-open request.
Don't take on that complexity before the latency is an actual complaint.

## Local development

Run Postgres however you like, point `DATABASE_URL` at it:

```bash
docker run -d --name velvet-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=velvet -p 5432:5432 postgres:16

export DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/velvet
pip install -r requirements.txt
python seed_demo.py
python app.py            # http://localhost:5000
```

To exercise the multi-process behaviour the way production runs it:

```bash
gunicorn -w 4 --threads 4 -b 127.0.0.1:8080 app:app
```
