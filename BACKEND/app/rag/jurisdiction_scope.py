"""
Jurisdiction scope for market-entry answers.

The selected target markets of the Product Passport version in the chat
control source retrieval, prompt context, answer structure and citations:

  * India         -> India sources
  * Germany       -> Germany + applicable European Union sources
  * United States -> United States sources (only when selected)

Rules enforced here (chatbot market-launch spec):

  * a source tagged to an unselected jurisdiction is dropped before the
    model ever sees it, and every filtering event is logged;
  * untagged chunks (private uploads, general material) stay citable as
    general background - never as a market-entry requirement;
  * when a selected market has no supporting source, the answer must say
    so with an explicit evidence-gap sentence instead of silently
    substituting another country's law;
  * U.S. regulatory references are stripped from produced answers unless
    the United States is a selected target market.

Nothing in this module invents sources, approvals or legal conclusions.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.analysis.ip_schemas import human_jurisdiction
from app.rag.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


# -------------------------------------------------------
# Markets -> allowed jurisdictions
# -------------------------------------------------------

#: EU member states (their own name + the supranational "European Union"
#: are both allowed when such a market is selected).
EU_MEMBER_STATES = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia",
    "czech republic", "denmark", "estonia", "finland", "france", "germany",
    "greece", "hungary", "ireland", "italy", "latvia", "lithuania",
    "luxembourg", "malta", "netherlands", "poland", "portugal", "romania",
    "slovakia", "slovenia", "spain", "sweden",
}

#: Common aliases -> canonical country name.
_MARKET_ALIASES = {
    "usa": "United States",
    "u.s.a.": "United States",
    "us": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "deutschland": "Germany",
    "bharat": "India",
}

def canonical_market(name: str) -> str:
    """Canonical display name for a market/country string."""
    if not name or not str(name).strip():
        return ""
    cleaned = str(name).strip()
    alias = _MARKET_ALIASES.get(cleaned.casefold())
    if alias:
        return alias
    return cleaned


def market_display_label(market: str) -> str:
    """UI/answer label for a selected market (Germany is Germany/EU)."""
    if not market:
        return market
    if market.casefold() == "germany":
        return "Germany/EU"
    return market


def allowed_for_market(market: str) -> List[str]:
    """Jurisdiction labels a single selected market allows."""
    canonical = canonical_market(market)
    if not canonical:
        return []
    if canonical.casefold() in EU_MEMBER_STATES:
        return [canonical, "European Union"]
    return [canonical]


def allowed_jurisdictions(markets: Sequence[str]) -> List[str]:
    """Flattened, order-preserving, de-duplicated allowed jurisdiction list
    for the selected target markets (incl. applicable supranational ones)."""
    out: List[str] = []
    seen = set()
    for market in markets or ():
        for jur in allowed_for_market(market):
            key = _canon(jur)
            if key not in seen:
                seen.add(key)
                out.append(jur)
    return out


def markets_from_product_context(product_context: Optional[dict]) -> List[str]:
    """Selected target markets from the Product Passport snapshot.

    Handles both snapshot shapes: the metadata envelope
    (``{..., "content": {"target_markets": [...]}}``) and a legacy
    content-shaped snapshot (``{"target_markets": [...]}`` at the top).
    """
    if not product_context:
        return []
    snapshot = product_context.get("snapshot")
    if not isinstance(snapshot, dict):
        return []
    content = snapshot.get("content")
    content = content if isinstance(content, dict) else snapshot
    markets = content.get("target_markets") or []
    names: List[str] = []
    for row in markets:
        if not isinstance(row, dict):
            continue
        name = str(row.get("country") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def snapshot_content(product_context: Optional[dict]) -> dict:
    """The content document (ingredients/formulation/claims/...) of a
    product-context snapshot; {} when unavailable."""
    if not product_context:
        return {}
    snapshot = product_context.get("snapshot")
    if not isinstance(snapshot, dict):
        return {}
    content = snapshot.get("content")
    return content if isinstance(content, dict) else snapshot


# -------------------------------------------------------
# Scope matching
# -------------------------------------------------------

def _canon(value: Optional[str]) -> str:
    """Canonical comparable form of a jurisdiction label."""
    if not value or not str(value).strip():
        return ""
    stripped = str(value).strip()
    human = human_jurisdiction(stripped) or stripped
    human = human.strip().casefold()
    if human in ("eu", "europe", "european union"):
        return "european union"
    return human


#: Jurisdictions that are general international background rather than
#: any single country's law: citable as background, never counted as a
#: market-entry source (spec: "General international background - not a
#: market-entry requirement").
NEUTRAL_JURISDICTIONS = {"international"}


def chunk_in_scope(jurisdiction: Optional[str], allowed: Sequence[str]) -> bool:
    """True when a chunk may be shown to the model.

    Untagged chunks (jurisdiction empty) are general background and stay
    citable; tagged chunks must belong to the allowed list.
    """
    jur = (jurisdiction or "").strip()
    if not jur:
        return True
    canon = _canon(jur)
    if canon in NEUTRAL_JURISDICTIONS:
        return True
    return canon in {_canon(a) for a in allowed}


def apply_jurisdiction_scope(
    chunks: Sequence[RetrievedChunk],
    allowed: Sequence[str],
) -> Tuple[List[RetrievedChunk], List[Tuple[str, str]]]:
    """Split retrieved candidates into (in_scope, excluded).

    ``excluded`` is a list of ``(jurisdiction_label, title)`` for every
    out-of-scope tagged candidate. Filtering events are logged so a
    leaked source can be traced during debugging.
    """
    if not allowed:
        return list(chunks), []
    allowed_set = {_canon(a) for a in allowed}
    kept: List[RetrievedChunk] = []
    excluded: List[Tuple[str, str]] = []
    for chunk in chunks:
        jur = (chunk.jurisdiction or "").strip()
        canon = _canon(jur) if jur else ""
        if not jur or canon in NEUTRAL_JURISDICTIONS or canon in allowed_set:
            kept.append(chunk)
        else:
            excluded.append((human_jurisdiction(jur) or jur, chunk.title))
    if excluded:
        labels = sorted({label for label, _ in excluded})
        logger.info(
            "Jurisdiction scope [%s]: excluded %d candidate chunk(s) from %s",
            ", ".join(allowed),
            len(excluded),
            ", ".join(labels),
        )
    return kept, excluded


# -------------------------------------------------------
# Scope tracker: wrap the retriever, count, remember exclusions
# -------------------------------------------------------

class JurisdictionScopeTracker:
    """Wraps ``hybrid_retrieve`` so every retrieval honours the scope.

    Responsibilities:
      * drop out-of-scope candidates (and log each filtering event);
      * keep the final list at the configured depth so excluded chunks
        never starve in-scope ones of prompt slots;
      * count distinct sources per selected market (and private sources)
        for the response metadata;
      * record whether a private-document search actually executed.
    """

    def __init__(
        self,
        allowed_jurisdictions: Sequence[str] = (),
        market_scopes: Optional[Dict[str, Sequence[str]]] = None,
        private_doc_ids: Iterable[int] = (),
        final_k: int = 6,
        candidate_k: int = 18,
    ) -> None:
        self.allowed = list(allowed_jurisdictions or ())
        self.market_scopes: Dict[str, List[str]] = {
            label: list(juris or ())
            for label, juris in (market_scopes or {}).items()
        }
        self.private_doc_ids = {int(i) for i in private_doc_ids}
        self.final_k = final_k
        self.candidate_k = max(candidate_k, final_k)
        # title -> human jurisdiction label (deduped filtering events)
        self.excluded: Dict[str, str] = {}
        self.public_docs_by_market: Dict[str, set] = {
            label: set() for label in self.market_scopes
        }
        self.public_docs: set = set()
        self.private_docs: set = set()
        self.search_executed = False

    # -- counting -------------------------------------------------------
    def _count(self, chunks: Sequence[RetrievedChunk]) -> None:
        for chunk in chunks:
            doc_id = chunk.document_id
            if doc_id in self.private_doc_ids:
                self.private_docs.add(doc_id)
                continue
            self.public_docs.add(doc_id)
            jur = _canon(chunk.jurisdiction or "")
            if not jur:
                continue
            for label, juris in self.market_scopes.items():
                if jur in {_canon(j) for j in juris}:
                    self.public_docs_by_market.setdefault(label, set()).add(doc_id)
                    break

    def public_counts_by_market(self) -> Dict[str, int]:
        """Distinct public sources per selected market label."""
        return {
            label: len(ids)
            for label, ids in self.public_docs_by_market.items()
        }

    def excluded_labels(self) -> List[str]:
        """Human labels of every jurisdiction excluded this request."""
        return sorted(set(self.excluded.values()))

    # -- retrieval wrapper ----------------------------------------------
    def wrap(self, retrieve_fn: Callable) -> Callable:
        """Return a retrieve function with the scope applied."""
        allowed = self.allowed

        def _retrieve(db, query, filters=None, user_id=None, **kwargs):
            if allowed:
                # Over-retrieve so out-of-scope candidates cannot crowd
                # in-scope ones out of the reranked window.
                kwargs.setdefault("top_k_final", self.candidate_k)
            raw = list(
                retrieve_fn(
                    db=db, query=query, filters=filters, user_id=user_id, **kwargs
                )
            )
            if allowed:
                kept, excluded = apply_jurisdiction_scope(raw, allowed)
                for label, title in excluded:
                    self.excluded.setdefault(title, label)
                if len(kept) > self.final_k:
                    kept = kept[: self.final_k]
            else:
                kept = raw
            self._count(kept)
            self.search_executed = True
            return kept

        return _retrieve


# -------------------------------------------------------
# Prompt block (shared by both prompt builders)
# -------------------------------------------------------

def build_scope_block(scope: Optional[dict]) -> str:
    """The === MARKET CONTEXT === prompt block, or '' when no scope.

    Both the single-answer and the selective prompt builders prepend it,
    so the model always knows which markets it may rely on and how the
    answer must be structured.
    """
    if not scope:
        return ""
    markets = list(scope.get("selected_markets") or [])
    labels = list(scope.get("market_labels") or [])
    allowed = list(scope.get("allowed_jurisdictions") or [])
    if not allowed:
        return ""

    lines = ["=== MARKET CONTEXT (selected Product Passport target markets) ==="]
    if markets:
        lines.append("Selected target markets: " + ", ".join(markets))
    lines.append("Allowed source jurisdictions: " + ", ".join(allowed))

    counts: Dict[str, int] = {}
    provider = scope.get("counts_provider")
    if callable(provider):
        try:
            counts = provider() or {}
        except Exception:  # pragma: no cover - counts are best effort
            counts = {}
    if counts:
        rendered = ", ".join(f"{label}: {n}" for label, n in counts.items())
        lines.append("In-scope sources retrieved for this question: " + rendered)

    lines.append("")
    lines.append("Rules for this answer:")
    section_names = [f"\"{label}:\"" for label in (labels or [])]
    if len(section_names) > 1:
        sections_text = ", ".join(section_names[:-1]) + f" and {section_names[-1]}"
    else:
        sections_text = section_names[0] if section_names else ""
    if sections_text:
        lines.append(
            "1. For market-entry guidance structure the answer with separate "
            f"sections {sections_text} and \"Cross-market considerations:\" "
            "(add a section only for a selected market)."
        )
    else:
        lines.append(
            "1. For market-entry guidance structure the answer with one "
            "section per allowed jurisdiction plus a \"Cross-market "
            "considerations:\" section."
        )
    lines.append(
        "2. Cite only the passages above. Each passage label shows its "
        "jurisdiction; jurisdiction N/A means general background - not a "
        "market-entry requirement."
    )
    lines.append(
        "3. Never apply or cite the law of a jurisdiction outside the "
        "allowed list. Do not substitute one country's law for another's, "
        "and never silently replace a missing market-specific source with "
        "another country's rules."
    )
    lines.append(
        "4. When a selected market has no supporting passage above, state "
        "exactly: \"No verified <market>-specific source was retrieved for "
        "this answer.\" and list what is missing instead of broadening to "
        "another country."
    )
    lines.append(
        "5. Never state that the product is approved, launch-ready, "
        "compliant or legally cleared. Separate verified source-backed "
        "facts, user-provided product data from the PRODUCT CONTEXT, "
        "missing information and your own bounded guidance, and recommend "
        "qualified professional review."
    )
    lines.append(
        "6. Report every recorded claim with its provenance and evidence "
        "status. A USER_PROVIDED claim without attached independent "
        "evidence must not be called proven, clinically established or "
        "legally permitted; marketing use requires review."
    )
    missing = list(scope.get("missing_information") or [])
    if missing:
        lines.append(
            "7. Missing information for this product (state it in the "
            "answer): " + "; ".join(missing) + "."
        )
    if scope.get("launch_question"):
        market_sections = (
            ", ".join(f"\"{label}:\"" for label in labels)
            if labels
            else "\"India:\", \"Germany/EU:\""
        )
        lines.append(
            "8. This is a launch-readiness question: do not answer with an "
            "unsupported yes or no. Structure the answer as \"Launch "
            "readiness:\", \"What is known:\", \"Why a final launch "
            f"decision cannot yet be made:\", {market_sections}, "
            "\"Claim and evidence review:\", \"Biodiversity/source "
            "documentation:\", \"Required next steps:\", \"Professional "
            "review warning:\", \"Sources:\". Start with \"Launch "
            "readiness: Cannot be determined from the current "
            "information.\""
        )
    return "\n".join(lines)


# -------------------------------------------------------
# Question classification
# -------------------------------------------------------

_LAUNCH_RE = re.compile(
    r"\blaunch|\bgo to market\b|\bmarket entry\b|enter the market|"
    r"\bsell (it |this |my |our )?(product )?(in|to|into)\b",
    re.IGNORECASE,
)


def is_launch_question(query: str) -> bool:
    """True when the question asks about launching / market entry."""
    if not query:
        return False
    return bool(_LAUNCH_RE.search(query))


# -------------------------------------------------------
# Evidence sufficiency + gap sentences
# -------------------------------------------------------

LAUNCH_REASON = (
    "The current evidence does not establish the product category, "
    "market-specific requirements, manufacturing status, or claim "
    "substantiation."
)


def compute_evidence_status(
    *,
    launch_question: bool,
    per_market_counts: Dict[str, int],
    missing_information: Sequence[str],
    claims_need_review: bool,
) -> Dict[str, str]:
    """Deterministic evidence status for the market context.

    SUFFICIENT          - every selected market has jurisdiction-specific
                          sources and no important gap remains;
    PARTIALLY_SUPPORTED - sources exist for every market but gaps or
                          claim reviews remain;
    INSUFFICIENT         - at least one selected market has no
                          jurisdiction-specific source (or none exist).
    """
    market_counts = {
        k: v for k, v in (per_market_counts or {}).items()
        if k != "Private documents"
    }
    if not market_counts or any(v == 0 for v in market_counts.values()):
        overall = "INSUFFICIENT"
    elif missing_information or claims_need_review:
        overall = "PARTIALLY_SUPPORTED"
    else:
        overall = "SUFFICIENT"
    if launch_question:
        return {
            "overall_status": overall,
            "launch_decision": "CANNOT_BE_DETERMINED",
            "reason": LAUNCH_REASON,
        }
    return {
        "overall_status": overall,
        "launch_decision": "NOT_APPLICABLE",
        "reason": (
            "Evidence was assessed only against sources from the selected "
            "target markets."
        ),
    }


def no_source_sentence(market_names: Sequence[str]) -> str:
    """Rule-6 sentence: "No verified India- or Germany-specific source was
    retrieved for this answer." (one market: "No verified Germany-...")."""
    names = [n for n in (market_names or []) if n]
    if not names:
        return (
            "No verified market-specific source was retrieved for this "
            "answer."
        )
    phrase = "- or ".join(names)
    return f"No verified {phrase}-specific source was retrieved for this answer."


