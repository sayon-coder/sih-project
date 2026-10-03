"""Agentic multi-source orchestration (Stage 2 of the staged build).

:func:`run_agent` is a *real* multi-step loop, not one LLM call per
sub-question::

    plan -> execute step tool(s) -> observe -> decide (continue / answer /
    abstain) -> synthesise -> validate citations -> score confidence ->
    persist the run

Guarantees, each exercised by ``tests/test_graph_agent.py``:

* **Step budget.** The plan is capped at ``max_steps`` (hard ceiling
  ``MAX_PLAN_STEPS``) before execution; the loop can never exceed it.
* **Per-tool error isolation.** One failing tool never aborts the run:
  :func:`app.agents.tools.execute_tool` converts handler crashes into
  ``ok=False`` and the loop continues to the next step.
* **Abstention.** When no substantive evidence was gathered the answer is
  exactly ``app.rag.citation.INSUFFICIENT_EVIDENCE_MESSAGE`` and
  ``insufficient_evidence`` is True - the same controlled response the RAG
  pipeline returns.
* **Citations.** Corpus citations are only kept after
  ``app.rag.citation.validate_citations`` verified them against the chunks
  that were actually retrieved. The failure semantics mirror
  ``app.rag.generation``: *model cited nothing* -> keep the answer with an
  honest warning; *model cited only unverifiable sources* -> abstain; *some
  invalid* -> keep the valid ones and warn. Anything the corpus cannot back
  is never cited.
* **No fabricated authority.** The deterministic synthesiser only quotes
  retrieved passages and recorded tool output. An LLM draft containing a
  conclusive statement (``CONCLUSIVE_PHRASE_PATTERNS``) is discarded and
  replaced by the evidence-only summary.
* **Deterministic confidence.** :func:`derive_confidence` is a pure function
  of observable evidence counts - never a model judgement.
* **Disclaimer.** ``DISCLAIMER`` is returned verbatim on every result.
* **Persistence.** Every run is stored in ``agent_runs`` so
  ``GET /api/agent/traces`` can show what actually happened.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.database import Base
from app.graph.schema import GRAPH_REVIEW_NOTE
from app.llm.schemas import CitationObject

logger = logging.getLogger(__name__)

#: Verbatim platform disclaimer - identical text everywhere, never reworded.
DISCLAIMER = (
    "This platform provides preliminary, source-backed information and decision support. "
    "It does not constitute legal, patent, regulatory, medical, or government advice or approval."
)

#: Ceiling on plan length (shared with the planner).
MAX_PLAN_STEPS = 5


# ============================================================
# Persisted run record
# ============================================================

class AgentRun(Base):
    """One persisted agent run: question, answer, plan, trace and scores.

    Registered with ``Base.metadata`` when this module is imported (the graph
    router imports it, so ``alembic`` sees the table once the router is
    registered in ``app/main.py``).
    """

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_version_id = Column(
        Integer,
        ForeignKey("product_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    plan_json = Column(Text, nullable=True)
    trace_json = Column(Text, nullable=True)
    citations_json = Column(Text, nullable=True)
    sources_json = Column(Text, nullable=True)
    graph_paths_json = Column(Text, nullable=True)
    warnings_json = Column(Text, nullable=True)
    confidence = Column(String(10), nullable=False, default="LOW")
    confidence_reason = Column(Text, nullable=True)
    insufficient_evidence = Column(Boolean, nullable=False, default=False)
    review_required = Column(Boolean, nullable=False, default=True)
    steps_used = Column(Integer, nullable=False, default=0)
    max_steps = Column(Integer, nullable=False, default=5)
    duration_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<AgentRun(id={self.id}, user_id={self.user_id}, "
            f"confidence={self.confidence}, steps={self.steps_used})>"
        )


# ============================================================
# Result schemas
# ============================================================

class AgentTrace(BaseModel):
    """One tool invocation as it actually happened."""

    step: int
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    result_summary: str = ""
    warning: Optional[str] = None
    ms: int = 0


class AgentResult(BaseModel):
    """Everything one orchestrator run produced."""

    answer: str
    plan: Dict[str, Any] = Field(default_factory=dict)
    trace: List[AgentTrace] = Field(default_factory=list)
    citations: List[CitationObject] = Field(default_factory=list)
    sources_used: List[Dict[str, Any]] = Field(default_factory=list)
    graph_paths: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: str = "LOW"  # HIGH | MEDIUM | LOW
    confidence_reason: str = ""
    insufficient_evidence: bool = False
    disclaimer: str = DISCLAIMER
    review_required: bool = True
    warnings: List[str] = Field(default_factory=list)
    steps_used: int = 0
    max_steps: int = MAX_PLAN_STEPS
    run_id: Optional[int] = None
    duration_ms: int = 0


# ============================================================
# No-conclusive-statement guard
# ============================================================

#: Sentences matching these patterns are conclusive legal/regulatory claims
#: the platform is never allowed to produce. They are removed from model
#: output and from evidence excerpts before anything reaches the user.
CONCLUSIVE_PHRASE_PATTERNS: Sequence[re.Pattern] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bis patentable\b",
        r"\bare patentable\b",
        r"\bnot patentable\b",
        r"\bunpatentable\b",
        r"\bwill be granted\b",
        r"\bwill be approved\b",
        r"\bis approved\b",
        r"\byou are eligible\b",
        r"\bis eligible\b",
        r"\beligible for a patent\b",
        r"\byou can file\b",
        r"\byou should file\b",
        r"\byou may proceed\b",
        r"\bdoes not infringe\b",
        r"\bguaranteed\b",
        r"\bsafe and effective\b",
        r"\bis compliant\b",
        r"\bfully compliant\b",
        r"\blegally binding\b",
        r"\bno legal risk\b",
        r"\bfree to use\b",
    )
)


def contains_conclusive_phrase(text: str) -> bool:
    """True when ``text`` states a conclusion the platform must not state."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in CONCLUSIVE_PHRASE_PATTERNS)


