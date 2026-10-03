"""
Knowledge Base router.

Endpoints:
  GET    /api/knowledge/documents        — list documents
  POST   /api/knowledge/documents        — upload + ingest document
  GET    /api/knowledge/documents/{id}   — get document detail
  DELETE /api/knowledge/documents/{id}   — delete document (owner or ADMIN)
  POST   /api/knowledge/documents/{id}/reindex — re-run ingestion
  POST   /api/knowledge/index     — re-run ingestion for pending/failed docs
  GET    /api/knowledge/status           — corpus-wide statistics
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.utils import get_current_user_model
from app.config import get_settings
from app.database import get_db
from app.models.models import RoleName, User
from app.models.rag_models import SourceDocument
from app.rag.ingestion import ingest_document
from app.schemas.schemas import APIResponse
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


# -------------------------------------------------------
# Response schemas
# -------------------------------------------------------

class DocumentResponse(BaseModel):
    id: int
    title: str
    source_type: str
    jurisdiction: Optional[str]
    language: str
    author: Optional[str]
    publication_date: Optional[str]
    source_url: Optional[str]
    is_public: bool
    status: str
    chunk_count: int
    error_message: Optional[str]
    corpus_version: Optional[str]
    uploader_id: Optional[int]
    created_at: str

    class Config:
        from_attributes = True


class CorpusStatus(BaseModel):
    total_documents: int
    indexed_documents: int
    pending_documents: int
    failed_documents: int
    total_chunks: int
    public_documents: int
    private_documents: int
    demo_mode: bool


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _require_owner_or_admin(doc: SourceDocument, user: User) -> None:
    """Raise 403 if user is not the uploader and not an ADMIN."""
    user_roles = [r.role.name for r in user.roles]
    is_admin = RoleName.ADMIN in user_roles
    if not is_admin and doc.uploader_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to modify this document.")


def _save_upload(upload: UploadFile, settings) -> tuple[str, str, int]:
    """Save an uploaded file to disk. Returns (file_path, document_hash, size_bytes)."""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Stream to disk and compute hash simultaneously
    sha256 = hashlib.sha256()
    filename = upload.filename or "upload"
    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    safe_name = safe_name or "document"

    temp_path = upload_dir / f"tmp_{os.getpid()}_{safe_name}"
    size = 0
    with open(temp_path, "wb") as f:
        while chunk := upload.file.read(65536):
            f.write(chunk)
            sha256.update(chunk)
            size += len(chunk)

    document_hash = sha256.hexdigest()
    final_path = upload_dir / f"{document_hash[:16]}_{safe_name}"
    shutil.move(str(temp_path), str(final_path))

    return str(final_path.resolve()), document_hash, size


# -------------------------------------------------------
# Routes
# -------------------------------------------------------

@router.get("/status", response_model=CorpusStatus)
def get_corpus_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Return corpus-wide statistics."""
    from sqlalchemy import func
    settings = get_settings()

    total = db.query(SourceDocument).count()
    indexed = db.query(SourceDocument).filter(SourceDocument.status == "INDEXED").count()
    pending = db.query(SourceDocument).filter(SourceDocument.status.in_(["PENDING", "INDEXING"])).count()
    failed = db.query(SourceDocument).filter(SourceDocument.status == "FAILED").count()
    public = db.query(SourceDocument).filter(SourceDocument.is_public == True).count()
    private = total - public

    from app.models.rag_models import SourceChunk
    total_chunks = db.query(func.count(SourceChunk.id)).scalar() or 0

    return CorpusStatus(
        total_documents=total,
        indexed_documents=indexed,
        pending_documents=pending,
        failed_documents=failed,
        total_chunks=total_chunks,
        public_documents=public,
        private_documents=private,
        demo_mode=settings.demo_mode,
    )