def launch_gap_sentence(market_labels: Sequence[str]) -> str:
    """The market-specific evidence-gap warning for launch questions."""
    labels = [l for l in (market_labels or []) if l]
    if not labels:
        labels = ["selected-market"]
    phrase = "- or ".join(labels)
    return (
        f"The verified corpus does not contain enough {phrase}-specific "
        "evidence to answer whether this product can be launched. Add "
        "verified sources or consult a qualified professional."
    )


def gap_warnings_for(
    *,
    per_market_counts: Dict[str, int],
    market_labels: Sequence[str],
    market_names: Dict[str, str],
    launch_question: bool,
) -> List[str]:
    """Explicit evidence-gap sentences for markets with no source.

    ``market_names`` maps the display label back to the country name used
    in the rule-6 sentence (Germany/EU -> Germany).
    """
    out: List[str] = []
    missing_names: List[str] = []
    for label in market_labels:
        if int(per_market_counts.get(label, 0)) == 0:
            missing_names.append(market_names.get(label, label))
    if missing_names:
        out.append(no_source_sentence(missing_names))
    total = sum(
        int(v) for k, v in (per_market_counts or {}).items()
        if k != "Private documents"
    )
    if launch_question and total == 0:
        out.append(launch_gap_sentence(market_labels))
    return out