def strip_conclusive_sentences(text: str) -> Tuple[str, int]:
    """Remove conclusive sentences; returns ``(clean_text, removed_count)``."""
    if not text:
        return text, 0
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = [s for s in sentences if not contains_conclusive_phrase(s)]
    return "\n".join(kept).strip(), len(sentences) - len(kept)


# ============================================================
# Confidence - deterministic, documented
# ============================================================

def derive_confidence(
    *,
    chunk_count: int = 0,
    graph_hit: bool = False,
    product_hit: bool = False,
    citation_count: int = 0,
    path_count: int = 0,
    failure_count: int = 0,
    sufficient: bool = True,
) -> Dict[str, Any]:
    """Derive the HIGH/MEDIUM/LOW indicator from evidence counts alone.

    Scoring (pure arithmetic, no model involved)::

        +2  corpus evidence   (>= 1 retrieved passage)
        +2  graph evidence    (knowledge-graph node or path matched)
        +2  product evidence  (route map / classification / screening returned data)
        +2  >= 3 validated citations      (+1 when 1-2, +0 when none)
        +1  >= 1 relational path (graph_paths)
        -1  per failed step

    Classification::

        insufficient evidence (abstained) -> LOW
        score >= 6 AND citations >= 3     -> HIGH
        score >= 3                        -> MEDIUM
        otherwise                         -> LOW
    """
    score = 0
    if chunk_count >= 1:
        score += 2
    if graph_hit:
        score += 2
    if product_hit:
        score += 2
    if citation_count >= 3:
        score += 2
    elif citation_count >= 1:
        score += 1
    if path_count >= 1:
        score += 1
    score -= max(0, int(failure_count))

    if not sufficient:
        return {
            "confidence": "LOW",
            "score": score,
            "reason": (
                "abstained: no substantive evidence was gathered "
                f"(chunks={chunk_count}, graph_hit={graph_hit}, product_hit={product_hit})"
            ),
        }
    if score >= 6 and citation_count >= 3:
        band = "HIGH"
    elif score >= 3:
        band = "MEDIUM"
    else:
        band = "LOW"
    reason = (
        f"score={score}: chunks={chunk_count}, citations={citation_count}, "
        f"graph_hit={graph_hit}, product_hit={product_hit}, paths={path_count}, "
        f"failed_steps={max(0, int(failure_count))}"
    )
    return {"confidence": band, "score": score, "reason": reason}


