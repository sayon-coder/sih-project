"""One-off: tag the EU/Germany market-access doc as Germany + sync chunk metadata."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal
from app.models.rag_models import SourceDocument, SourceChunk

db = SessionLocal()
try:
    d = db.query(SourceDocument).filter(
        SourceDocument.file_path.contains('eu-germany-herbal-medicinal-product-market-access.md')
    ).first()
    assert d is not None, 'EU-Germany doc not found'
    print(f'before: id={d.id} jurisdiction={d.jurisdiction}')
    d.jurisdiction = 'Germany'
    chunks = db.query(SourceChunk).filter(SourceChunk.document_id == d.id).all()
    for c in chunks:
        meta = json.loads(c.metadata_json or '{}')
        meta['jurisdiction'] = 'Germany'
        c.metadata_json = json.dumps(meta, ensure_ascii=False)
    db.commit()
    print(f'after: id={d.id} jurisdiction={d.jurisdiction} chunks_updated={len(chunks)}')
finally:
    db.close()
