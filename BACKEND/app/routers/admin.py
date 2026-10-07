"""
Admin router (Phase 10). Every route requires the ADMIN role (403 otherwise).

  GET    /api/admin/users            list users with roles
  GET    /api/admin/sources          list all corpus source records
  POST   /api/admin/sources          register a source record
  PUT    /api/admin/sources/{id}     update a source record
  DELETE /api/admin/sources/{id}     delete a source record
  GET    /api/admin/rag/status       corpus + embedding + demo-mode status
  GET    /api/admin/audit            full audit trail (?user_id=, ?limit=)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, Role, RoleName, SourceDocument, User, UserRole
from app.schemas.schemas import APIResponse
from app.utils import get_user_role_names, require_admin
from app.utils.cache import cache

router = APIRouter(prefix="/api/admin", tags=["Admin"])
settings = get_settings()


def _user_out(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "roles": sorted(get_user_role_names(db, user.id)),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _source_out(doc: SourceDocument) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "source_type": doc.source_type,
        "jurisdiction": doc.jurisdiction,
        "language": doc.language,
        "author": doc.author,
        "source_url": doc.source_url,
        "is_public": doc.is_public,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "corpus_version": doc.corpus_version,
        "uploader_id": doc.uploader_id,
    }


class SourceCreate(BaseModel):
    title: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    jurisdiction: Optional[str] = None
    language: str = "en"
    author: Optional[str] = None
    source_url: Optional[str] = None
    is_public: bool = False
    corpus_version: Optional[str] = None


class SourceUpdate(BaseModel):
    title: Optional[str] = None
    source_type: Optional[str] = None
    jurisdiction: Optional[str] = None
    language: Optional[str] = None
    author: Optional[str] = None
    source_url: Optional[str] = None
    is_public: Optional[bool] = None
    corpus_version: Optional[str] = None


@router.get("/users", response_model=APIResponse)
def list_users(
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.id.asc()).all()
    return APIResponse(
        success=True,
        data=[_user_out(db, u) for u in users],
        message=f"Found {len(users)} user(s)",
    )


@router.get("/sources", response_model=APIResponse)
def list_sources(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    docs = db.query(SourceDocument).order_by(SourceDocument.id.desc()).all()
    return APIResponse(success=True, data=[_source_out(d) for d in docs])


@router.post("/sources", response_model=APIResponse, status_code=201)
def create_source(
    body: SourceCreate,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = SourceDocument(
        title=body.title.strip(),
        source_type=body.source_type.strip(),
        jurisdiction=body.jurisdiction,
        language=body.language,
        author=body.author,
        source_url=body.source_url,
        is_public=body.is_public,
        corpus_version=body.corpus_version,
        uploader_id=int(admin["sub"]),
        status="PENDING",
        chunk_count=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return APIResponse(success=True, data=_source_out(doc), message="Source registered")


@router.put("/sources/{source_id}", response_model=APIResponse)
def update_source(
    source_id: int,
    body: SourceUpdate,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Source not found")
    for field in ("title", "source_type", "jurisdiction", "language", "author",
                  "source_url", "is_public", "corpus_version"):
        value = getattr(body, field)
        if value is not None:
            setattr(doc, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(doc)
    return APIResponse(success=True, data=_source_out(doc), message="Source updated")


@router.delete("/sources/{source_id}", response_model=APIResponse)
def delete_source(
    source_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(doc)
    db.commit()
    return APIResponse(success=True, data={"id": source_id}, message="Source deleted")


@router.get("/rag/status", response_model=APIResponse)
def rag_status(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    by_status = db.query(SourceDocument.status, func.count(SourceDocument.id)).group_by(
        SourceDocument.status
    ).all()
    chunks = db.query(func.coalesce(func.sum(SourceDocument.chunk_count), 0)).scalar()
    versions = [
        v for (v,) in db.query(SourceDocument.corpus_version)
        .filter(SourceDocument.corpus_version.isnot(None))
        .distinct().all()
    ]
    return APIResponse(
        success=True,
        data={
            "documents_total": sum(n for _, n in by_status),
            "documents_by_status": [{"status": s, "count": n} for s, n in by_status],
            "chunks_total": int(chunks or 0),
            "corpus_versions": versions,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "demo_mode": settings.demo_mode,
        },
    )


@router.get("/audit", response_model=APIResponse)
def admin_audit(
    user_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    entries = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit).all()
    return APIResponse(
        success=True,
        data=[
            {
                "id": e.id,
                "user_id": e.user_id,
                "action": e.action,
                "resource": e.resource,
                "resource_id": e.resource_id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in entries
        ],
        message=f"Found {len(entries)} audit entr(y/ies)",
    )


@router.get("/cache/stats", response_model=APIResponse)
def cache_stats(admin: dict = Depends(require_admin)):
    """Hit/miss counters per cache namespace (in-process; per worker)."""
    return APIResponse(success=True, data=cache.stats())


@router.post("/cache/clear", response_model=APIResponse)
def cache_clear(admin: dict = Depends(require_admin)):
    """Drop every cached entry (e.g. after a bulk corpus ingest)."""
    dropped = cache.clear()
    return APIResponse(
        success=True,
        data={"dropped_entries": dropped},
        message=f"Cleared {dropped} cached entr(y/ies)",
    )