# ============================================================
# Observation of tool results
# ============================================================

def _chunks_from_payload(payload: Dict[str, Any]) -> List[Any]:
    """Rebuild ``RetrievedChunk`` objects from a ``retrieve_corpus`` payload."""
    from app.rag.schemas import RetrievedChunk  # local: keeps module import light

    chunks: List[RetrievedChunk] = []
    for item in payload.get("chunks") or []:
        if not isinstance(item, dict) or item.get("chunk_id") is None:
            continue
        try:
            chunks.append(
                RetrievedChunk(
                    chunk_id=int(item["chunk_id"]),
                    document_id=int(item.get("document_id") or 0),
                    title=str(item.get("title") or ""),
                    source_type=str(item.get("source_type") or "other"),
                    jurisdiction=item.get("jurisdiction"),
                    source_url=item.get("source_url"),
                    publication_date=item.get("publication_date"),
                    text=str(item.get("text") or ""),
                    page_number=item.get("page_number"),
                    final_score=float(item.get("final_score") or 0.0),
                )
            )
        except (TypeError, ValueError):  # pragma: no cover - malformed tool data
            continue
    return chunks


def _tag_paths(paths: Any, source: str) -> List[Dict[str, Any]]:
    """Tag path dicts with where they came from (provenance for the API)."""
    out: List[Dict[str, Any]] = []
    for path in paths or []:
        if isinstance(path, dict):
            tagged = dict(path)
            tagged.setdefault("source", source)
            tagged.setdefault("review_required", True)
            out.append(tagged)
    return out


class _Observations:
    """Accumulates what every successful tool returned."""

    def __init__(self) -> None:
        self.chunks: List[Any] = []
        self.kg_node_count = 0
        self.kg_edge_count = 0
        self.kg_node_names: List[str] = []
        self.kg_paths: List[Dict[str, Any]] = []
        self.product_paths: List[Dict[str, Any]] = []
        self.product_hits: List[str] = []
        self.route_map: Optional[Dict[str, Any]] = None
        self.classification: Optional[Dict[str, Any]] = None
        self.screening: Optional[Dict[str, Any]] = None
        self.reference: Optional[Dict[str, Any]] = None
        self.failures = 0
        self.tool_warnings: List[str] = []

    # -- classification of one successful tool result ----------------------
    def observe(self, tool: str, data: Any) -> None:
        if not isinstance(data, dict):
            return
        if tool == "retrieve_corpus":
            self.chunks.extend(_chunks_from_payload(data))
        elif tool == "query_knowledge_graph":
            if data.get("mode") == "path":
                self.kg_paths.extend(_tag_paths(data.get("paths"), "tool:query_knowledge_graph"))
            else:
                context = data.get("context") or {}
                self.kg_node_count += int(context.get("node_count") or 0)
                self.kg_edge_count += int(context.get("edge_count") or 0)
                for node in context.get("nodes") or []:
                    name = node.get("canonical_name") if isinstance(node, dict) else None
                    if name and name not in self.kg_node_names:
                        self.kg_node_names.append(str(name))
                self.kg_paths.extend(_tag_paths(data.get("paths"), "tool:query_knowledge_graph"))
        elif tool in ("ip_route_map", "classify_formulation", "biodiversity_screen"):
            if tool not in self.product_hits:
                self.product_hits.append(tool)
            if tool == "ip_route_map":
                self.route_map = data
            elif tool == "classify_formulation":
                self.classification = data
            else:
                self.screening = data
        elif tool == "official_sources_for":
            # Reference metadata: useful context, but never sufficient on its
            # own to answer a substantive question (it is static registry data).
            self.reference = data

    # -- derived -----------------------------------------------------------
    @property
    def graph_hit(self) -> bool:
        return bool(self.kg_node_count or self.kg_paths or self.product_paths)

    @property
    def graph_paths(self) -> List[Dict[str, Any]]:
        return list(self.kg_paths) + list(self.product_paths)

    @property
    def substantive(self) -> bool:
        """True when at least one source of *substantive* evidence exists."""
        return bool(self.chunks) or self.graph_hit or bool(self.product_hits)


