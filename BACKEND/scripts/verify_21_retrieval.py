"""Verify RAG retrieval over the 21-file batch (keyword+vector, no LLM calls)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal
from app.rag.retrieval import hybrid_retrieve
from app.rag.jurisdiction_scope import (
    allowed_jurisdictions, chunk_in_scope, apply_jurisdiction_scope,
)

db = SessionLocal()
try:
    checks = []
    # 1. Germany market question -> EU/Germany doc must surface and stay in scope
    gq = 'What are the requirements to sell an Ayurvedic herbal medicinal product in Germany under Directive 2001/83/EC traditional-use registration?'
    gres = hybrid_retrieve(db, gq, top_k_final=10)
    allowed_g = allowed_jurisdictions(['Germany'])
    kept, excluded = apply_jurisdiction_scope(gres, allowed_g)
    eu_hits = [c for c in kept if c.document_id == 123]
    print(f'GERMANY Q: retrieved={len(gres)} kept={len(kept)} excluded={len(excluded)} eu_doc_hits={len(eu_hits)} allowed={allowed_g}')
    for c in kept[:6]:
        print(f'  keep doc={c.document_id} jur={c.jurisdiction} title={c.title[:60]}')
    checks.append(('germany-eu-doc-in-scope', len(eu_hits) > 0))

    # 2. India question -> biodiversity rules doc must surface and stay in scope
    iq = 'What does the Biological Diversity Rules 2024 require for access to medicinal plants in India?'
    ires = hybrid_retrieve(db, iq, top_k_final=10)
    allowed_i = allowed_jurisdictions(['India'])
    kept_i, _ = apply_jurisdiction_scope(ires, allowed_i)
    bd_hits = [c for c in kept_i if c.document_id == 117]
    print(f'INDIA Q: retrieved={len(ires)} kept={len(kept_i)} bd_doc_hits={len(bd_hits)} allowed={allowed_i}')
    for c in kept_i[:6]:
        print(f'  keep doc={c.document_id} jur={c.jurisdiction} title={c.title[:60]}')
    checks.append(('india-bd-doc-in-scope', len(bd_hits) > 0))

    # 3. Unit-level scope sanity for the new Germany label
    checks.append(('germany-label-in-scope', chunk_in_scope('Germany', ['Germany', 'European Union'])))
    checks.append(('germany-eu-hyphen-would-drop', not chunk_in_scope('Germany-EU', ['Germany', 'European Union'])))

    print('---')
    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f'{"PASS" if ok else "FAIL"} {n}')
    sys.exit(1 if failed else 0)
finally:
    db.close()
