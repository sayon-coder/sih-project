"""
Report router (Phase 8b).

Version-scoped generation (ownership enforced through the product):

  POST /api/products/{product_id}/versions/{version_id}/reports/ip-brief
  POST /api/products/{product_id}/versions/{version_id}/reports/disclosure
  POST /api/products/{product_id}/versions/{version_id}/reports/expert-handoff
  GET  /api/products/{product_id}/versions/{version_id}/reports

Global access:

  GET  /api/reports/{report_id}         download the PDF (owner only)
  GET  /api/reports/{report_id}/verify  public verification payload (no auth)

Every PDF carries the platform disclaimers and a QR code to the verify URL.
"""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.report_models import ReportType
from app.schemas.schemas import APIResponse
from app.services.report_service import ReportService, serialize
from app.utils import verify_token

version_router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Reports"],
)

global_router = APIRouter(prefix="/api/reports", tags=["Reports"])


def _uid(token_payload: dict) -> int:
    return int(token_payload["sub"])


def _generate(product_id, version_id, report_type, token_payload, db, request):
    report = ReportService.generate(
        db, product_id, version_id, _uid(token_payload), report_type, request=request
    )
    return APIResponse(success=True, data=serialize(report), message="Report generated")


@version_router.post("/reports/ip-brief", response_model=APIResponse, status_code=201)
def generate_ip_brief(
    product_id: int,
    version_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Generate the IP Opportunity & Evidence Brief (preliminary, never conclusive)."""
    return _generate(product_id, version_id, ReportType.IP_BRIEF, token_payload, db, request)


@version_router.post("/reports/disclosure", response_model=APIResponse, status_code=201)
def generate_disclosure_record(
    product_id: int,
    version_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Generate the Invention Disclosure Record for this version's events."""
    return _generate(
        product_id, version_id, ReportType.DISCLOSURE_RECORD, token_payload, db, request
    )


@version_router.post("/reports/expert-handoff", response_model=APIResponse, status_code=201)
def generate_expert_handoff(
    product_id: int,
    version_id: int,
    request: Request,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Generate the Expert Handoff Package for this version."""
    return _generate(
        product_id, version_id, ReportType.EXPERT_HANDOFF, token_payload, db, request
    )


@version_router.get("/reports", response_model=APIResponse)
def list_reports(
    product_id: int,
    version_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reports = ReportService.list_for_version(db, product_id, version_id, _uid(token_payload))
    return APIResponse(
        success=True,
        data=[serialize(r) for r in reports],
        message=f"Found {len(reports)} report(s)",
    )


@global_router.get("/{report_id}")
def download_report(
    report_id: int,
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    report = ReportService.get(db, report_id, _uid(token_payload))
    pdf = ReportService.read_bytes(report)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{report.id}.pdf"'},
    )


@global_router.get("/{report_id}/verify", response_model=APIResponse)
def verify_report(report_id: int, db: Session = Depends(get_db)):
    """Public verification payload for QR checks - no authentication required."""
    from fastapi import HTTPException

    from app.models.report_models import Report as ReportModel

    report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return APIResponse(success=True, data=ReportService.verify_payload(report))
