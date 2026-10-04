"""
Clarification service - the interactive classification loop.

The problem statement requires the assistant to *"ask the minimum
clarifying questions"* to determine a formulation's category. Gap detection
is fully deterministic: the questions below are generated from the same
``missing_information_for`` list the chat uses (plus presence checks for an
empty ingredient/claim list), in spec order, so the assistant can never
invent a question.

Ask -> the answer is recorded (upsert per version + question key) -> the
gap list shrinks -> re-running analysis resolves the classification.
Recording an answer NEVER edits version content; facts belong in the
Product Passport editors, answers here are advisory notes with an audit
trail.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.clarification_models import ClarificationAnswer
from app.models.product_models import ProductVersion
from app.rag.jurisdiction_scope import missing_information_for
from app.services.audit_service import AuditService
from app.services.version_snapshot import build_version_snapshot
from app.services.overview_service import _has_resolved_classification


#: Deterministic question catalog. ``gap`` is the exact
#: ``missing_information_for`` item (None = presence check); ``section`` is
#: the Product Passport editor that records the fact.
QUESTION_CATALOG: List[Dict[str, Any]] = [
    {
        "key": "product_category",
        "gap": "Product category",
        "question": (
            "What is the intended use of this product, and which regulatory "
            "category does it fall in - classical/generic medicine, "
            "patent-or-proprietary medicine, new (non-classical) drug, "
            "phytopharmaceutical, Ayurveda-Aahar/nutraceutical, or cosmetic?"
        ),
        "section": "analysis",
        "hint": "Record the category, then run a full analysis to confirm it.",
    },
    {
        "key": "dosage_form",
        "gap": "Dosage form",
        "question": (
            "What is the dosage form of this product "
            "(for example tablet, capsule, syrup, oil, powder or granules)?"
        ),
        "section": "formulation",
        "hint": "Record it in the formulation editor of this version.",
    },
    {
        "key": "manufacturing_licensing",
        "gap": "Manufacturing/licensing details",
        "question": (
            "Where and under which manufacturing licence is (or will) this "
            "product be made - own licensed premises, loan licence, or "
            "third-party manufacturer?"
        ),
        "section": "formulation",
        "hint": "Record the manufacturing arrangement in the formulation editor.",
    },
    {
        "key": "complete_formulation",
        "gap": "Complete formulation",
        "question": (
            "What are the complete process parameters - solvent, pressure, "
            "duration and concentration (extraction method and conditions)?"
        ),
        "section": "formulation",
        "hint": "Fill every process field in the formulation editor.",
    },
    {
        "key": "safety_quality_evidence",
        "gap": "Safety and quality evidence",
        "question": (
            "What safety and quality evidence supports this product "
            "(pharmacopoeial monographs, test reports, stability data, "
            "published studies)?"
        ),
        "section": "evidence",
        "hint": "Attach each document as evidence on this version.",
    },
    {
        "key": "claim_substantiation",
        "gap": "Claim substantiation",
        "question": (
            "Which recorded claim still needs substantiation, and what "
            "evidence supports it?"
        ),
        "section": "claims",
        "hint": "Review each claim against its evidence in the claims editor.",
    },
    {
        "key": "final_label",
        "gap": "Final label and marketing material",
        "question": (
            "What are the exact label claims and marketing statements "
            "planned for this product?"
        ),
        "section": "claims",
        "hint": "Record the exact wording as claims; advertising must stay verifiable.",
    },
    {
        "key": "intended_claims",
        "gap": None,
        "question": (
            "What claims do you intend to make for this product "
            "(health benefit, ingredient characterisation, or usage)?"
        ),
        "section": "claims",
        "hint": "No claims are recorded yet - add the first one in the claims editor.",
        "when_empty": "claims",
    },
    {
        "key": "ingredient_list",
        "gap": None,
        "question": (
            "Which ingredients (botanical species, plant part, quantity, "
            "source) does this formulation contain?"
        ),
        "section": "ingredients",
        "hint": "No ingredients are recorded yet - add them in the ingredients editor.",
        "when_empty": "ingredients",
    },
]


def _content_of(version: ProductVersion) -> Dict[str, Any]:
    """Fresh content document for gap detection (same shape chat uses)."""
    try:
        snapshot = build_version_snapshot(version)
    except Exception:
        snapshot = {}
    if isinstance(snapshot, dict):
        content = snapshot.get("content")
        if isinstance(content, dict):
            return content
        return snapshot
    return {}


def get_questions(db: Session, version: ProductVersion) -> List[Dict[str, Any]]:
    """Deterministic clarifying questions for this version, in spec order.

    Only genuine gaps produce questions. Each carries its answered state so
    the UI can show progress and the loop can terminate.
    """
    content = _content_of(version)
    resolved = _has_resolved_classification(db, version.id)
    gaps = missing_information_for(content, resolved)

    answered = {
        row.question_key: row
        for row in db.query(ClarificationAnswer)
        .filter(ClarificationAnswer.product_version_id == version.id)
        .all()
    }

    questions: List[Dict[str, Any]] = []
    for item in QUESTION_CATALOG:
        if item.get("when_empty") == "claims" and (content.get("claims") or []):
            continue
        if item.get("when_empty") == "ingredients" and (
            content.get("ingredients") or []
        ):
            continue
        if item.get("gap") is not None and item["gap"] not in gaps:
            continue
        row = answered.get(item["key"])
        questions.append(
            {
                "question_key": item["key"],
                "question_text": item["question"],
                "gap_item": item.get("gap"),
                "destination": {
                    "section": item["section"],
                    "hint": item["hint"],
                },
                "answered": row is not None,
                "answer": row.answer if row else None,
                "answered_at": row.answered_at.isoformat() if row and row.answered_at else None,
            }
        )
    return questions


def submit_answer(
    db: Session,
    version: ProductVersion,
    user_id: int,
    question_key: str,
    answer_text: str,
) -> ClarificationAnswer:
    """Record (upsert) the user's answer to one clarifying question.

    Raises ``KeyError`` for an unknown key and ``ValueError`` for an empty
    answer. Never edits version content.
    """
    known = {item["key"] for item in QUESTION_CATALOG}
    if question_key not in known:
        raise KeyError(f"Unknown clarifying question: {question_key!r}")
    text = (answer_text or "").strip()
    if not text:
        raise ValueError("An answer is required.")

    row = (
        db.query(ClarificationAnswer)
        .filter(
            ClarificationAnswer.product_version_id == version.id,
            ClarificationAnswer.question_key == question_key,
        )
        .first()
    )
    if row is None:
        question_text = next(
            item["question"] for item in QUESTION_CATALOG if item["key"] == question_key
        )
        row = ClarificationAnswer(
            product_version_id=version.id,
            user_id=user_id,
            question_key=question_key,
            question_text=question_text,
            answer=text,
        )
        db.add(row)
    else:
        row.answer = text
        row.user_id = user_id
    db.commit()
    db.refresh(row)

    AuditService.log_action(
        db,
        user_id=user_id,
        action="clarification_answer",
        resource="product_version",
        resource_id=version.id,
        details={"question_key": question_key},
    )
    return row


def serialize(row: ClarificationAnswer) -> Dict[str, Any]:
    """JSON-safe representation of one stored answer."""
    return {
        "id": row.id,
        "product_version_id": row.product_version_id,
        "question_key": row.question_key,
        "question_text": row.question_text,
        "answer": row.answer,
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
    }


def list_answers(db: Session, version: ProductVersion) -> List[Dict[str, Any]]:
    """All recorded answers on this version, oldest first."""
    rows = (
        db.query(ClarificationAnswer)
        .filter(ClarificationAnswer.product_version_id == version.id)
        .order_by(ClarificationAnswer.id)
        .all()
    )
    return [serialize(row) for row in rows]
