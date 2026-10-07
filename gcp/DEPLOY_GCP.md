# Hosting IP-SAKTI Sahayak fully on GCP (free tier, $0/month)

Everything - frontend, backend, PostgreSQL + pgvector - runs on **one
always-free `e2-micro` VM** (1 vCPU, 1 GB RAM, 30 GB disk) in
`us-central1`. The app is served by nginx on port 80, with the API proxied
same-origin under `/api`, so there are no CORS or mixed-content issues.

Deliberately NOT used (all billable): Cloud SQL, Cloud Run, load
balancers, Serverless VPC connectors. The database is plain PostgreSQL 16
with pgvector in Docker - the same image as local dev.

Trade-offs of the free VM (read before deploying):

- The backend builds from `requirements-slim.txt`: **keyword-only
  retrieval** (no vector arm, no reranker). Chat, analyses, screenings,
  reports, reviews and email all work normally.
- First boot takes 20-40 minutes (Docker install, pip/npm builds and
  corpus ingest on a tiny machine). Later reboots take ~2 minutes.
- Plain HTTP. Fine for a class demo; see "HTTPS follow-up" below for
  production use.
- Deleting the VM deletes the database with it (take a snapshot first if
  the data matters).

## 0. Commit and push (required)

The VM clones from GitHub - uncommitted work does **not** deploy:

```bash
git add -A
git commit -m "Deploy to GCP"
git push origin main
```

The repo must be **public** (or the clone step fails). If it is private,
make it public temporarily or install with a deploy key manually.

## 1. Create a GCP account and project

- Sign up at <https://cloud.google.com> (a card is required; the free
  tier itself is not charged).
- Create a project, note its **project ID**, and install `gcloud`
  (`gcloud init`, select the project), or use Cloud Shell in the console
  (no install needed).
- Free-tier regions for `e2-micro`: `us-west1`, `us-central1`,
  `us-east1`. The commands below use `us-central1-a`.

## 2. Collect the three secrets (metadata, never committed)

| Metadata key      | Value | Where to find it |
|-------------------|-------|------------------|
| `groq-api-key`    | Your Groq key | Local `BACKEND/.env`, `GROQ_API_KEY=` |
| `sarvam-api-key`  | Your Sarvam key (optional, may be empty) | Local `BACKEND/.env`, `SARVAM_API_KEY=` |
| `smtp-password`   | Gmail app password **without spaces** (optional; empty disables email openly) | Google Account -> Security -> App passwords |

The DB password and JWT secret are generated on the VM itself and
persisted in `/root/.ip-sakti/` (survive reboots, never leave the VM).

## 3. Create the VM

From the repo root (this folder contains `gcp/gce-startup.sh`):

```bash
gcloud compute instances create ipsakti-vm \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --tags=http-server \
  --metadata-from-file=startup-script=gcp/gce-startup.sh \
  --metadata=groq-api-key=PASTE_GROQ_KEY,sarvam-api-key=PASTE_SARVAM_KEY,smtp-password=PASTE_SMTP_APP_PASSWORD
```

The `http-server` tag opens port 80 via the default `default-allow-http`
firewall rule. If that rule was deleted in your project, recreate it:

```bash
gcloud compute firewall-rules create allow-http-ipsakti \
  --allow=tcp:80 --source-ranges=0.0.0.0/0 --target-tags=http-server
```

## 4. Keep the IP stable (recommended)

Ephemeral IPs change on stop/start. Promote the VM's current IP to a
static one (free while the VM runs):

```bash
IP=$(gcloud compute instances describe ipsakti-vm --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
gcloud compute addresses create ipsakti-ip --region=us-central1 --addresses="$IP"
echo "App will be at: http://$IP/"
```

## 5. Wait and verify

Watch the first-boot log (Docker install -> image builds -> migrations ->
role seed -> corpus ingest -> jurisdiction fix):

```bash
gcloud compute ssh ipsakti-vm --zone=us-central1-a -- \
  sudo journalctl -u google-startup-scripts.service -f
```

When it prints `IP-SAKTI Sahayak deploy finished`, open:

- App: `http://<IP>/`
- API docs: `http://<IP>/api/docs`
- Health: `http://<IP>/api/health`

Then register an account, ask the chatbot a question (keyword retrieval),
and request a review on `/reviews` - the "Email reviewer" button should
report `sent` if `smtp-password` was provided.

## 6. Updating the app later

```bash
git push origin main                              # from your machine
gcloud compute instances stop ipsakti-vm --zone=us-central1-a
gcloud compute instances start ipsakti-vm --zone=us-central1-a
```

The startup script re-pulls `main` on boot and rebuilds images **only**
when the commit changed. Database and users survive (same disk, stable
secrets in `/root/.ip-sakti/`).

## 7. Useful commands on the VM

```bash
gcloud compute ssh ipsakti-vm --zone=us-central1-a
cd /opt/ip-sakti
sudo docker compose -f docker-compose.yml -f docker-compose.gcp.yml ps
sudo docker compose -f docker-compose.yml -f docker-compose.gcp.yml logs backend --tail=50
sudo docker compose -f docker-compose.yml -f docker-compose.gcp.yml exec backend \
  python -m pytest tests/test_notify.py -q
```

## 8. HTTPS follow-up (optional, still free)

Plain HTTP exposes logins to the network. The minimal upgrade is Caddy
in front of nginx with a (free) domain pointed at the static IP:

1. Point an A record at the static IP.
2. Add a `caddy` service to the compose files reverse-proxying the
   frontend and terminating TLS automatically (Let's Encrypt).

Not wired by default because it needs a domain you own.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `http://<IP>/` refuses connection after 10 min | First boot still building; watch the startup log (§5). Full first boot is 20-40 min on e2-micro. |
| Build killed / OOM | The script adds 2 GB swap; if Docker was installed manually without it, add swap and rebuild. |
| Chat says "insufficient evidence" for everything | Corpus ingest still running or failed; check `docker ... logs backend`, re-run `ingest_corpus.py` + `fix_corpus_jurisdictions.py --apply` via exec. |
| Review email "not sent (SMTP not configured)" | `smtp-password` metadata was empty; stop the VM, edit metadata (`gcloud compute instances add-metadata ...`), start again. |
| Login broken after VM recreate | Expected: new disk = new DB + new JWT secret. Re-register. Snapshot the boot disk beforehand if data matters. |
| Bill warning | Stay inside: 1 e2-micro in us-west1/central1/east1, 30 GB pd-standard, static IP attached to a running VM, < 1 GB egress/month. Anything else (Cloud SQL, balancer, extra disks) bills. |
