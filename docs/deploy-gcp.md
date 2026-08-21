# Deploying Velvet to Google Cloud (Cloud Run + Cloud SQL)

Velvet runs as a stateless container on **Cloud Run**, with all data in
**Cloud SQL for PostgreSQL**. Cloud Run adds and removes instances on
demand, and because no state lives in the container, any instance can serve
any request.

Set `PROJECT_ID` and `REGION` once and the commands below can be pasted as-is:

```bash
export PROJECT_ID=your-project-id
export REGION=europe-west4
export INSTANCE=velvet-db
gcloud config set project "$PROJECT_ID"
```

Use the **same region for Cloud Run and Cloud SQL**. Cross-region works — the
Cloud SQL socket is reachable either way — but every query then pays a
transatlantic round trip. A Cloud SQL instance's region is **immutable**, so
correcting a mismatch later means creating a second instance and migrating the
data, not moving the one you have.

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

# Generate a URL-safe password. Do NOT use `openssl rand -base64 32`: its
# alphabet includes "/", and step 7 below pastes this value straight into a
# DATABASE_URL, where a single "/" silently truncates the credentials.
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
python3 -c 'import secrets; print(secrets.token_urlsafe(18), end="")' \
  | gcloud secrets create velvet-admin-pass --data-file=-
```

`APP_SECRET_KEY` **must** be set here rather than left to the app's random
fallback: with more than one instance running, a per-instance random key
would mean a session cookie issued by one instance is rejected by the next.

`velvet-admin-pass` is only consulted the **first** time the app reaches an
empty database: `init_db()` sets the admin password when it creates the row,
and every later boot just re-asserts `is_admin = TRUE` (`app.py`). Changing
the secret afterwards does not change the login — you have to update the hash
in the database. Read the value back with:

```bash
gcloud secrets versions access latest --secret=velvet-admin-pass
```

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

`--source` deploys additionally upload a build context to a `run-sources-*`
GCS bucket, which needs bucket-create rights. Grant them or the deploy fails
with `does not have storage.buckets.create access`:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/storage.admin
```

Do not assume these are already in place — see the note in **CI deploy** below.

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
  --concurrency=80 \
  --startup-probe=httpGet.path=/healthz,periodSeconds=5,timeoutSeconds=5,failureThreshold=6
```

The app creates its schema and the admin account on boot, guarded by a
Postgres advisory lock so simultaneous instance starts don't collide.

**Keep the startup probe.** Gunicorn binds the port before forking workers, so
Cloud Run's default TCP probe passes the instant the master starts — before any
worker has touched the database. Without an HTTP probe, a revision that cannot
reach Cloud SQL still reports *"deployed and is serving 100 percent of
traffic"* and then returns `Service Unavailable` on every request, with the
real error visible only in the runtime logs. `/healthz` returns 503 (and
retries the schema init, so a database that was merely slow recovers on its
own) until the app can actually query, which turns that silent failure into a
failed deploy.

**Watch `/-/health`, not `/healthz`, from outside.** The probe path works
because Cloud Run dials the container directly. Google's frontend intercepts
the literal `/healthz` on the way in, so through the mapped domain it answers
with Google's own 404 page and never reaches the app — every other path,
including `/healthz/` and `/health`, gets through fine. `/-/health` is the same
handler on a path nothing upstream claims. Point uptime monitoring at that.

Deploy again with the same command to ship changes — Cloud Run keeps the
URL and rolls traffic to the new revision.

## 6. Map a custom domain (optional)

Cloud Run serves the app on a generated `*.run.app` URL. Pointing your own
domain at it is three steps: prove you own the domain, create the mapping,
then point DNS at Google.

**Verify the domain.** In [Google Search Console](https://search.google.com/search-console),
add a **Domain** property (not URL-prefix — the domain property covers every
subdomain, so `www` needs no separate verification) and add the `TXT` record it
gives you at your registrar. Use the same Google account as GCP and the
verification is visible to Cloud Run automatically.

**Create the mappings.** Note the `beta` track: `--region` is not on the GA
`domain-mappings` command, which fails with a confusing `unrecognized
arguments` error.

```bash
gcloud beta run domain-mappings create --service=velvet --domain=example.com --region="$REGION"
gcloud beta run domain-mappings create --service=velvet --domain=www.example.com --region="$REGION"
```

**Point DNS at Google.** Read the exact records back rather than copying them
from memory:

```bash
gcloud beta run domain-mappings describe --domain=example.com --region="$REGION" \
  --format="table(status.resourceRecords)"