def _summarize(tool: str, result: Dict[str, Any]) -> str:
    """Short human summary of one tool result for the trace."""
    if not result.get("ok"):
        text = f"failed: {result.get('warning') or 'unknown error'}"
        return text[:300]
    data = result.get("data")
    if not isinstance(data, dict):
        text = "ok"
    elif tool == "retrieve_corpus":
        text = f"{data.get('count', 0)} passage(s) retrieved"
    elif tool == "query_knowledge_graph":
        paths = len(data.get("paths") or [])
        if data.get("mode") == "path":
            text = f"{paths} path(s) between the named concepts"
        else:
            context = data.get("context") or {}
            text = (
                f"{context.get('node_count', 0)} node(s), "
                f"{context.get('edge_count', 0)} edge(s), {paths} path(s)"
            )
    elif tool == "ip_route_map":
        text = (
            f"{len(data.get('routes') or [])} route(s), "
            f"{len(data.get('missing_information') or [])} missing-information item(s)"
        )
    elif tool == "classify_formulation":
        text = f"status={data.get('status')}, category={data.get('category')}"
    elif tool == "biodiversity_screen":
        text = f"status={data.get('status')}"
    elif tool == "official_sources_for":
        text = (
            f"{len(data.get('instruments') or [])} instrument(s), "
            f"{len(data.get('registry_sources') or [])} registry source(s)"
        )
    else:  # pragma: no cover - future tool
        text = "ok"
    return text[:300]


def _decide(obs: _Observations, *, budget_exhausted: bool) -> str:
    """Observe -> decide: ``continue`` while budget remains, otherwise
    ``answer`` when substantive evidence exists, else ``abstain``."""
    if not budget_exhausted:
        return "continue"
    return "answer" if obs.substantive else "abstain"


# ============================================================
# Synthesis
# ============================================================

def _excerpt(text: str, limit: int = 300) -> str:
    """Single-line excerpt with conclusive phrasing removed."""
    clean, _ = strip_conclusive_sentences(" ".join((text or "").split()))
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return clean or "(no passage text)"


def _citations_from_chunks(chunks: Sequence[Any], limit: int = 5) -> List[CitationObject]:
    """Deterministic citations straight from the retrieved chunks."""
    citations: List[CitationObject] = []
    for chunk in list(chunks)[:limit]:
        text = " ".join((chunk.text or "").split())
        if len(text) > 400:
            text = text[:399].rstrip() + "…"
        citations.append(
            CitationObject(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.title,
                source_type=chunk.source_type,
                jurisdiction=chunk.jurisdiction,
                publication_date=chunk.publication_date,
                page_number=chunk.page_number,
                relevant_text=text,
                url=chunk.source_url,
            )
        )
    return citations


def _deterministic_answer(obs: _Observations) -> str:
    """Evidence-only answer assembled without any model.

    Every line is derived from retrieved passages, graph paths or recorded
    tool output - there is nowhere here for a fact to be invented.
    """
    lines: List[str] = ["Preliminary multi-source findings (review required).", ""]

    if obs.chunks:
        lines.append("Validated corpus passages:")
        for index, chunk in enumerate(obs.chunks[:5], 1):
            place = chunk.jurisdiction or chunk.source_type
            lines.append(
                f'{index}. {chunk.title} - "{_excerpt(chunk.text)}" '
                f"(chunk {chunk.chunk_id}, {place})"
            )
        lines.append("")

    if obs.kg_node_names:
        lines.append(
            "Related concepts in the knowledge graph: "
            + ", ".join(sorted(obs.kg_node_names)[:8])
            + "."
        )
        lines.append("")

    paths = obs.graph_paths
    if paths:
        lines.append("Relational paths (knowledge graph - preliminary):")
        for path in paths[:4]:
            chain = path.get("chain") or path.get("human_readable") or ""
            if chain:
                lines.append(f"- {chain}")
        lines.append(GRAPH_REVIEW_NOTE)
        lines.append("")

    if obs.route_map:
        lines.append("IP route map for the selected Product Passport (preliminary):")
        for route in (obs.route_map.get("routes") or [])[:9]:
            if isinstance(route, dict):
                label = route.get("route_label") or route.get("route") or "route"
                lines.append(f"- {label}: {route.get('status')}")
        lines.append("")

    if obs.classification:
        lines.append(
            "Formulation classification: "
            f"{obs.classification.get('category')} ({obs.classification.get('status')}) "
            "- preliminary, review required."
        )
        lines.append("")

    if obs.screening:
        lines.append(
            f"Biodiversity screening: {obs.screening.get('status')} "
            "- preliminary, not a determination."
        )
        lines.append("")

    if obs.reference:
        lines.append(
            f"Official-source reference list: "
            f"{len(obs.reference.get('instruments') or [])} instrument(s), "
            f"{len(obs.reference.get('registry_sources') or [])} registry source(s)."
        )
        lines.append("")

    lines.append(
        "Next step: professional review is required before any filing, launch, "
        "registration or launch decision."
    )
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


