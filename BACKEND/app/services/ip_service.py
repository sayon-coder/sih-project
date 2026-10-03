"""
IP screening service (Phase 6).

Owns the Phase 6 workflows and their persistence:

* ``get_ip_route_map``        - live, deterministic route map (read-only)
* ``search_patents``          - extract features, screen, persist candidate records
* ``list_patent_records``     - the records already identified for a version
* ``get_patent_record``       - one record, scoped to an accessible version
* ``compare_patents``         - re-compare a version against identified records
* ``screen_biodiversity``     - biodiversity/ABS screening
* ``screen_traditional_knowledge`` - traditional-knowledge screening

Safety rules carried over from Phase 5:

* the workflows are **advisory** - they never modify claims, evidence, ingredients
  or the formulation;
* every run is pinned to the exact version it reviewed;
* an AI/provider outage is not applicable here (the screening is deterministic),
  but a retrieval failure degrades to "no corpus sources" with an explicit
  warning rather than being hidden;
* results carry ``AI_ANALYSIS`` (machine-generated, not expert-verified)
  provenance.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.analysis.ip_routes import build_ip_route_map
from app.analysis.ip_schemas import human_jurisdiction, record_verification_fields
from app.analysis.patent_screening import build_patent_comparison, screen_patents
from app.analysis.screening import screen_biodiversity, screen_traditional_knowledge
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisType,
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    PatentFeature,
    PatentRecord,
    ProductVersion,
    TargetMarket,
)
from app.services.analysis_service import AnalysisService
from app.services.audit_service import AuditService
from app.services.version_content import load_version_content
from app.utils.authorization import get_accessible_version

logger = logging.getLogger(__name__)


class IPService:
    """Run and retrieve the Phase 6 IP screening workflows."""

    # ============================================
    # Shared helpers
    # ============================================

    @staticmethod
    def _version(db: Session, product_id: int, version_id: int, user_id: int) -> ProductVersion:
        return get_accessible_version(db, product_id, version_id, user_id)

    @staticmethod
    def _content(db: Session, version: ProductVersion) -> Dict[str, Any]:
        """Load the version content the screenings reason over."""
        return load_version_content(db, version)

    # ============================================
    # IP route map
    # ============================================

    @staticmethod
    def get_ip_route_map(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> Dict[str, Any]:
        """Build the route map live. Deterministic, so no persistence is needed."""
        version = IPService._version(db, product_id, version_id, user_id)
        content = IPService._content(db, version)
        result = build_ip_route_map(
            version.product,
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
        )
        return result.model_dump()

    # ============================================
    # Patent screening
    # ============================================

    @staticmethod
    def _persist_records(
        db: Session, version: ProductVersion, result_dict: Dict[str, Any]
    ) -> List[PatentRecord]:
        """Persist the identified candidate records and their features."""
        records: List[PatentRecord] = []
        for item in result_dict.get("records", []):
            record = PatentRecord(
                product_version_id=version.id,
                record_id=item["record_id"],
                patent_number=item.get("patent_number"),
                title=item["title"],
                assignee=item.get("assignee"),
                jurisdiction=item.get("jurisdiction"),
                publication_date=item.get("publication_date"),
                abstract=item.get("abstract"),
                source_url=item.get("source_url"),
                source_passage=item.get("source_passage"),
                record_source=item.get("record_source", "DEMO_CORPUS"),
                is_demo=item.get("is_demo", True),
                corpus_version=item.get("corpus_version"),
                relevance_label=item.get("relevance_label", "Further Review Recommended"),
                similarity=float(item.get("similarity", 0.0)),
                similarity_band=item.get("similarity_band", "none"),
                uncertainty=item.get("uncertainty"),
                provenance=item.get("provenance", "AI_ANALYSIS"),
            )
            for feature in item.get("features", []):
                record.features.append(
                    PatentFeature(
                        feature_type=feature["feature_type"],
                        feature_value=feature.get("patent_value") or "",
                        verdict=feature.get("verdict", "unknown"),
                        user_value=feature.get("user_value"),
                    )
                )
            db.add(record)
            records.append(record)
        db.commit()
        for record in records:
            db.refresh(record)
        return records

    @staticmethod
    def record_to_result(record: PatentRecord) -> Dict[str, Any]:
        """Convert a PatentRecord row into the API representation.

        The per-record verification status and visible label are derived from
        the stored row (spec item 6), so a verified public record inserted later
        surfaces correctly without changing this code.
        """
        verification = record_verification_fields(
            record.record_source, bool(record.is_demo)
        )
        return {
            "id": record.id,
            "record_id": record.record_id,
            "patent_number": record.patent_number,
            "title": record.title,
            "assignee": record.assignee,
            # Legacy rows stored the raw code ("IN"); render it human-readable
            # so no screen ever shows an ambiguous jurisdiction (spec item 7).
            "jurisdiction": human_jurisdiction(record.jurisdiction),
            "publication_date": record.publication_date,
            "abstract": record.abstract,
            "source_url": record.source_url,
            "source_passage": record.source_passage,
            "record_source": record.record_source,
            "is_demo": record.is_demo,
            "corpus_version": record.corpus_version,
            "verification_status": verification["verification_status"],
            "record_label": verification["record_label"],
            "relevance_label": record.relevance_label,
            "similarity": record.similarity,
            "similarity_band": record.similarity_band,
            "uncertainty": record.uncertainty or "",
            "provenance": record.provenance,
            "features": [
                {
                    "feature_type": f.feature_type,
                    "patent_value": f.feature_value,
                    "user_value": f.user_value,
                    "verdict": f.verdict,
                }
                for f in record.features
            ],
        }

    @staticmethod
    def search_patents(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        request=None,
    ) -> Analysis:
        """
        Screen a version, persist the identified records, and record the run.

        Returns the persisted ``Analysis`` row (type ``PATENT_SCREENING``).
        """
        version = IPService._version(db, product_id, version_id, user_id)
        content = IPService._content(db, version)

        result = screen_patents(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
        )
        result_dict = result.model_dump()

        records = IPService._persist_records(db, version, result_dict)
        # Reflect the real database ids back into the stored result.
        for item, record in zip(result_dict["records"], records):
            item["id"] = record.id

        recommendations = [
            f"Review candidate record {item['record_id']} ({item['relevance_label']}) "
            f"with a registered patent agent."
            for item in result_dict["records"]
        ] or [
            "No candidate record overlapped with this version in the demonstration "
            "corpus; a live patent search should still be carried out before any filing."
        ]

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.PATENT_SCREENING,
            status=AnalysisStatus.COMPLETED,
            results=result_dict,
            summary=(
                f"Patent screening identified {result_dict['record_count']} candidate "
                f"record(s) in the demonstration corpus (similarity indicator: "
                f"{result_dict['similarity_indicator']})."
            ),
            recommendations=recommendations,
            warnings=result_dict["warnings"],
            flags=["preliminary_screening", "demo_corpus"],
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="screen_patents",
            user_id=user_id,
            request=request,
        )

    @staticmethod
    def list_patent_records(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[Dict[str, Any]]:
        """Return the records already identified for a version, most similar first."""
        version = IPService._version(db, product_id, version_id, user_id)
        records = (
            db.query(PatentRecord)
            .filter(PatentRecord.product_version_id == version.id)
            .order_by(PatentRecord.similarity.desc(), PatentRecord.id.asc())
            .all()
        )
        return [IPService.record_to_result(record) for record in records]

    @staticmethod
    def get_patent_record(db: Session, patent_id: int, user_id: int) -> Dict[str, Any]:
        """Fetch one record, scoped to the version (and owner) it belongs to."""
        record = db.query(PatentRecord).filter(PatentRecord.id == patent_id).first()
        if record is None:
            raise HTTPException(status_code=404, detail="Patent record not found")

        version = record.product_version
        if version is None:
            raise HTTPException(status_code=404, detail="Patent record not found")
        # Re-use the ownership check: cross-user access becomes a 404.
        get_accessible_version(db, version.product_id, version.id, user_id)
        return IPService.record_to_result(record)

    @staticmethod
    def compare_patents(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        patent_record_ids: Optional[Sequence[int]] = None,
        request=None,
    ) -> Analysis:
        """
        Re-compare a version's current features against already-identified records.

        No new records are created; the comparison is recorded as an analysis run.
        """
        version = IPService._version(db, product_id, version_id, user_id)

        query = db.query(PatentRecord).filter(PatentRecord.product_version_id == version.id)
        if patent_record_ids:
            query = query.filter(PatentRecord.id.in_(list(patent_record_ids)))
        records = query.order_by(PatentRecord.similarity.desc(), PatentRecord.id.asc()).all()

        content = IPService._content(db, version)
        record_results = [IPService.record_to_result(record) for record in records]

        comparison = build_patent_comparison(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            _record_results_from_dicts(record_results),
        )
        comparison_dict = comparison.model_dump()

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.PATENT_SCREENING,
            status=AnalysisStatus.COMPLETED,
            results=comparison_dict,
            summary=(
                f"Feature comparison against {comparison_dict['record_count']} identified "
                f"record(s) (similarity indicator: {comparison_dict['similarity_indicator']})."
            ),
            recommendations=[
                "Confirm the comparison with a registered patent agent; it is a "
                "feature-overlap indication, not a freedom-to-operate or validity opinion."
            ],
            warnings=comparison_dict["warnings"],
            flags=["preliminary_screening", "demo_corpus"],
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="compare_patents",
            user_id=user_id,
            request=request,
        )

    # ============================================
    # Biodiversity / TK screening
    # ============================================

    @staticmethod
    def screen_biodiversity(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        include_sources: bool = False,
        request=None,
    ) -> Analysis:
        version = IPService._version(db, product_id, version_id, user_id)
        content = IPService._content(db, version)

        result = screen_biodiversity(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
            db=db,
            user_id=user_id,
            include_sources=include_sources,
        )
        result_dict = result.model_dump()

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.BIODIVERSITY_SCREENING,
            status=AnalysisStatus.COMPLETED,
            results=result_dict,
            summary=f"Biodiversity/ABS screening status: {result_dict['status_label']}.",
            recommendations=result_dict["review_questions"],
            warnings=result_dict["warnings"],
            flags=["preliminary_screening"],
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="screen_biodiversity",
            user_id=user_id,
            request=request,
        )

    @staticmethod
    def screen_traditional_knowledge(
        db: Session,
        product_id: int,
        version_id: int,
        user_id: int,
        include_sources: bool = False,
        request=None,
    ) -> Analysis:
        version = IPService._version(db, product_id, version_id, user_id)
        content = IPService._content(db, version)

        result = screen_traditional_knowledge(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
            db=db,
            user_id=user_id,
            include_sources=include_sources,
        )
        result_dict = result.model_dump()

        analysis = AnalysisService._persist(
            db,
            version=version,
            analysis_type=AnalysisType.TK_SCREENING,
            status=AnalysisStatus.COMPLETED,
            results=result_dict,
            summary=(
                f"Traditional-knowledge screening status: {result_dict['status_label']}."
            ),
            recommendations=result_dict["review_questions"],
            warnings=result_dict["warnings"],
            flags=["preliminary_screening"],
            user_id=user_id,
        )
        return AnalysisService._finalize(
            db,
            version=version,
            analysis=analysis,
            action="screen_traditional_knowledge",
            user_id=user_id,
            request=request,
        )


def _record_results_from_dicts(items: Sequence[Dict[str, Any]]):
    """Rebuild PatentRecordResult objects from serialized records."""
    from app.analysis.ip_schemas import PatentFeatureComparison, PatentRecordResult

    results = []
    for item in items:
        results.append(
            PatentRecordResult(
                **{
                    **item,
                    "features": [
                        PatentFeatureComparison(**feature) for feature in item.get("features", [])
                    ],
                }
            )
        )
    return results