```

The apex needs four `A` records (`216.239.32.21`, `.34.21`, `.36.21`,
`.38.21`) and optionally the matching `AAAA` records; `www` needs a single
`CNAME` to `ghs.googlehosted.com.`. A `CNAME` on the apex is not legal — it
cannot coexist with the zone's own `NS`/`SOA` records — so the apex must use
`A` records. Delete any parking or redirect record the registrar put on `@`
and `www` first, or it will keep resolving to their placeholder page.

`dig +short example.com` may return only two of the four addresses on any
given call; resolvers hand back rotating subsets. Run it twice before
concluding a record is missing.

**Wait for the certificate.** Google issues a managed TLS certificate once the
domain resolves to it — minutes usually, up to 24h at worst. Until then the
site serves a certificate warning, which is expected rather than a
misconfiguration:

```bash
gcloud beta run domain-mappings describe --domain=example.com --region="$REGION" \
  --format="value(status.conditions[].type, status.conditions[].status)"
```

`DomainRoutable: True` with `CertificateProvisioned: Unknown` and `Retry:
True` is the normal in-progress state. An empty
`status.conditions[].message` means it is queued, not stuck. You want
`CertificateProvisioned: True` and `Ready: True`.

**Then pick one hostname.** Serving on both the apex and `www` splits sessions:
a cookie set on `example.com` is not sent to `www.example.com`, so a user who
logs in on one and later lands on the other appears logged out. Set
`CANONICAL_HOST` and the app 308-redirects every other host — `www` and the
`*.run.app` URL alike — to that one, and marks the session cookie `Secure`:

```bash
gcloud run services update velvet --region="$REGION" \
  --update-env-vars=CANONICAL_HOST=example.com
```

Leave it unset for local development and for any deployment without a mapped
domain; unset means no redirect and no `Secure` flag, since a `Secure` cookie
is never returned over plain http on localhost. `/healthz` is exempt from the
redirect — Cloud Run's startup probe reaches the container directly rather
than through the mapped domain, so redirecting it would fail every deploy.

## 6b. The dev subdomain (`dev.velvt.nl`)

`dev.velvt.nl` is a **second Cloud Run service** — `velvet-dev` — running the
same image from a branch you choose, against its **own database** on the same
Cloud SQL instance. One instance, two databases: a dev deploy costs no extra
Cloud SQL money, and `python seed_demo.py --reset` against it cannot touch a
real member's account. Sharing the production database instead would have
made the one thing a dev site is for — trying destructive changes — the one
thing you could not do on it.

`.github/workflows/deploy-dev.yml` does the deploying. Steps 1–4 of this
document are already done; the one-time setup below is what is left.

### One time

```bash
export PROJECT_ID=velvet-app-505108
export REGION=europe-west4
export INSTANCE=velvet-db-eu

# Its own database, same instance and same user.
gcloud sql databases create velvet_dev --instance="$INSTANCE"

# Its own session key and admin password. Sharing APP_SECRET_KEY with
# production would mean one signing key across two trust boundaries, which
# is not a saving worth making for one `gcloud secrets create`.
python3 -c 'import secrets; print(secrets.token_hex(32), end="")' \
  | gcloud secrets create velvet-dev-secret-key --data-file=-
python3 -c 'import secrets; print(secrets.token_urlsafe(18), end="")' \
  | gcloud secrets create velvet-dev-admin-pass --data-file=-

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for s in velvet-dev-secret-key velvet-dev-admin-pass; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
done
```

Read the dev admin password back with
`gcloud secrets versions access latest --secret=velvet-dev-admin-pass`. As in
step 3, it is only consulted the **first** time the app reaches the empty
database.

### Deploy it once, then map the domain

Run **Actions → Deploy to dev.velvt.nl → Run workflow** and pick a branch.
The service has to exist before a domain can be mapped to it.

```bash
gcloud beta run domain-mappings create \
  --service=velvet-dev --domain=dev.velvt.nl --region="$REGION"
