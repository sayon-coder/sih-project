"""
BHASHINI router (Phase 11). The language-access layer - never the reasoning layer.

  GET  /api/bhashini/languages   supported languages + glossary terms
  POST /api/bhashini/detect      script-based language detection
  POST /api/bhashini/translate   translation (honest fallback when unconfigured)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.bhashini.glossary import GLOSSARY, LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from app.bhashini.language_detector import detect_language
from app.bhashini.translator import translate
from app.schemas.schemas import APIResponse
from app.utils import verify_token

router = APIRouter(prefix="/api/bhashini", tags=["BHASHINI"])


class DetectRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source_language: str = "en"
    target_language: str = "en"


@router.get("/languages", response_model=APIResponse)
def list_languages(token_payload: dict = Depends(verify_token)):
    return APIResponse(
        success=True,
        data={
            "supported": [
                {"code": code, "name": LANGUAGE_NAMES[code]} for code in SUPPORTED_LANGUAGES
            ],
            "glossary_terms": sorted(GLOSSARY.keys()),
            "notes": (
                "RAG and analysis always run on the canonical representation; "
                "identifiers (patent numbers, URLs, DOIs, dates) are never translated."
            ),
        },
    )


@router.post("/detect", response_model=APIResponse)
def detect(request: DetectRequest, token_payload: dict = Depends(verify_token)):
    result = detect_language(request.text)
    return APIResponse(success=True, data=result)


@router.post("/translate", response_model=APIResponse)
def translate_text(request: TranslateRequest, token_payload: dict = Depends(verify_token)):
    try:
        output, translated, warning = translate(
            request.text, request.source_language, request.target_language
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return APIResponse(
        success=True,
        data={
            "output": output,
            "translated": translated,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "warning": warning,
        },
    )