LLM_SYNTHESIS_SYSTEM_PROMPT = (
    "You are the synthesis step of a preliminary IP/biodiversity decision-support "
    "agent. Answer ONLY from the evidence provided below; never add facts, "
    "passages, statutes, sources or numbers that are not in the evidence. "
    "Reference passages by their [chunk N] id and attach them as citations. "
    "Never state that anything is eligible, approved, patentable, infringing, "
    "safe or compliant, and never give a final legal, regulatory or medical "
    "conclusion: describe what the evidence shows and say review is required. "
    "If the evidence does not answer the question, say so briefly. "
    "Respond with ONE JSON object and nothing else:\n"
    '{"answer": "<text>", "citations": [{"chunk_id": N, "title": "<exact title>", '
    '"relevant_text": "<passage supporting the answer>"}]}'
)


def _build_evidence_prompt(obs: _Observations, query: str) -> str:
    parts: List[str] = [f"Question: {query}", "", "Evidence:"]
    if obs.chunks:
        parts.append("")
        parts.append("Corpus passages:")
        for chunk in obs.chunks[:5]:
            parts.append(
                f"[chunk {chunk.chunk_id}] {chunk.title} "
                f"({chunk.jurisdiction or chunk.source_type}):\n"
                f"{(chunk.text or '')[:800]}"
            )
    paths = obs.graph_paths
    if paths:
        parts.append("")
        parts.append("Relational paths (knowledge graph, review required):")
        for path in paths[:4]:
            chain = path.get("chain") or path.get("human_readable")
            if chain:
                parts.append(f"- {chain}")
    if obs.kg_node_names:
        parts.append("")
        parts.append("Graph concepts: " + ", ".join(sorted(obs.kg_node_names)[:12]))
    if obs.route_map:
        parts.append("")
        parts.append("Recorded IP route map (preliminary):")
        for route in (obs.route_map.get("routes") or [])[:9]:
            if isinstance(route, dict):
                parts.append(
                    f"- {route.get('route_label') or route.get('route')}: "
                    f"{route.get('status')}"
                )
    if obs.classification:
        parts.append("")
        parts.append(
            "Recorded classification: "
            f"{obs.classification.get('category')} ({obs.classification.get('status')})"
        )
    if obs.screening:
        parts.append("")
        parts.append(f"Recorded biodiversity screening: {obs.screening.get('status')}")
    parts.append("")
    parts.append(DISCLAIMER)
    return "\n".join(parts)


