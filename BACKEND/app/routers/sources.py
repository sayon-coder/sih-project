"""
Public sources router (master prompt section 7 — SOURCES).

  GET /api/sources             list corpus sources visible to the caller
  GET /api/sources/search      search sources (?q= title/author/type/jurisdiction)
  GET /api/sources/{source_id} fetch one source

Read-only and authenticated. Visibility follows the knowledge-base rule:
public documents plus the caller's own uploads (ADMIN sees everything).
Responses never expose file paths or document hashes.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import RoleName, User
from app.models.rag_models import SourceDocument
from app.schemas.schemas import APIResponse
from app.utils import get_current_user_model

router = APIRouter(prefix="/api/sources", tags=["Sources"])


class SourceOut(BaseModel):
    id: int
    title: str
    source_type: str
    jurisdiction: Optional[str] = None
    language: str
    author: Optional[str] = None
    publication_date: Optional[str] = None
    source_url: Optional[str] = None
    is_public: bool
    status: str
    chunk_count: int
    corpus_version: Optional[str] = None
    uploader_id: Optional[int] = None
    created_at: Optional[str] = None


def _visible_query(db: Session, user: User):
    """Public documents + the caller's own; ADMIN sees everything."""
    q = db.query(SourceDocument)
    roles = [r.role.name for r in user.roles]
    if RoleName.ADMIN not in roles:
        q = q.filter(
            (SourceDocument.is_public == True)  # noqa: E712
            | (SourceDocument.uploader_id == user.id)
        )
    return q


def _out(doc: SourceDocument) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "source_type": doc.source_type,
        "jurisdiction": doc.jurisdiction,
        "language": doc.language,
        "author": doc.author,
        "publication_date": str(doc.publication_date) if doc.publication_date else None,
        "source_url": doc.source_url,
        "is_public": doc.is_public,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "corpus_version": doc.corpus_version,
        "uploader_id": doc.uploader_id,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("", response_model=APIResponse)
def list_sources(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """List corpus sources the caller is allowed to see."""
    docs = (
        _visible_query(db, current_user)
        .order_by(SourceDocument.created_at.desc(), SourceDocument.id.desc())
        .limit(limit)
        .all()
    )
    return APIResponse(
        success=True,
        data=[_out(d) for d in docs],
        message=f"Found {len(docs)} source(s)",
    )


# NOTE: "/search" must be declared before "/{source_id}" so the literal path
# is matched first instead of being parsed as an integer id.
@router.get("/search", response_model=APIResponse)
def search_sources(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Search visible sources by title, author, source type or jurisdiction."""
    term = q.strip()
    pattern = f"%{term}%"
    docs = (
        _visible_query(db, current_user)
        .filter(
            or_(
                SourceDocument.title.ilike(pattern),
                SourceDocument.author.ilike(pattern),
                SourceDocument.source_type.ilike(pattern),
                SourceDocument.jurisdiction.ilike(pattern),
            )
        )
        .order_by(SourceDocument.created_at.desc(), SourceDocument.id.desc())
        .limit(limit)
        .all()
    )
    return APIResponse(
        success=True,
        data=[_out(d) for d in docs],
        message=f"Found {len(docs)} source(s) for '{term}'",
    )


@router.get("/{source_id}", response_model=APIResponse)
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Fetch a single source. Documents the caller may not see return 404."""
    doc = (
        _visible_query(db, current_user)
        .filter(SourceDocument.id == source_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return APIResponse(success=True, data=_out(doc))
