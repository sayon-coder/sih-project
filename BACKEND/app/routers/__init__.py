"""Routers package."""
from app.routers.auth import router as auth_router
from app.routers.products import router as product_router
from app.routers.version_content import router as version_content_router
from app.routers.knowledge import router as knowledge_router
from app.routers.assistant import router as assistant_router
from app.routers.analysis import router as analysis_router
from app.routers.ip import router as ip_router
from app.routers.change_impact import router as change_impact_router
from app.routers.disclosures import global_router as disclosure_global_router
from app.routers.disclosures import version_router as disclosure_version_router
from app.routers.overview import version_router as overview_version_router
from app.routers.reports import global_router as report_global_router
from app.routers.reports import version_router as report_version_router
from app.routers.reviews import router as review_router
from app.routers.bhashini import router as bhashini_router
from app.routers.dashboard import router as dashboard_router
from app.routers.audit import router as audit_router
from app.routers.admin import router as admin_router
from app.routers.sources import router as source_router
from app.routers.users import router as user_router

__all__ = [
    "auth_router",
    "product_router",
    "version_content_router",
    "knowledge_router",
    "assistant_router",
    "analysis_router",
    "ip_router",
    "change_impact_router",
    "disclosure_global_router",
    "disclosure_version_router",
    "overview_version_router",
    "report_global_router",
    "report_version_router",
    "review_router",
    "dashboard_router",
    "audit_router",
    "admin_router",
    "bhashini_router",
    "source_router",
    "user_router",
]