def _synthesise_with_llm(
    llm: Any, query: str, obs: _Observations
) -> Tuple[Optional[str], Optional[List[CitationObject]], List[str]]:
    """Ask the model to answer from the observed evidence only.

    Returns ``(answer, citations, warnings)``. ``answer is None`` means the
    draft was unusable (bad JSON or a conclusive statement) and the caller
    must fall back to the deterministic summary; ``citations is None`` means
    the response carried no usable citation list at all.
    """
    from app.agents.planner import _parse_json

    warnings: List[str] = []
    try:
        raw = llm.generate(
            system_prompt=LLM_SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=_build_evidence_prompt(obs, query),
        )
        parsed = _parse_json(raw)
    except Exception as exc:
        logger.warning("LLM synthesis failed (%s); using the evidence-only summary", exc)
        return None, None, [f"Model synthesis unavailable ({exc}); used the evidence-only summary."]

    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None, None, ["Model returned no usable answer; used the evidence-only summary."]

    raw_citations = parsed.get("citations")
    citations: Optional[List[CitationObject]] = None
    if isinstance(raw_citations, list):
        citations = []
        for item in raw_citations:
            if not isinstance(item, dict) or item.get("chunk_id") is None:
                continue
            try:
                citations.append(
                    CitationObject(
                        chunk_id=int(item["chunk_id"]),
                        document_id=int(item.get("document_id") or 0),
                        title=str(item.get("title") or ""),
                        source_type=str(item.get("source_type") or "corpus"),
                        relevant_text=str(item.get("relevant_text") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue

    cleaned, removed = strip_conclusive_sentences(answer)
    if removed:
        logger.warning("LLM synthesis dropped %d conclusive sentence(s)", removed)
        return None, None, warnings + [
            "The model draft contained a conclusive statement and was replaced "
            "with the evidence-only summary."
        ]
    if not cleaned.strip():
        return None, None, warnings + [
            "Nothing remained of the model draft after the conclusive-statement "
            "check; used the evidence-only summary."
        ]
    return cleaned.strip(), citations, warnings


# ============================================================
# Product -> IP route reasoning enrichment
# ============================================================

#: Query keyword -> IP route key, most specific first; ``patent`` is the
#: default target (the route with the best-known statutory bars).
_ROUTE_KEYWORDS: Sequence[Tuple[str, Sequence[str]]] = (
    ("traditional_knowledge", ("traditional knowledge",)),
    ("biodiversity_abs", ("biodiversity", "benefit sharing", "nagoya", "biological resource")),
    ("gi", ("geographical indication", "gi ", "region of origin")),
    ("plant_variety", ("plant variety", "cultivar", "farmers' rights")),
    ("trade_secret", ("trade secret", "know-how", "confidential process")),
    ("trademark", ("trademark", "trade mark", "brand name")),
    ("copyright", ("copyright",)),
    ("design", ("industrial design", "design")),
    ("patent", ("patent",)),
)


def target_route_key(query: str) -> str:
    """Deterministically pick the IP route a reasoning chain should aim at."""
    text = f" {(query or '').lower()} "
    for key, keywords in _ROUTE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return key
    return "patent"  # pragma: no cover - "patent" keyword always matches


def _product_reasoning_paths(
    db: Session, user_id: int, product_version_id: int, query: str
) -> List[Dict[str, Any]]:
    """Product node -> ... -> IP route chain from the graph (internal step).

    Not a registry tool: it is the orchestrator's own enrichment so a run with
    a Product Passport selected always carries the graph's multi-hop chain for
    the route the question points at. Access control is enforced here exactly
    as the tools enforce it.
    """
    try:
        from app.graph.query import reasoning_paths
        from app.models import ProductVersion
        from app.utils.authorization import get_accessible_product

        version = db.get(ProductVersion, int(product_version_id))
        if version is None:
            return []
        get_accessible_product(db, version.product_id, user_id)
        key = target_route_key(query)
        paths = reasoning_paths(db, version.product_id, key)
    except Exception as exc:
        logger.info("Product reasoning paths skipped: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for path in paths:
        tagged = dict(path)
        tagged["source"] = "product_reasoning"
        tagged["target_route_key"] = target_route_key(query)
        out.append(tagged)
    return out


# ============================================================
# The orchestrator
# ============================================================

def run_agent(
    db: Session,
    query: str,
    *,
    user_id: int,
    product_version_id: Optional[int] = None,
    max_steps: int = 5,
    llm: Any = None,
) -> AgentResult:
    """Run one full plan -> execute -> observe -> decide -> synthesise cycle.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    query:
        The user's question.
    user_id:
        Asking user (tools use it for retrieval scope and access control).
    product_version_id:
        Selected Product Passport version, when the caller has one.
    max_steps:
        Step budget for this run (capped at ``MAX_PLAN_STEPS``).
    llm:
        Optional provider exposing ``generate(system_prompt=..., user_prompt=...)``
        used for planning and synthesis. ``None`` (or any model failure)
        degrades to the deterministic planner/summariser - never to a crash.
    """
    from app.rag.citation import INSUFFICIENT_EVIDENCE_MESSAGE, validate_citations

    started = time.perf_counter()
    max_steps = max(1, min(int(max_steps), MAX_PLAN_STEPS))

    # ---------------------------------------------------------
    # 1. Plan (LLM when available, deterministic fallback otherwise)
    # ---------------------------------------------------------
    from app.agents.planner import plan
    from app.agents.tools import TOOL_REGISTRY, execute_tool

    planned = plan(query, product_version_id=product_version_id, max_steps=max_steps, llm=llm)
    steps = planned.steps[:max_steps]

    # ---------------------------------------------------------
    # 2. Execute -> observe -> decide (step budget enforced)
    # ---------------------------------------------------------
    obs = _Observations()
    trace: List[AgentTrace] = []
    warnings: List[str] = []
    decision = "continue"

    for index, step in enumerate(steps, start=1):
        args: Dict[str, Any] = dict(step.args or {})
        spec = TOOL_REGISTRY.get(step.tool)
        if spec is not None and spec.requires_version and product_version_id:
            args.setdefault("product_version_id", product_version_id)

        t0 = time.perf_counter()
        result = execute_tool(db, step.tool, args, user_id=user_id)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        ok = bool(result.get("ok"))

        trace.append(
            AgentTrace(
                step=index,
                tool=step.tool,
                args=args,
                ok=ok,
                result_summary=_summarize(step.tool, result),
                warning=result.get("warning"),
                ms=elapsed_ms,
            )
        )
        if ok:
            obs.observe(step.tool, result.get("data"))
        else:
            obs.failures += 1
            warning = str(result.get("warning") or "unknown error")
            obs.tool_warnings.append(f"{step.tool}: {warning}")
            warnings.append(f"Step {index} ({step.tool}) failed: {warning}")

        decision = _decide(obs, budget_exhausted=(index >= len(steps)))
        if decision != "continue":
            break

    # ---------------------------------------------------------
    # 3. Graph enrichment: product -> IP route reasoning chain
    # ---------------------------------------------------------
    if product_version_id:
        obs.product_paths.extend(
            _product_reasoning_paths(db, user_id, product_version_id, query)
        )
    decision = _decide(obs, budget_exhausted=True)
    graph_paths = obs.graph_paths

    # ---------------------------------------------------------
    # 4. Synthesise
    # ---------------------------------------------------------
    answer: Optional[str] = None
    llm_citations: Optional[List[CitationObject]] = None
    if llm is not None:
        answer, llm_citations, synth_warnings = _synthesise_with_llm(llm, query, obs)
        warnings.extend(synth_warnings)
    if answer is None:
        answer = _deterministic_answer(obs)

    # ---------------------------------------------------------
    # 5. Abstention + citation validation (mirrors app.rag.generation)
    # ---------------------------------------------------------
    citations: List[CitationObject] = []
    insufficient = False

    if decision == "abstain":
        answer = INSUFFICIENT_EVIDENCE_MESSAGE
        citations = []
        insufficient = True
        warnings.append(
            "Insufficient evidence: no corpus passage, knowledge-graph match or "
            "Product Passport result was available for this question."
        )
    elif obs.chunks:
        proposed = (
            llm_citations
            if (llm is not None and llm_citations is not None)
            else _citations_from_chunks(obs.chunks)
        )
        all_valid, valid = validate_citations(proposed, obs.chunks)
        if not valid and not proposed:
            # Model attached no citations although sources WERE retrieved:
            # keep the answer and say its claims carry no verified citation
            # (same rule as app.rag.generation).
            citations = []
            warnings.append(
                "This answer was produced from retrieved sources, but no "
                "verifiable citations were attached - treat its claims as "
                "unverified until cited."
            )
        elif not valid:
            # Every cited source is unverifiable -> abstain.
            answer = INSUFFICIENT_EVIDENCE_MESSAGE
            citations = []
            insufficient = True
            warnings.append("Citation validation failed - no verified sources available.")
        else:
            citations = valid
            if not all_valid:
                warnings.append(
                    "Some citations could not be verified against the retrieved "
                    "passages and were removed."
                )
    else:
        if llm_citations:
            warnings.append(
                "Citations offered by the model were dropped: no retrieved "
                "passage was available to validate them against."
            )
        citations = []
        if not insufficient:
            warnings.append(
                "No corpus passage matched this question; the answer rests on "
                "relational and Product Passport evidence only (review required)."
            )

    # ---------------------------------------------------------
    # 6. Final conclusive-statement guard (never on controlled text)
    # ---------------------------------------------------------
    if not insufficient:
        cleaned, removed = strip_conclusive_sentences(answer)
        if removed:
            answer = cleaned
            warnings.append(
                "Conclusive phrasing was removed so the platform does not "
                "state a legal, regulatory or medical conclusion."
            )
        if not answer or not answer.strip():
            answer = INSUFFICIENT_EVIDENCE_MESSAGE
            citations = []
            insufficient = True
            warnings.append("Nothing remained of the answer after safety checks.")

    # ---------------------------------------------------------
    # 7. Deterministic confidence + sources
    # ---------------------------------------------------------
    confidence = derive_confidence(
        chunk_count=len(obs.chunks),
        graph_hit=obs.graph_hit,
        product_hit=bool(obs.product_hits),
        citation_count=len(citations),
        path_count=len(graph_paths),
        failure_count=obs.failures,
        sufficient=not insufficient,
    )

    sources_used: List[Dict[str, Any]] = []
    seen_documents = set()
    for citation in citations:
        document_id = getattr(citation, "document_id", None)
        if document_id in seen_documents:
            continue
        if document_id is not None:
            seen_documents.add(document_id)
        sources_used.append(
            {
                "document_id": document_id,
                "title": getattr(citation, "title", ""),
                "source_type": getattr(citation, "source_type", ""),
                "url": getattr(citation, "url", None),
            }
        )

    warnings = _dedupe(warnings)
    duration_ms = int((time.perf_counter() - started) * 1000)

    result = AgentResult(
        answer=answer.strip(),
        plan=planned.to_dict(),
        trace=trace,
        citations=citations,
        sources_used=sources_used,
        graph_paths=graph_paths,
        confidence=str(confidence["confidence"]),
        confidence_reason=str(confidence["reason"]),
        insufficient_evidence=insufficient,
        disclaimer=DISCLAIMER,
        review_required=True,
        warnings=warnings,
        steps_used=len(trace),
        max_steps=max_steps,
        duration_ms=duration_ms,
    )

    # ---------------------------------------------------------
    # 8. Persist the run (a failed insert never fails the answer)
    # ---------------------------------------------------------
    result.run_id = _persist_run(
        db,
        user_id=user_id,
        product_version_id=product_version_id,
        query=query,
        result=result,
    )

    logger.info(
        "Agent run: user=%s steps=%d/%d confidence=%s insufficient=%s citations=%d "
        "graph_paths=%d run_id=%s | %s",
        user_id,
        len(trace),
        max_steps,
        result.confidence,
        result.insufficient_evidence,
        len(citations),
        len(graph_paths),
        result.run_id,
        (query or "")[:80],
    )
    return result


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _persist_run(
    db: Session,
    *,
    user_id: int,
    product_version_id: Optional[int],
    query: str,
    result: AgentResult,
) -> Optional[int]:
    """Store the run so ``GET /api/agent/traces`` can replay it."""
    try:
        run = AgentRun(
            user_id=user_id,
            product_version_id=product_version_id,
            query=query,
            answer=result.answer,
            plan_json=_dump(result.plan),
            trace_json=_dump([t.model_dump() for t in result.trace]),
            citations_json=_dump([c.model_dump() for c in result.citations]),
            sources_json=_dump(result.sources_used),
            graph_paths_json=_dump(result.graph_paths),
            warnings_json=_dump(result.warnings),
            confidence=result.confidence,
            confidence_reason=result.confidence_reason,
            insufficient_evidence=result.insufficient_evidence,
            review_required=True,
            steps_used=result.steps_used,
            max_steps=result.max_steps,
            duration_ms=result.duration_ms,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    except Exception as exc:  # pragma: no cover - defensive isolation
        db.rollback()
        logger.warning("Could not persist agent run: %s", exc)
        return None
