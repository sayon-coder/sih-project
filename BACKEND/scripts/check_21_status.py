import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal
from app.models.rag_models import SourceDocument, SourceChunk
from sqlalchemy import func
db = SessionLocal()
targets = ['drugs-and-magic-remedies-objectionable-advertisements-act-1954.md','patent-amendment-rules-2024-india.md','geographical-indications-act-1999-india.md','trade-marks-act-1999-india.md','designs-act-2000-india.md','copyright-act-1957-india.md','plant-variety-farmers-rights-act-2001-india.md','biological-diversity-rules-2024-india.md','fssai-ayurveda-aahar-regulations-2022.md','section-3j-3p-patenting-bar-tkdl-guidance.md','first-schedule-authoritative-texts-ayurveda.md','ayurvedic-pharmacopoeia-india-standards.md','trips-agreement-1994-relevant-provisions.md','convention-biological-diversity-1992-cbd.md','nagoya-protocol-2010-access-benefit-sharing.md','patent-cooperation-treaty-pct.md','madrid-protocol-international-trademark-registration.md','hague-system-industrial-designs-registration.md','budapest-treaty-microorganism-deposit.md','indian-ip-case-law-compendium.md','eu-germany-herbal-medicinal-product-market-access.md']
print('--- 21-file embedding + metadata check ---')
for t in targets:
    d = db.query(SourceDocument).filter(SourceDocument.file_path.contains(t)).first()
    total = db.query(SourceChunk).filter(SourceChunk.document_id == d.id).count()
    nulls = db.query(SourceChunk).filter(SourceChunk.document_id == d.id, SourceChunk.embedding.is_(None)).count()
    sample = db.query(SourceChunk).filter(SourceChunk.document_id == d.id).order_by(SourceChunk.chunk_index).first()
    meta_jur = json.loads(sample.metadata_json).get('jurisdiction') if sample else None
    print(f'{t}: chunks={total} null_embed={nulls} doc_jur={d.jurisdiction} meta_jur={meta_jur}')
print('--- stuck docs file existence ---')
import os
for did in [64, 2, 9, 69]:
    d = db.get(SourceDocument, did)
    same = os.path.exists(os.path.join('corpus', os.path.basename(d.file_path))) if d else False
    print(f'id={did} stored_exists={os.path.exists(d.file_path) if d else None} local_same_name={same}')
db.close()
