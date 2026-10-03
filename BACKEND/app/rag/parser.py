"""
Document parser for the RAG ingestion pipeline.

Supported formats:
  - PDF  (via PyMuPDF / fitz)
  - TXT  (plain text)

Returns a ParsedDocument with full text and per-page metadata.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Dict, Any

from app.rag.schemas import ParsedDocument

logger = logging.getLogger(__name__)


def parse_document(file_path: str) -> ParsedDocument:
    """Parse a document file into text + metadata.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the file on disk.

    Returns
    -------
    ParsedDocument with concatenated text and per-page info.

    Raises
    ------
    ValueError:
        If the file format is not supported.
    FileNotFoundError:
        If the file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path)
    elif suffix in (".txt", ".text", ".md"):
        return _parse_txt(path)
    else:
        raise ValueError(
            f"Unsupported file format: '{suffix}'. "
            "Supported: .pdf, .txt, .text, .md"
        )


# ------------------------------------------------------------------
# Internal parsers
# ------------------------------------------------------------------

def _parse_pdf(path: Path) -> ParsedDocument:
    """Parse a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is not installed. Run: pip install PyMuPDF") from exc

    pages: List[Dict[str, Any]] = []

    doc = fitz.open(str(path))
    try:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")
            text = _clean_text(text)
            if text.strip():
                pages.append({"page_number": page_num, "text": text, "char_count": len(text)})
    finally:
        doc.close()

    # Drop repeated running headers/footers before chunking so they do not
    # pollute every chunk (only verbatim lines that repeat in the
    # header/footer position on most pages are removed - see the helper).
    pages = _strip_repeated_headers_footers(pages)

    full_text = "\n\n".join(p["text"] for p in pages if p["text"].strip())
    logger.debug("Parsed PDF '%s': %d pages, %d chars", path.name, len(pages), len(full_text))

    return ParsedDocument(
        text=full_text,
        pages=pages,
        num_pages=len(pages),
        metadata={"filename": path.name, "format": "pdf"},
    )


def _parse_txt(path: Path) -> ParsedDocument:
    """Parse a plain text file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to read text file: {exc}") from exc

    text = _clean_text(text)
    logger.debug("Parsed TXT '%s': %d chars", path.name, len(text))

    return ParsedDocument(
        text=text,
        pages=[{"page_number": 1, "text": text, "char_count": len(text)}],
        num_pages=1,
        metadata={"filename": path.name, "format": "txt"},
    )


def _clean_text(text: str) -> str:
    """Basic text normalisation: collapse excessive whitespace."""
    import re
    # Collapse multiple blank lines into two
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove control characters except newlines/tabs
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    return text.strip()


def _strip_repeated_headers_footers(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove running headers/footers that repeat across pages.

    A line qualifies only when it appears in the first or last three lines
    of at least 60 % of the pages (and on at least two pages), is short
    enough to be a header/footer, and matches verbatim. Body content never
    repeats verbatim in header/footer position on most pages, so legal text
    is preserved; page numbers ("Page 3 of 12") differ per page and are
    therefore never touched either.

    Returns the pages with qualifying lines removed (empty pages dropped,
    page numbers of surviving pages unchanged).
    """
    if len(pages) < 3:
        return pages

    from collections import Counter

    first_counts: Counter = Counter()
    last_counts: Counter = Counter()
    for page in pages:
        lines = [ln.strip() for ln in page.get("text", "").splitlines() if ln.strip()]
        for ln in lines[:3]:
            first_counts[ln] += 1
        for ln in lines[-3:]:
            last_counts[ln] += 1

    threshold = max(2, int(0.6 * len(pages)))

    def repeated(counter) -> set:
        return {
            ln
            for ln, count in counter.items()
            if count >= threshold and len(ln) <= 120
        }

    drop = repeated(first_counts) | repeated(last_counts)
    if not drop:
        return pages

    cleaned: List[Dict[str, Any]] = []
    removed_any = False
    for page in pages:
        kept = [ln for ln in page.get("text", "").splitlines() if ln.strip() not in drop]
        new_text = _clean_text("\n".join(kept))
        if not new_text.strip():
            removed_any = True
            continue  # page held nothing but a running header/footer
        if new_text != page.get("text"):
            removed_any = True
        page = dict(page)
        page["text"] = new_text
        page["char_count"] = len(new_text)
        cleaned.append(page)

    if removed_any:
        logger.debug(
            "Stripped repeated header/footer lines on %d page(s): %d distinct line(s)",
            len(cleaned),
            len(drop),
        )
    return cleaned
