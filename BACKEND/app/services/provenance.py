"""
Provenance firewall (master prompt section 17: Claim-to-Evidence Firewall).

Provenance records *where a fact came from*, and the whole platform depends on
that record being trustworthy. Two rules make it trustworthy:

1. **The server assigns provenance, never the client.** A user may submit the
   text "increases bioavailability by 40%", but the API stores it as
   ``USER_PROVIDED``. Only later phases (AI analysis in Phase 5, expert review
   in Phase 9) may promote a record to ``AI_ANALYSIS`` / ``EXPERT_VERIFIED``.
2. **Verified data is protected.** Once a record is ``EXPERT_VERIFIED``, the
   ordinary user endpoints refuse to edit or delete it. A verified fact must not
   be silently overwritten by a later user edit.
"""
import enum
from typing import Any

from fastapi import HTTPException


class Provenance(str, enum.Enum):
    """Allowed provenance values, exactly as listed in the master prompt."""

    USER_PROVIDED = "USER_PROVIDED"
    PUBLIC_SOURCE = "PUBLIC_SOURCE"
    AI_ANALYSIS = "AI_ANALYSIS"
    EXPERT_VERIFIED = "EXPERT_VERIFIED"


#: Provenance values a request body is never allowed to set directly.
CLIENT_FORBIDDEN_PROVENANCE = {value.value for value in Provenance}

#: The provenance every record receives when a user creates it.
DEFAULT_PROVENANCE = Provenance.USER_PROVIDED.value

#: The provenance attached to anything an AI analysis produced (Phase 5).
AI_ANALYSIS_PROVENANCE = Provenance.AI_ANALYSIS.value

#: Evidence statuses a *user* may declare for a claim they typed in.
#:
#: ``SUPPORTED`` / ``PARTIALLY_SUPPORTED`` / ``EXPERT_VERIFIED`` are conclusions:
#: they may only be reached by evidence review or the expert workflow, never by
#: a client asserting them at creation time.
USER_SETTABLE_EVIDENCE_STATUSES = {"user_provided", "needs_evidence"}

#: Evidence statuses an *AI analysis* may propose for a claim (Phase 5).
#:
#: The AI may suggest that a claim still needs evidence, or that the corpus
#: partially supports it. It must never assert ``SUPPORTED`` or
#: ``EXPERT_VERIFIED``: those are conclusions that only evidence review or the
#: expert workflow (Phase 9) can reach. This is the machine counterpart of
#: ``USER_SETTABLE_EVIDENCE_STATUSES`` and the reason an AI run can never
#: silently upgrade a user's claim.
AI_MAX_EVIDENCE_STATUSES = {
    "user_provided",
    "needs_evidence",
    "partially_supported",
}

#: The most supportive status an AI run is ever allowed to suggest.
AI_SUGGESTED_CEILING = "partially_supported"


def is_expert_verified(record: Any) -> bool:
    """True when a record's provenance is EXPERT_VERIFIED."""
    return getattr(record, "provenance", None) == Provenance.EXPERT_VERIFIED.value


def ensure_mutable(record: Any, *, resource: str) -> None:
    """
    Refuse to modify a record whose provenance is EXPERT_VERIFIED.

    Raises:
        HTTPException: 409 Conflict, telling the caller to use the expert-review
            workflow instead of editing verified data in place.
    """
    if is_expert_verified(record):
        raise HTTPException(
            status_code=409,
            detail=(
                f"This {resource} is EXPERT_VERIFIED and cannot be modified directly. "
                "Submit the change through the expert review workflow so the verified "
                "record is preserved."
            ),
        )


def apply_user_provenance(record: Any) -> Any:
    """Stamp a newly created record as USER_PROVIDED."""
    record.provenance = DEFAULT_PROVENANCE
    return record


def clamp_ai_evidence_status(suggested: Any, *, fallback: str = "needs_evidence") -> str:
    """
    Clamp an AI-proposed evidence status into the AI-allowed set.

    Any value the model invents, or any attempt to claim ``SUPPORTED`` /
    ``EXPERT_VERIFIED``, collapses to something conservative rather than being
    accepted. Returning ``needs_evidence`` by default means an unparseable model
    answer can only ever make the platform *less* confident, never more.
    """
    value = suggested.value if isinstance(suggested, enum.Enum) else str(suggested or "")
    value = value.strip().lower()
    if value not in AI_MAX_EVIDENCE_STATUSES:
        return fallback
    return value


def resolve_evidence_status(declared: Any) -> str:
    """
    Normalise the evidence status a client asked for on a new claim.

    Any status outside the user-settable set is rejected rather than silently
    downgraded, so a client cannot quietly claim ``SUPPORTED``.
    """
    if declared is None:
        return "user_provided"

    value = declared.value if isinstance(declared, enum.Enum) else str(declared)
    if value not in USER_SETTABLE_EVIDENCE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"evidence_status '{value}' cannot be set by a user. Allowed values: "
                f"{sorted(USER_SETTABLE_EVIDENCE_STATUSES)}. Evidence support is "
                "established by evidence review, not by assertion."
            ),
        )
    return value
