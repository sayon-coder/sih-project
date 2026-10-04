"""
Clarifying questions router - the interactive classification loop.

``GET .../clarification-questions`` asks the minimum deterministic
questions for this version (spec order, genuine gaps only);
``GET/POST .../clarifications`` reads/records the answers. Recording an
answer never edits version content - facts belong in the Product Passport
editors.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User
from app.schemas.schemas import APIResponse
from app.services import clarification_service
from app.utils import get_current_user_model
from app.utils.authorization import get_accessible_version

version_router = APIRouter(
    prefix="/api/products/{product_id}/versions/{version_id}",
    tags=["Clarifications"],
)


class ClarificationAnswerIn(BaseModel):
    question_key: str = Field(..., min_length=1, max_length=100)
    answer: str = Field(..., min_length=1, max_length=4000)


@version_router.get("/clarification-questions", response_model=APIResponse)
def clarification_questions(
    product_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """Deterministic clarifying questions for this version, in spec order."""
    version = get_accessible_version(db, product_id, version_id, current_user.id)
    questions = clarification_service.get_questions(db, version)
    return APIResponse(
        success=True,
        data={
            "questions": questions,
            "count": len(questions),
            "answered": sum(1 for q in questions if q["answered"]),
        },
    )


@version_router.get("/clarifications", response_model=APIResponse)
def list_clarifications(
    product_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """Recorded clarification answers on this version, oldest first."""
    version = get_accessible_version(db, product_id, version_id, current_user.id)
    answers = clarification_service.list_answers(db, version)
    return APIResponse(
        success=True, data={"answers": answers, "count": len(answers)}
    )


@version_router.post(
    "/clarifications", response_model=APIResponse, status_code=201
)
def answer_clarification(
    product_id: int,
    version_id: int,
    body: ClarificationAnswerIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """Record (or update) the answer to one clarifying question."""
    version = get_accessible_version(db, product_id, version_id, current_user.id)
    try:
        row = clarification_service.submit_answer(
            db, version, current_user.id, body.question_key, body.answer
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return APIResponse(
        success=True,
        data=clarification_service.serialize(row),
        message="Clarification answer recorded.",
    )
