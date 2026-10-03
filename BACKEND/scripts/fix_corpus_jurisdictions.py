"""
scripts/fix_corpus_jurisdictions.py

Correct mislabelled ``source_documents.jurisdiction`` values in the live
corpus.

The original ingest stamped every public document with jurisdiction
"India", including U.S. law (21 CFR / FDA), a China policy document and
international (WIPO / PIC/S) material. Because the chatbot's jurisdiction
scope trusts this column, U.S. CGMP passed every gate as "India" and was
cited for an India + Germany market-entry question.

This script rewrites ONLY the ``jurisdiction`` column, and only for
documents whose identity makes the correct jurisdiction unambiguous:

    Cfr Title21 ... / Fda ... / Federal Regulations (Cfr)  -> United States
    Chinas ... policy document                              -> China
    Wipo ... / Pic S ... (international instruments)       -> International

Every other document is left untouched (ambiguous titles are never
guessed). Idempotent: re-running it produces no further changes.

Usage:
    python scripts/fix_corpus_jurisdictions.py            # dry run
    python scripts/fix_corpus_jurisdictions.py --apply    # write changes
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func

from app.database import SessionLocal
from app.models.rag_models import SourceDocument

# (title prefix, correct jurisdiction) - exact document identities only.
TITLE_RULES = [
    ("Cfr Title21", "United States"),
    ("Cfr Title 21", "United States"),
    ("Fda ", "United States"),
    ("Federal Regulations (Cfr)", "United States"),
    ("Chinas ", "China"),
    ("Wipo ", "International"),
    ("Pic S ", "International"),
    ("Pic/S ", "International"),
]


def matches(title: str) -> str | None:
    """Return the correct jurisdiction for a document title, else None."""
    for prefix, jurisdiction in TITLE_RULES:
        if title.startswith(prefix):
            return jurisdiction
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the corrections (default is a dry run that only prints).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(SourceDocument)
            .filter(
                SourceDocument.jurisdiction.isnot(None),
                SourceDocument.uploader_id.is_(None),  # corpus docs only
            )
            .all()
        )
        changes = []
        for doc in rows:
            correct = matches(doc.title or "")
            if correct and correct != doc.jurisdiction:
                changes.append((doc.id, doc.title, doc.jurisdiction, correct))

        if not changes:
            print("No mislabelled documents found - nothing to do.")
            return 0

        print(f"{'APPLY' if args.apply else 'DRY RUN'}: "
              f"{len(changes)} document(s) to correct\n")
        for doc_id, title, old, new in changes:
            print(f"  [{doc_id}] {title[:70]!r}: {old} -> {new}")

        if args.apply:
            for doc_id, _, _, new in changes:
                doc = db.get(SourceDocument, doc_id)
                doc.jurisdiction = new
            db.commit()
            print(f"\nApplied {len(changes)} correction(s).")
            counts = (
                db.query(SourceDocument.jurisdiction, func.count())
                .group_by(SourceDocument.jurisdiction)
                .all()
            )
            print("Corpus jurisdiction distribution now:")
            for jurisdiction, count in sorted(counts, key=lambda r: -r[1]):
                print(f"  {jurisdiction or '(untagged)'}: {count}")
        else:
            print("\nDry run only - re-run with --apply to write changes.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
