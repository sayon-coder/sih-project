#!/bin/bash
# GCE startup script for IP-SAKTI Sahayak (free-tier e2-micro, Debian 12).
# Runs as root on first boot (and every boot - every step is idempotent).
# Full log: sudo journalctl -u google-startup-scripts.service
set -euo pipefail

APP_DIR="/opt/ip-sakti"
SECRETS_DIR="/root/.ip-sakti"

# --- metadata inputs (set on `gcloud compute instances create --metadata`) ---
REPO_URL="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/repo-url' \
  || echo 'https://github.com/sayon-coder/sih-project.git')"
REPO_BRANCH="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/repo-branch' \
  || echo 'main')"
GROQ_KEY="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/groq-api-key' || true)"
SARVAM_KEY="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/sarvam-api-key' || true)"
SMTP_PASS="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/smtp-password' || true)"
PUBLIC_IP="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip')"

# --- 2 GB swap: the e2-micro has 1 GB RAM; pip/npm builds OOM without this ---
if ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- docker ---
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

# --- code (first boot clones, later boots pull the deployed branch) ---
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin "$REPO_BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$REPO_BRANCH"
fi

# --- stable secrets: generated once, reused on every later boot so the
#     stored database stays reachable after a VM restart ---
mkdir -p "$SECRETS_DIR"
if [ ! -f "$SECRETS_DIR/db_password" ]; then
  openssl rand -hex 24 > "$SECRETS_DIR/db_password"
  chmod 600 "$SECRETS_DIR/db_password"
fi
if [ ! -f "$SECRETS_DIR/jwt_secret" ]; then
  openssl rand -hex 32 > "$SECRETS_DIR/jwt_secret"
  chmod 600 "$SECRETS_DIR/jwt_secret"
fi
DB_PASSWORD="$(cat "$SECRETS_DIR/db_password")"
JWT_SECRET="$(cat "$SECRETS_DIR/jwt_secret")"

# --- backend .env for compose (DATABASE_URL targets the compose postgres;
#     secrets come from metadata at deploy time, never from the repo) ---
cat > "$APP_DIR/BACKEND/.env" <<EOF
# Generated on the VM by gce-startup.sh - not part of the repo.
DATABASE_URL=postgresql://ipsakti:${DB_PASSWORD}@postgres:5432/ipsakti
JWT_SECRET_KEY=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
CORS_ORIGINS=http://${PUBLIC_IP}
DEMO_MODE=false
LLM_PROVIDER=groq
GROQ_API_KEY=${GROQ_KEY}
SARVAM_API_KEY=${SARVAM_KEY}
EMBEDDING_PROVIDER=sentence-transformers
RAG_CHUNK_SIZE=250
RAG_CHUNK_OVERLAP=40
RAG_TOP_K_RETRIEVAL=20
RAG_RERANK_TOP_K=6
RAG_MIN_SIMILARITY=0.30
MAX_UPLOAD_SIZE_MB=25
UPLOAD_DIR=data/uploads
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=sayonsawbib@gmail.com
SMTP_PASSWORD=${SMTP_PASS}
SMTP_USE_TLS=true
REVIEW_NOTIFY_EMAIL=sayonsawbib@gmail.com
REVIEW_NOTIFY_FROM=sayonsawbib@gmail.com
EOF
chmod 600 "$APP_DIR/BACKEND/.env"

# --- bring the stack up (overlay reads DB_PASSWORD/PUBLIC_IP from env) ---
export DB_PASSWORD
export PUBLIC_IP

cd "$APP_DIR"
# Rebuild images only when the deployed commit changed (pip/npm builds take
# 10+ minutes on an e2-micro); plain restarts just bring containers up.
HEAD_NOW="$(git -C "$APP_DIR" rev-parse HEAD)"
HEAD_DONE="$(cat "$SECRETS_DIR/deployed_commit" 2>/dev/null || true)"
if [ "$HEAD_NOW" != "$HEAD_DONE" ]; then
  docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d --build
  echo "$HEAD_NOW" > "$SECRETS_DIR/deployed_commit"
else
  docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d
fi

# --- first-boot data: roles/seed + corpus ingest (keyword-only on slim;
#     embeddings are skipped openly, FTS vectors are still written) ---
compose="docker compose -f docker-compose.yml -f docker-compose.gcp.yml"
# Wait for postgres + finished migrations (backend CMD runs alembic first).
for i in $(seq 1 60); do
  if $compose exec -T backend python -c \
    "import sqlalchemy as sa, os; e=sa.create_engine(os.environ['DATABASE_URL']); \
     e.connect().execute(sa.text('select count(*) from source_documents'))" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 10
done
$compose exec -T backend python scripts/seed_roles.py || true
DOCS="$($compose exec -T backend python -c \
  "import sqlalchemy as sa, os; e=sa.create_engine(os.environ['DATABASE_URL']); \
   print(e.connect().execute(sa.text('select count(*) from source_documents')).scalar())" \
  2>/dev/null | tr -d '\r' | tail -n 1)"
if [ "${DOCS:-0}" = "0" ]; then
  $compose exec -T backend python scripts/ingest_corpus.py \
    --dir corpus/ --public --corpus-version v1-gcp || true
  $compose exec -T backend python scripts/fix_corpus_jurisdictions.py --apply || true
fi

echo "IP-SAKTI Sahayak deploy finished: http://${PUBLIC_IP}/ (API docs at /api/docs)"
