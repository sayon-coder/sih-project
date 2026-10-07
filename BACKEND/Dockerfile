# IP-SAKTI Sahayak backend (FastAPI + RAG).
#
#   docker build -t ipsakti-backend ./BACKEND
#   docker run --env-file BACKEND/.env -p 8000:8000 ipsakti-backend
#
# The container runs `alembic upgrade head` on start (Alembic owns the
# schema; the app never creates tables at boot) and then serves the API
# with uvicorn. Provide DATABASE_URL, JWT_SECRET_KEY and GROQ_API_KEY via
# --env-file (see BACKEND/.env.example). The BGE-M3 embedding model
# (several GB) downloads on first AI request; bake it in with an extra
# `python scripts/ingest_corpus.py` layer if the registry allows it.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

# System deps: libpq for psycopg, build tools for sentence-transformers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-slim.txt ./
# Free-tier VMs (1 GB RAM) cannot run torch/sentence-transformers: build with
# --build-arg REQUIREMENTS_FILE=requirements-slim.txt for a keyword-only
# backend (retrieval degrades openly, everything else works).
ARG REQUIREMENTS_FILE=requirements.txt
RUN pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

COPY alembic.ini alembic/ ./alembic/
COPY alembic ./alembic
COPY app ./app
COPY scripts/seed_roles.py scripts/ingest_corpus.py ./scripts/
COPY corpus ./corpus

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
