"""
Text chunking for the RAG ingestion pipeline.

Strategy: recursive character splitting with sentence-boundary awareness.
Chunk size: 250 tokens (≈ 250 words for whitespace tokenisation).
Overlap:    40 tokens between adjacent chunks.

The page_number is propagated from the source ParsedDocument pages so that
citations can reference specific pages.
"""
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any

from app.rag.schemas import Chunk, ParsedDocument


# ------------------------------------------------------------------
# Simple whitespace-based token counter (approx.)
# Avoids a heavy tokenizer dependency; 1 token ≈ 1 word is close
# enough for chunk sizing at the document level.
# ------------------------------------------------------------------

def _approx_token_count(text: str) -> int:
    return len(text.split())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using a lightweight regex."""
    # Split at sentence endings: . ! ? followed by whitespace or end
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


# ------------------------------------------------------------------
# Section (heading) detection
# ------------------------------------------------------------------

_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+)*[\s.)]+\S")
_CAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 ,/&()'’\-]{4,79}$")


def _heading_of(line: str) -> Optional[str]:
    """Return a normalised section name when the line looks like a heading.

    Two conservative shapes are recognised: numbered headings
    ("4.2 Extraction Process") and short ALL-CAPS lines ("EXTRACTION
    PROCESS"). Detection only labels text - it never removes it - so a
    false positive can at worst add a section label to metadata.
    """
    s = line.strip()
    if not s or len(s) > 80:
        return None
    if s.endswith((".", "!", "?", ";", ",")):
        return None
    if _NUMBERED_HEADING_RE.match(s):
        return re.sub(r"\s+", " ", s)
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and _CAPS_HEADING_RE.match(s):
        return re.sub(r"\s+", " ", s)
    return None


def _split_page_with_sections(
    text: str, current_section: str
) -> tuple:
    """Split one page into ``(sentences, final_section)``.

    Each sentence carries the section (heading) it belongs to, so chunks
    can record ``metadata["section"]`` alongside ``page_number``. Blank
    lines are paragraph boundaries (flush); section state carries across
    pages because headings structure the whole document.
    """
    out: List[tuple] = []
    buffer: List[str] = []
    section = current_section

    def flush() -> None:
        if not buffer:
            return
        block = " ".join(ln.strip() for ln in buffer if ln.strip())
        for sent in _split_sentences(block):
            out.append((sent, section))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            buffer = []
            continue
        heading = _heading_of(line)
        if heading:
            flush()
            buffer = []
            section = heading
            buffer.append(line)  # headings are content too - keep them
        else:
            buffer.append(line)
    flush()
    return out, section


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def chunk_document(
    parsed: ParsedDocument,
    chunk_size: int = 250,
    chunk_overlap: int = 40,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> List[Chunk]:
    """Split a ParsedDocument into overlapping text chunks.

    Chunks respect sentence boundaries where possible.

    Parameters
    ----------
    parsed:
        The output of parser.parse_document().
    chunk_size:
        Target chunk size in approximate tokens (words).
    chunk_overlap:
        Overlap between consecutive chunks in approximate tokens.
    extra_metadata:
        Additional metadata fields to attach to every chunk.

    Returns
    -------
    Ordered list of Chunk objects.
    """
    chunks: List[Chunk] = []
    metadata = extra_metadata or {}

    if not parsed.pages:
        # Fallback: treat entire text as one page
        pages = [{"page_number": 1, "text": parsed.text}]
    else:
        pages = parsed.pages

    # Build a flat list of (sentence, page_number, section) triples.
    # Sections come from heading detection and carry across pages.
    sentence_pairs: List[tuple] = []
    section = ""
    for page_info in pages:
        page_num = page_info.get("page_number", 1)
        page_sentences, section = _split_page_with_sections(
            page_info.get("text", ""), section
        )
        for sent, sent_section in page_sentences:
            sentence_pairs.append((sent, page_num, sent_section))

    if not sentence_pairs:
        return []

    chunk_index = 0
    i = 0  # sentence index

    while i < len(sentence_pairs):
        # Accumulate sentences until we hit chunk_size tokens
        current_sentences: List[str] = []
        current_page: Optional[int] = sentence_pairs[i][1]
        current_section: str = sentence_pairs[i][2]
        token_count = 0

        j = i
        while j < len(sentence_pairs):
            sent, page, _sec = sentence_pairs[j]
            sent_tokens = _approx_token_count(sent)
            if token_count + sent_tokens > chunk_size and current_sentences:
                break
            current_sentences.append(sent)
            token_count += sent_tokens
            j += 1

        if not current_sentences:
            # Single sentence larger than chunk_size — include it anyway
            current_sentences = [sentence_pairs[i][0]]
            current_page = sentence_pairs[i][1]
            current_section = sentence_pairs[i][2]
            j = i + 1

        chunk_text = " ".join(current_sentences).strip()
        if not chunk_text:
            # Never index an empty chunk.
            i = max(i + 1, j)
            continue

        chunks.append(
            Chunk(
                text=chunk_text,
                chunk_index=chunk_index,
                page_number=current_page,
                token_count=_approx_token_count(chunk_text),
                metadata={**metadata, "section": current_section},
            )
        )
        chunk_index += 1

        # Advance with overlap: step back by overlap tokens worth of sentences
        overlap_tokens = 0
        step = j
        while step > i + 1:
            step -= 1
            overlap_tokens += _approx_token_count(sentence_pairs[step][0])
            if overlap_tokens >= chunk_overlap:
                break
        i = max(i + 1, step)  # always make forward progress

    return chunks
