"""
scripts/ingest_corpus.py

CLI tool to ingest a directory of PDF / TXT / MD files into the IP-SHAKTI
knowledge corpus, with per-stage timing (parse / chunk / embed / db) so slow
steps are easy to spot.

Usage:
    python scripts/ingest_corpus.py --dir corpus/ --public
    python scripts/ingest_corpus.py --dir corpus/ --only CCRAS_Drug --reindex
"""
import argparse
import hashlib
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add backend root to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.orm import Session

from app.database import engine
from app.models.rag_models import SourceDocument
import app.rag.ingestion as ingestion


# ------------------------------------------------------------------
# Timing instrumentation
# Wraps parse / chunk / embed inside app.rag.ingestion without editing it.
# ------------------------------------------------------------------
class Timings:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stage = defaultdict(float)
        self.chunk_stats = {"count": 0, "avg_words": 0, "max_words": 0}


timings = Timings()


def _timed(stage, fn):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            timings.stage[stage] += time.perf_counter() - start

    return wrapper


def install_timing_hooks():
    ingestion.parse_document = _timed("parse", ingestion.parse_document)

    original_chunk = ingestion.chunk_document

    def chunk_wrapper(*args, **kwargs):
        start = time.perf_counter()
        chunks = original_chunk(*args, **kwargs)
        timings.stage["chunk"] += time.perf_counter() - start
        sizes = [c.token_count for c in chunks]
        timings.chunk_stats = {
            "count": len(chunks),
            "avg_words": sum(sizes) // len(sizes) if sizes else 0,
            "max_words": max(sizes, default=0),
        }
        return chunks

    ingestion.chunk_document = chunk_wrapper

    original_get_provider = ingestion.get_embedding_provider

    def provider_wrapper(*args, **kwargs):
        provider = original_get_provider(*args, **kwargs)
        if not getattr(provider, "_embed_timed", False):
            provider.embed = _timed("embed", provider.embed)
            provider._embed_timed = True
        return provider

    ingestion.get_embedding_provider = provider_wrapper


def warm_up_model():
    """Load the embedding model up front so its load time isn't billed to file #1."""
    try:
        import torch

        print(f"CUDA available: {torch.cuda.is_available()}")
    except ImportError:
        pass
    start = time.perf_counter()
    dim = ingestion.get_embedding_provider().dimension
    print(f"Embedding model ready (dim={dim}) in {time.perf_counter() - start:.1f}s\n")


def ingest_and_time(db, doc_id, name):
    timings.reset()
    start = time.perf_counter()
    ingested = ingestion.ingest_document(db, doc_id)
    total = time.perf_counter() - start

    parse = timings.stage["parse"]
    chunk = timings.stage["chunk"]
    embed = timings.stage["embed"]
    db_time = max(total - parse - chunk - embed, 0.0)
    s = timings.chunk_stats

    print(
        f"    -> {ingested.chunk_count} chunk(s), "
        f"avg {s['avg_words']} / max {s['max_words']} words. Status: {ingested.status}"
    )
    print(
        f"    -> parse {parse:.1f}s | chunk {chunk:.1f}s | "
        f"embed {embed:.1f}s | db {db_time:.1f}s | total {total:.1f}s"
    )
    return {
        "name": name,
        "chunks": ingested.chunk_count,
        "parse": parse,
        "chunk": chunk,
        "embed": embed,
        "db": db_time,
        "total": total,
    }


def print_summary(results, wall_time):
    if not results:
        return
    print("\n--- Timing summary ---")
    for key in ("parse", "chunk", "embed", "db"):
        print(f"{key:>6}: {sum(r[key] for r in results):8.1f}s")
    print(f" total: {wall_time:8.1f}s across {len(results)} file(s)")
    print("Slowest files:")
    for r in sorted(results, key=lambda r: r["total"], reverse=True)[:5]:
        print(f"  {r['total']:7.1f}s  {r['name']} ({r['chunks']} chunks)")


# ------------------------------------------------------------------
# Ingestion
# ------------------------------------------------------------------
def compute_hash(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while block := f.read(65536):
            sha.update(block)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into the RAG corpus.")
    parser.add_argument("--dir", required=True, help="Directory containing documents (.pdf, .txt, .md)")
    parser.add_argument(
        "--source-type",
        default="official_guidance",
        help="Source type (patent, law, regulation, scientific_paper, traditional_knowledge, etc.)",
    )
    parser.add_argument("--jurisdiction", default="India", help="Jurisdiction (India, WIPO, US, etc.)")
    parser.add_argument(
        "--public",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mark documents as public in corpus (use --no-public to disable)",
    )
    parser.add_argument("--corpus-version", default="v1.0-verified", help="Corpus version tag")
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Re-ingest documents that already exist (e.g. after changing the chunker)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Only process files whose name contains this text (case-insensitive)",
    )
    args = parser.parse_args()

    doc_dir = Path(args.dir)
    if not doc_dir.exists() or not doc_dir.is_dir():
        print(f"Error: Directory not found: {doc_dir}")
        sys.exit(1)

    allowed_exts = {".pdf", ".txt", ".text", ".md"}
    files = sorted(
        f for f in doc_dir.iterdir() if f.is_file() and f.suffix.lower() in allowed_exts
    )
    if args.only:
        files = [f for f in files if args.only.lower() in f.name.lower()]

    if not files:
        print(f"No matching document files found in {doc_dir}.")
        return

    print(f"Found {len(files)} document(s) to process.")

    install_timing_hooks()
    warm_up_model()

    results = []
    run_start = time.perf_counter()

    with Session(engine) as db:
        for f in files:
            doc_hash = compute_hash(f)
            existing = (
                db.query(SourceDocument)
                .filter(SourceDocument.document_hash == doc_hash)
                .first()
            )

            if existing and not args.reindex:
                print(f"[-] Skipping duplicate: {f.name} (already document_id={existing.id})")
                continue

            if existing:
                print(f"[~] Re-indexing: {f.name} (document_id={existing.id})")
                doc_id = existing.id
            else:
                title = f.stem.replace("_", " ").replace("-", " ").title()
                print(f"[+] Registering: {title} ({f.name})")
                doc = SourceDocument(
                    title=title,
                    source_type=args.source_type,
                    jurisdiction=args.jurisdiction,
                    language="en",
                    file_path=str(f.resolve()),
                    document_hash=doc_hash,
                    is_public=args.public,
                    corpus_version=args.corpus_version,
                    status="PENDING",
                )
                db.add(doc)
                db.commit()
                db.refresh(doc)
                doc_id = doc.id

            try:
                results.append(ingest_and_time(db, doc_id, f.name))
            except Exception as e:
                print(f"    -> Ingestion failed: {e}")

    print_summary(results, time.perf_counter() - run_start)
    print("\nIngestion run complete.")


if __name__ == "__main__":
    main()