# -------------------------------------------------------
# Claim standing (passport claims -> spec claim JSON)
# -------------------------------------------------------

def has_verified_evidence(content: dict) -> bool:
    """True when the version records at least one verified evidence doc."""
    for doc in (content or {}).get("evidence") or []:
        if str(doc.get("verification_status") or "").lower() == "verified":
            return True
    return False


def claim_standing(claim: dict, verified_evidence: bool) -> Dict[str, object]:
    """Spec claim JSON for one recorded Product Passport claim.

    Mirrors the deterministic standing used by the claim analysis
    (EXPERT_VERIFIED / USER_PROVIDED_ONLY / EVIDENCE_ON_RECORD) - never
    invented, never "proven".
    """
    claim_text = str(claim.get("claim_text") or "")
    provenance = str(claim.get("provenance") or "USER_PROVIDED")
    evidence_value = str(claim.get("evidence_status") or "").lower()
    base = {"claim_text": claim_text, "provenance": provenance}

    if provenance.upper() == "EXPERT_VERIFIED" or evidence_value == "expert_verified":
        return {
            **base,
            "evidence_status": "EXPERT_VERIFIED",
            "independent_verification": "EXPERT_VERIFIED",
            "marketing_use": "PROFESSIONAL_REVIEW_RECOMMENDED",
            "review_required": False,
            "reason": (
                "This claim is EXPERT_VERIFIED by the expert workflow; it "
                "is returned locked."
            ),
        }
    if not verified_evidence:
        return {
            **base,
            "evidence_status": "USER_PROVIDED_ONLY",
            "independent_verification": "NOT_FOUND",
            "marketing_use": "REVIEW_REQUIRED",
            "review_required": True,
            "reason": (
                "The claim was entered by the user and no independently "
                "verified supporting evidence was retrieved."
            ),
        }
    return {
        **base,
        "evidence_status": "EVIDENCE_ON_RECORD",
        "independent_verification": "EVIDENCE_ON_RECORD",
        "marketing_use": "REVIEW_REQUIRED",
        "review_required": True,
        "reason": (
            "Verified evidence is recorded on this version; confirm that it "
            "supports this specific claim before relying on it."
        ),
    }