@router.post("/index", response_model=APIResponse)
def index_pending_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Re-run ingestion for pending/failed documents the caller may modify.

    Regular users index their own uploads; ADMIN indexes the whole corpus.
    Records without a file on disk (for example admin source registrations)
    are skipped and reported honestly rather than silently ignored.
    """
    user_roles = [r.role.name for r in current_user.roles]
    is_admin = RoleName.ADMIN in user_roles

    q = db.query(SourceDocument).filter(
        SourceDocument.status.in_(["PENDING", "FAILED"])
    )
    if not is_admin:
        q = q.filter(SourceDocument.uploader_id == current_user.id)
    docs = q.order_by(SourceDocument.id.asc()).all()

    attempted = indexed = failed = skipped = 0
    for doc in docs:
        if not doc.file_path or not os.path.exists(doc.file_path):
            skipped += 1
            continue
        attempted += 1
        try:
            ingest_document(db, doc.id)
            indexed += 1
        except Exception:
            # ingest_document already stored FAILED status + error_message.
            logger.warning("Bulk indexing failed for document %d", doc.id)
            failed += 1

    return APIResponse(
        success=True,
        data={
            "attempted": attempted,
            "indexed": indexed,
            "failed": failed,
            "skipped": skipped,
        },
        message=(
            f"Indexed {indexed}/{attempted} document(s); "
            f"{failed} failed; {skipped} skipped (no file on disk)"
        ),
    )


@router.get("/documents", response_model=List[DocumentResponse])
def list_documents(
    source_type: Optional[str] = Query(None),
    is_public: Optional[bool] = Query(None),
    my_uploads_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """List documents. Admins see all; researchers see public + own."""
    user_roles = [r.role.name for r in current_user.roles]
    is_admin = RoleName.ADMIN in user_roles

    q = db.query(SourceDocument)
    if not is_admin:
        q = q.filter(
            (SourceDocument.is_public == True) |
            (SourceDocument.uploader_id == current_user.id)
        )
    if my_uploads_only:
        q = q.filter(SourceDocument.uploader_id == current_user.id)
    if source_type:
        q = q.filter(SourceDocument.source_type == source_type)
    if is_public is not None:
        q = q.filter(SourceDocument.is_public == is_public)

    docs = q.order_by(SourceDocument.created_at.desc()).all()
    return [_doc_to_response(d) for d in docs]


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    source_type: str = Form(...),
    jurisdiction: Optional[str] = Form(None),
    language: str = Form("en"),
    author: Optional[str] = Form(None),
    publication_date: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    is_public: bool = Form(False),
    corpus_version: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
    request: Request = None,
    settings=Depends(get_settings),
):
    """Upload and ingest a document (PDF or TXT)."""
    # Validate file type
    allowed_extensions = {".pdf", ".txt", ".text", ".md"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(allowed_extensions)}"
        )

    # Validate file size (rough check via content-length header)
    # Full check happens during streaming

    # Only ADMINs can publish public documents (others upload as private)
    user_roles = [r.role.name for r in current_user.roles]
    is_admin = RoleName.ADMIN in user_roles
    if is_public and not is_admin:
        is_public = False  # silently downgrade to private

    # Save to disk
    try:
        file_path, document_hash, size_bytes = _save_upload(file, settings)
    except Exception as exc:
        logger.error("File upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"File upload failed: {exc}")

    if size_bytes > settings.max_upload_size_bytes:
        os.remove(file_path)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB"
        )

    # Check for duplicate hash
    existing = db.query(SourceDocument).filter(SourceDocument.document_hash == document_hash).first()
    if existing:
        os.remove(file_path)
        raise HTTPException(
            status_code=409,
            detail=f"This document has already been uploaded (document_id={existing.id})."
        )

    # Create database record
    doc = SourceDocument(
        title=title,
        source_type=source_type,
        jurisdiction=jurisdiction,
        language=language,
        author=author,
        publication_date=publication_date,
        source_url=source_url,
        file_path=file_path,
        document_hash=document_hash,
        uploader_id=current_user.id,
        is_public=is_public,
        corpus_version=corpus_version,
        status="PENDING",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Ingest synchronously (for MVP; move to background task in production)
    try:
        doc = ingest_document(db, doc.id)
    except Exception as exc:
        logger.error("Ingestion failed for document %d: %s", doc.id, exc)
        # Status is already set to FAILED in ingest_document; just return the record

    # Audit: the knowledge base is user content, so every mutation is logged.
    AuditService.log_action(
        db=db,
        user_id=current_user.id,
        action="upload_document",
        resource="knowledge_document",
        resource_id=doc.id,
        details={
            "title": title,
            "source_type": source_type,
            "is_public": doc.is_public,
            "status": doc.status,
            "document_hash": doc.document_hash,
        },
        request=request,
    )

    return _doc_to_response(doc)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
):
    """Get a single document by ID."""
    doc = _get_accessible_doc(document_id, current_user, db)
    return _doc_to_response(doc)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
    request: Request = None,
):
    """Delete a document and all its chunks (owner or ADMIN)."""
    doc = _get_accessible_doc(document_id, current_user, db)
    _require_owner_or_admin(doc, current_user)

    # Capture the audit facts before the row disappears.
    audit_details = {
        "title": doc.title,
        "source_type": doc.source_type,
        "is_public": doc.is_public,
        "uploader_id": doc.uploader_id,
    }

    # Remove file from disk
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except Exception as exc:
            logger.warning("Could not delete file '%s': %s", doc.file_path, exc)

    db.delete(doc)
    db.commit()

    AuditService.log_action(
        db=db,
        user_id=current_user.id,
        action="delete_document",
        resource="knowledge_document",
        resource_id=document_id,
        details=audit_details,
        request=request,
    )


@router.post("/documents/{document_id}/reindex", response_model=DocumentResponse)
def reindex_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
    request: Request = None,
):
    """Re-run ingestion on an already-uploaded document (owner or ADMIN)."""
    doc = _get_accessible_doc(document_id, current_user, db)
    _require_owner_or_admin(doc, current_user)

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk. Cannot re-index.")

    doc = ingest_document(db, document_id)

    AuditService.log_action(
        db=db,
        user_id=current_user.id,
        action="reindex_document",
        resource="knowledge_document",
        resource_id=doc.id,
        details={"title": doc.title, "status": doc.status, "chunk_count": doc.chunk_count},
        request=request,
    )

    return _doc_to_response(doc)


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _get_accessible_doc(document_id: int, user: User, db: Session) -> SourceDocument:
    doc = db.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    user_roles = [r.role.name for r in user.roles]
    is_admin = RoleName.ADMIN in user_roles
    if not is_admin and doc.uploader_id != user.id and not doc.is_public:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


def _doc_to_response(doc: SourceDocument) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        source_type=doc.source_type,
        jurisdiction=doc.jurisdiction,
        language=doc.language,
        author=doc.author,
        publication_date=str(doc.publication_date) if doc.publication_date else None,
        source_url=doc.source_url,
        is_public=doc.is_public,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        corpus_version=doc.corpus_version,
        uploader_id=doc.uploader_id,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
    )