```

No extra domain verification is needed: the Search Console **Domain**
property for `velvt.nl` from step 6 covers every subdomain, which is exactly
why that property type was the one to add.

### The DNS record at Mijndomein

`dev` is a subdomain, not the apex, so it is a single `CNAME` — none of the
four `A` records the apex needs:

| Type | Name / host | Value | TTL |
|---|---|---|---|
| `CNAME` | `dev` | `ghs.googlehosted.com.` | default (1h) |

In Mijndomein's control panel this is under the domain's **DNS-instellingen**
(*Mijn domeinen → velvt.nl → DNS*). Enter the host as `dev` alone, not
`dev.velvt.nl` — Mijndomein appends the domain itself, and typing the full
name yields `dev.velvt.nl.velvt.nl`, which resolves to nothing and looks
identical to a typo you cannot see in the form. Keep the trailing dot on the
value.

Confirm the record before blaming the certificate:

```bash
dig +short dev.velvt.nl CNAME     # expect ghs.googlehosted.com.
```

Then wait for the managed certificate exactly as in step 6 —
`CertificateProvisioned: Unknown` with `Retry: True` is normal progress, and
a certificate warning until it lands is expected rather than broken:

```bash
gcloud beta run domain-mappings describe --domain=dev.velvt.nl --region="$REGION" \
  --format="value(status.conditions[].type, status.conditions[].status)"
```

### What dev does differently

The workflow sets three things production does not, and each is the reason
this must never be the production service:

- `ALLOW_BOT_MATCHES=1` — without it the seeded demo members are excluded
  from every search pool and a search on dev would never pair, which makes
  the site untestable by one person.
- `DB_NAME=velvet_dev` and its own secrets, per above.
- `SEARCH_INDEXING` **left unset**, so the app serves a disallow-all
  `robots.txt` and an `X-Robots-Tag: noindex, nofollow` header. A public
  near-duplicate of the site is a real SEO problem, not a theoretical one,
  and the flag defaults to off so a future preview host that forgets it is
  still safe. Production sets `SEARCH_INDEXING=1` explicitly in
  `deploy-gcp.yml` — that line is what keeps velvt.nl indexable, so do not
  remove it.

`CANONICAL_HOST=dev.velvt.nl` also applies, so the `*.run.app` URL redirects
to the mapped domain and the session cookie is `Secure`, same as production.

Seed dev's demo members with **Actions → Seed the demo profiles → Run
workflow**, choosing `velvet_dev` as the database.

## 7. Seed the demo profiles (optional)

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

## CI deploy (GitHub Actions)

`.github/workflows/deploy-gcp.yml` redeploys the current code to the
already-created Cloud Run service + Cloud SQL instance above on every push
to **`main`**. It assumes steps 1–4 have already been done once by hand.

Work on a feature branch does **not** deploy — pushing there ships nothing,
and Cloud Run keeps serving whatever `main` last built. To put a branch in
front of the real service without merging, use **Run workflow** in the
Actions tab (or `gh workflow run deploy-gcp.yml --ref <branch>`): the job
checks out the ref it was dispatched on, so the branch deploys to the same
service and URL, replacing the running revision until the next deploy.

One-time setup, using **Workload Identity Federation** — GitHub Actions
authenticates without any long-lived key. This is required on projects where
the `iam.disableServiceAccountKeyCreation` org policy blocks SA key creation
(the default on projects created since mid-2024), and is the recommended
path regardless:

```bash
gcloud services enable iamcredentials.googleapis.com --project="$PROJECT_ID"

gcloud iam workload-identity-pools create "github-pool" \
  --project="$PROJECT_ID" --location=global \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='Theoduras/claude'"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/Theoduras/claude"

gcloud iam workload-identity-pools providers describe "github-provider" \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool="github-pool" --format="value(name)"
```

The default compute SA does **not** automatically carry everything this deploy
needs — an earlier version of this document claimed it did, and the first CI
runs failed on exactly that (`does not have storage.buckets.create access`).
Grant step 4's roles explicitly, and confirm the SA also has
`roles/cloudbuild.builds.editor` and `roles/artifactregistry.writer` for
`--source` builds. A dedicated `velvet-deployer` account isn't necessary unless
you want CI's identity separated from the app's runtime identity.

Then in the repo's **Settings → Secrets and variables → Actions**, add:

- `GCP_WORKLOAD_IDENTITY_PROVIDER` — the resource name printed by the last
  command above
- `GCP_SERVICE_ACCOUNT` — `$SA` from above
- `GCP_PROJECT_ID` — your `$PROJECT_ID`
- `GCP_REGION` (optional, as a **variable** not a secret) — defaults to
  `europe-west4` if unset, matching the fallback in the workflow's `env:` block

Both grants (`iam.workloadIdentityPoolAdmin` to create the pool/provider,
`iam.serviceAccountKeyAdmin` if you experiment with keys instead) are
project-level IAM roles — grant them to your own account first if a command
above 403s with a `PERMISSION_DENIED` naming that permission.

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
