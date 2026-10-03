"""
Main FastAPI application for IP-SAKTI Sahayak.

Keeps application wiring only: app creation, middleware, router registration and
health endpoints. Business logic lives in app/services and app/routers.

Schema management: Alembic owns the database schema (see alembic/versions).
There is deliberately no ``Base.metadata.create_all`` here - creating tables at
startup would bypass migrations and silently drift from the migrated schema.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    auth_router,
    product_router,
    version_content_router,
    knowledge_router,
    assistant_router,
    analysis_router,
    ip_router,
    change_impact_router,
    disclosure_global_router,
    disclosure_version_router,
    overview_version_router,
    report_global_router,
    report_version_router,
    review_router,
    dashboard_router,
    audit_router,
    admin_router,
    bhashini_router,
    source_router,
    user_router,
)

settings = get_settings()

# Per-query RAG diagnostics (query expansion terms, retrieval-arm results,
# keyword/vector match counts, reranking, citation validation) are emitted at
# INFO by the app.* loggers. Uvicorn configures only its own loggers, so
# without this the root logger's WARNING default silently drops every line
# and the diagnostics never reach the server log. Client-visible responses
# stay clean: the `debug` payload still requires DEBUG=true.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="IP-SAKTI Sahayak",
    description=(
        "Multilingual RAG-based AI Assistant for Ayurveda IP and Regulatory Guidance. "
        "This platform provides preliminary, source-backed information and decision "
        "support. It does not constitute legal, patent, regulatory, medical, or "
        "government advice or approval."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(product_router)
app.include_router(version_content_router)
app.include_router(knowledge_router)
app.include_router(assistant_router)
app.include_router(analysis_router)
app.include_router(ip_router)
app.include_router(change_impact_router)
app.include_router(disclosure_version_router)
app.include_router(overview_version_router)
app.include_router(disclosure_global_router)
app.include_router(report_version_router)
app.include_router(report_global_router)
app.include_router(review_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.include_router(admin_router)
app.include_router(bhashini_router)
app.include_router(source_router)
app.include_router(user_router)


@app.get("/", tags=["Root"])
def root():
    """Root endpoint."""
    return {
        "message": "Welcome to IP-SAKTI Sahayak API",
        "docs": "/api/docs",
        "version": "1.0.0",
    }


@app.get("/api/health", tags=["Health"])
def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "service": "ip-sakti-sahayak",
        "version": "1.0.0",
        "phase": "13",
    }
