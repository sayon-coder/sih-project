"""One-off: retry ingestion for docs stuck in INDEXING/FAILED (ids 2, 64, 9, 69)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal
import app.rag.ingestion as ingestion

db = SessionLocal()
try:
    for did in [2, 69, 9, 64]:
        try:
            doc = ingestion.ingest_document(db, did)
            print(f'OK id={did}: status={doc.status} chunks={doc.chunk_count}', flush=True)
        except Exception as e:
            print(f'FAIL id={did}: {type(e).__name__}: {str(e)[:300]}', flush=True)
finally:
    db.close()
print('retry run complete', flush=True)