# -------------------------------------------------------
# Missing information (deterministic, spec order)
# -------------------------------------------------------

_MISSING_ALWAYS = [
    "Manufacturing/licensing details",
    "Final label and marketing material",
]


def missing_information_for(
    content: dict, has_resolved_classification: bool
) -> List[str]:
    """Information the Product Passport still lacks, in spec order.

    Only genuinely absent items are reported; nothing is invented.
    """
    items: List[str] = []
    if not has_resolved_classification:
        items.append("Product category")
        items.append("Dosage form")
    items.append("Manufacturing/licensing details")

    formulation = (content or {}).get("formulation")
    complete = isinstance(formulation, dict) and all(
        formulation.get(key) not in (None, "")
        for key in ("solvent", "pressure", "duration", "concentration")
    )
    if not complete:
        items.append("Complete formulation")

    verified = has_verified_evidence(content)
    if not verified:
        items.append("Safety and quality evidence")
    claims = (content or {}).get("claims") or []
    if any(claim_standing(c, verified).get("review_required") for c in claims):
        items.append("Claim substantiation")
    items.append("Final label and marketing material")
    # de-dup, keep order
    seen = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


# -------------------------------------------------------
# U.S.-reference sanitizer
# -------------------------------------------------------

#: Strong markers of U.S. regulatory law. Matched only to remove U.S.
#: references from answers where the United States was NOT selected.
_US_REFERENCE_PATTERNS = [
    re.compile(r"\b21\s*C\.?\s?F\.?\s?R\b", re.IGNORECASE),
    re.compile(r"\bC\.?\s?F\.?\s?R\.?\s+Parts?\b", re.IGNORECASE),
    re.compile(r"\bU\.?\s?S\.?\s+FDA\b", re.IGNORECASE),
    re.compile(r"\bUS\s+FDA\b", re.IGNORECASE),
    re.compile(r"\bFood and Drug Administration\b", re.IGNORECASE),
]


def strip_unselected_us_references(
    answer: str, allowed_jurisdictions_: Sequence[str]
) -> Tuple[str, int]:
    """Remove sentences citing U.S. law when the U.S. is not selected.

    Returns ``(cleaned_answer, removed_count)``. No-op when the United
    States is an allowed jurisdiction or the answer is empty.
    """
    if not answer:
        return answer, 0
    allowed = {_canon(a) for a in (allowed_jurisdictions_ or [])}
    if "united states" in allowed:
        return answer, 0
    removed = 0
    cleaned_lines: List[str] = []
    for line in answer.split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        kept = [
            part for part in parts
            if not any(rx.search(part) for rx in _US_REFERENCE_PATTERNS)
        ]
        if len(kept) != len(parts):
            removed += len(parts) - len(kept)
        if kept:
            cleaned_lines.append(" ".join(kept))
    return "\n".join(cleaned_lines), removed
