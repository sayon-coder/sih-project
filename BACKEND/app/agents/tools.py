"""Tool registry for the orchestrating agent.

Every capability the agent may call lives here as a :class:`ToolSpec` with a
stable name, a plain-language description, a JSON-able parameter contract and
a handler. Handlers are ordinary functions ``(db, user_id, args) -> dict`` and
**must** return exactly::

    {"ok": bool, "data": <json-serialisable>, "warning": str | None}

Design rules (they are what the tests protect):

* **Read-only.** No tool writes to the database. The agent reasons over stored
  content; it never mutates products, claims, analyses or the graph.
* **Isolation.** A tool never lets an internal exception escape: expected
  failures are returned as ``ok=False`` with an explanatory ``warning``, and
  :func:`execute_tool` converts anything else into ``ok=False`` so one broken
  tool cannot abort the run.
* **Product context.** The four product-scoped tools need a
  ``product_version_id``; the orchestrator injects it from the request so the
  model does not have to echo ids back.
* **No conclusions.** Tools return recorded facts, relational paths and
  disclaimers. Nothing here produces an approval, eligibility or
  patentability statement.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.analysis.classifier import classify_product
from app.analysis.ip_routes import build_ip_route_map
from app.analysis.screening import screen_biodiversity
from app.data.traditional_knowledge_sources import get_traditional_knowledge_sources
from app.graph.query import graph_context, query_paths, shortest_path
from app.graph.schema import GRAPH_REVIEW_NOTE, GraphNode, NodeType, node_to_dict
from app.models import ProductVersion
from app.rag.retrieval import hybrid_retrieve
from app.rag.schemas import MetadataFilter
from app.services.version_content import load_version_content
from app.utils.authorization import get_accessible_product

logger = logging.getLogger(__name__)

Handler = Callable[[Session, int, Dict[str, Any]], Dict[str, Any]]


# ============================================================
# Result helpers
# ============================================================

def tool_ok(data: Any, warning: Optional[str] = None) -> Dict[str, Any]:
    """Successful tool result."""
    return {"ok": True, "data": data, "warning": warning}


def tool_error(message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    """Controlled tool failure (never raises into the orchestrator)."""
    return {"ok": False, "data": data if data is not None else {}, "warning": message}


# ============================================================
# Shared context
# ============================================================

def _version_for(db: Session, user_id: int, args: Dict[str, Any]) -> ProductVersion:
    """Resolve the Product Passport version the product-scoped tools use.

    Ownership is checked with the shared authorisation helper, and a failure is
    reported as "not found" so a foreign version id is never confirmed.
    """
    raw = args.get("product_version_id")
    if raw in (None, "", 0):
        raise ValueError(
            "This tool needs a product_version_id: select a Product Passport first."
        )
    version = db.get(ProductVersion, int(raw))
    if version is None:
        raise ValueError("Product version not found.")
    try:
        get_accessible_product(db, version.product_id, user_id)
    except HTTPException as exc:  # 404 for missing/foreign products
        raise ValueError("Product version not found.") from exc
    return version


def _chunk_payload(chunk: Any) -> Dict[str, Any]:
    """Serialise a RetrievedChunk for the prompt/trace (text is truncated)."""
    text = (chunk.text or "").strip()
    if len(text) > 600:
        text = text[:600] + "..."
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "source_type": chunk.source_type,
        "jurisdiction": chunk.jurisdiction,
        "source_url": chunk.source_url,
        "page_number": chunk.page_number,
        "final_score": chunk.final_score,
        "text": text,
    }


# ============================================================
# Tool handlers
# ============================================================

def _retrieve_corpus(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Hybrid retrieval over the verified corpus for a free-text query."""
    query = str(args.get("query") or "").strip()
    if not query:
        return tool_error("retrieve_corpus requires a non-empty 'query'.")

    try:
        top_k = max(1, min(int(args.get("top_k") or 5), 20))
    except (TypeError, ValueError):
        top_k = 5

    filters = MetadataFilter(
        source_types=list(args["source_types"]) if args.get("source_types") else None,
        jurisdictions=list(args["jurisdictions"]) if args.get("jurisdictions") else None,
        include_public=True,
        include_private=True,
    )

    try:
        chunks = hybrid_retrieve(
            db, query, filters=filters, user_id=user_id, top_k_final=top_k
        )
    except Exception as exc:  # retrieval outages degrade, never 500
        logger.warning("retrieve_corpus failed: %s", exc)
        return tool_error(f"Corpus retrieval failed: {exc}")

    payload = [_chunk_payload(c) for c in chunks]
    warning = None
    if not payload:
        warning = (
            "No verified corpus passage matched this query; the answer must not "
            "invent a source."
        )
    return tool_ok({"query": query, "count": len(payload), "chunks": payload}, warning)


def _query_knowledge_graph(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Relational context: a subgraph for the query and/or a path between two nodes."""
    from_ref = args.get("from") or args.get("from_name")
    to_ref = args.get("to") or args.get("to_name")
    query = str(args.get("query") or "").strip()

    if from_ref and to_ref:
        path = shortest_path(db, from_ref, to_ref)
        data = {
            "mode": "path",
            "paths": [path] if path else [],
            "review_required": True,
            "note": GRAPH_REVIEW_NOTE,
        }
        warning = None if path else "No relational path between those two concepts."
        return tool_ok(data, warning)

    if not query and not from_ref and not to_ref:
        return tool_error(
            "query_knowledge_graph requires 'query' or a 'from'/'to' pair."
        )

    seed = query or str(from_ref or to_ref)
    context = graph_context(db, seed, limit=6)
    paths = query_paths(db, seed) if query else []
    data = {
        "mode": "context",
        "context": context,
        "paths": paths,
        "review_required": True,
        "note": GRAPH_REVIEW_NOTE,
    }
    warning = None
    if not context["nodes"]:
        warning = "The knowledge graph has no node matching this query."
    return tool_ok(data, warning)


def _ip_route_map(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic IP route map for the selected Product Passport version."""
    version = _version_for(db, user_id, args)
    content = load_version_content(db, version)
    result = build_ip_route_map(
        version.product,
        version,
        content["ingredients"],
        content["formulation"],
        content["claims"],
        content["evidence"],
        content["markets"],
    )
    payload = result.model_dump()
    warnings = list(payload.get("warnings") or [])
    return tool_ok(payload, warnings[0] if warnings else "Preliminary route map only.")


def _biodiversity_screen(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Access-and-benefit-sharing screening for the selected version."""
    version = _version_for(db, user_id, args)
    content = load_version_content(db, version)
    result = screen_biodiversity(
        version,
        content["ingredients"],
        content["formulation"],
        content["claims"],
        content["evidence"],
        content["markets"],
        db=db,
        user_id=user_id,
    )
    payload = result.model_dump()
    return tool_ok(payload, "Preliminary screening - not an approval or determination.")


def _official_sources_for(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Official instruments/registries for a jurisdiction plus the source registry.

    Restricted databases (TKDL) are returned as citations *to the database*,
    never as contents - the platform cannot search them.
    """
    jurisdiction = str(args.get("jurisdiction") or "").strip()
    topic = str(args.get("topic") or "").strip()

    sources = get_traditional_knowledge_sources()
    if jurisdiction:
        wanted = jurisdiction.lower()
        sources = [
            s
            for s in sources
            if str(s.get("jurisdiction") or "").lower() == wanted
            or not s.get("jurisdiction")
        ]

    types = [
        NodeType.STATUTE.value,
        NodeType.RULE.value,
        NodeType.TREATY.value,
        NodeType.REGISTRY.value,
        NodeType.REGULATOR.value,
        NodeType.OBLIGATION.value,
    ]
    query = db.query(GraphNode).filter(GraphNode.node_type.in_(types))
    if jurisdiction:
        query = query.filter(
            or_(
                GraphNode.jurisdiction == jurisdiction,
                GraphNode.jurisdiction == "International",
            )
        )
    instruments = [node_to_dict(n) for n in query.order_by(GraphNode.node_type, GraphNode.canonical_name).all()]

    if topic:
        wanted = topic.lower()
        instruments = [
            i for i in instruments
            if wanted in (i.get("canonical_name") or "").lower()
            or wanted in str(i.get("attributes") or {}).lower()
        ]

    data = {
        "jurisdiction": jurisdiction or None,
        "topic": topic or None,
        "registry_sources": sources,
        "instruments": instruments,
        "review_required": True,
        "note": GRAPH_REVIEW_NOTE,
    }
    warning = None
    if not instruments and not sources:
        warning = "No official source or instrument recorded for that jurisdiction/topic."
    return tool_ok(data, warning)


def _classify_formulation(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """Preliminary formulation classification for the selected version.

    The classification gate is inherited as-is: missing information leads and
    the status stays ``PRELIMINARY`` with ``review_required``.
    """
    version = _version_for(db, user_id, args)
    content = load_version_content(db, version)
    try:
        result = classify_product(
            db,
            version.product,
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["markets"],
            content["evidence"],
        )
    except ValueError as exc:
        # Malformed model output is a controlled failure, never a guessed category.
        return tool_error(f"Classification unavailable: {exc}")
    payload = result.model_dump()
    return tool_ok(payload, "Preliminary classification - review required.")


# ============================================================
# Registry
# ============================================================

@dataclass(frozen=True)
class ToolSpec:
    """One tool the agent may call."""

    name: str
    description: str
    parameters: Dict[str, Dict[str, Any]]
    requires_version: bool
    handler: Handler

    def contract(self) -> Dict[str, Any]:
        """JSON-able parameter contract (shown to the planner and the API)."""
        return {name: dict(spec) for name, spec in self.parameters.items()}


def _param(kind: str, description: str, required: bool = False) -> Dict[str, Any]:
    return {"type": kind, "description": description, "required": required}


#: Ordered registry - the order is the planner's default priority.
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "retrieve_corpus": ToolSpec(
        name="retrieve_corpus",
        description=(
            "Search the verified corpus (vector + keyword, reranked) and return the "
            "passages that support an answer, each with its chunk id and title."
        ),
        parameters={
            "query": _param("string", "Free-text question or keyword set.", required=True),
            "top_k": _param("integer", "How many passages to return (1-20, default 5)."),
            "source_types": _param("array", "Optional source-type filter."),
            "jurisdictions": _param("array", "Optional jurisdiction filter (e.g. ['India'])."),
        },
        requires_version=False,
        handler=_retrieve_corpus,
    ),
    "query_knowledge_graph": ToolSpec(
        name="query_knowledge_graph",
        description=(
            "Read the relational knowledge graph: a subgraph for a free-text query, "
            "or the path between two named concepts (e.g. a formulation category and "
            "an IP route). Always returns review_required=true."
        ),
        parameters={
            "query": _param("string", "Concepts to match against the graph."),
            "from": _param("string", "Start node (name or id) for a path query."),
            "to": _param("string", "End node (name or id) for a path query."),
        },
        requires_version=False,
        handler=_query_knowledge_graph,
    ),
    "ip_route_map": ToolSpec(
        name="ip_route_map",
        description=(
            "Deterministic IP route map for the selected Product Passport version: "
            "preliminary route indications, missing information and warnings."
        ),
        parameters={
            "product_version_id": _param(
                "integer", "Product Passport version id (injected when selected).", required=True
            ),
        },
        requires_version=True,
        handler=_ip_route_map,
    ),
    "biodiversity_screen": ToolSpec(
        name="biodiversity_screen",
        description=(
            "Access-and-benefit-sharing screening for the selected version: whether a "
            "biological resource is recorded and what information is still missing."
        ),
        parameters={
            "product_version_id": _param(
                "integer", "Product Passport version id (injected when selected).", required=True
            ),
        },
        requires_version=True,
        handler=_biodiversity_screen,
    ),
    "official_sources_for": ToolSpec(
        name="official_sources_for",
        description=(
            "Official instruments, registries, regulators and the traditional-knowledge "
            "source registry for a jurisdiction (restricted databases are cited, never read)."
        ),
        parameters={
            "jurisdiction": _param("string", "Jurisdiction name, e.g. 'India'."),
            "topic": _param("string", "Optional topic to narrow the instrument list."),
        },
        requires_version=False,
        handler=_official_sources_for,
    ),
    "classify_formulation": ToolSpec(
        name="classify_formulation",
        description=(
            "Preliminary formulation classification for the selected version (status, "
            "category, alternatives, missing information). Never a final category."
        ),
        parameters={
            "product_version_id": _param(
                "integer", "Product Passport version id (injected when selected).", required=True
            ),
        },
        requires_version=True,
        handler=_classify_formulation,
    ),
}

#: Tools that need a selected Product Passport version.
VERSION_TOOLS = tuple(name for name, spec in TOOL_REGISTRY.items() if spec.requires_version)


def tool_catalog() -> List[Dict[str, Any]]:
    """Public tool catalogue for ``GET /api/agent/tools``."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.contract(),
            "requires_product_version": spec.requires_version,
        }
        for spec in TOOL_REGISTRY.values()
    ]


def execute_tool(
    db: Session,
    name: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    user_id: int,
) -> Dict[str, Any]:
    """Run one tool with full error isolation.

    Returns the tool's ``{ok, data, warning}`` dict, with ``tool`` and ``args``
    echoed back so the trace can be rendered without re-deriving them. Unknown
    tools and handler crashes are reported as ``ok=False`` instead of raising.
    """
    args = dict(args or {})
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return tool_error(
            f"Unknown tool '{name}'. Available tools: {', '.join(TOOL_REGISTRY)}.",
            data={"tool": name, "args": args},
        )

    try:
        result = spec.handler(db, user_id, args)
    except ValueError as exc:
        result = tool_error(str(exc))
    except Exception as exc:  # pragma: no cover - defensive isolation
        logger.exception("Tool %s crashed", name)
        result = tool_error(f"Tool '{name}' failed: {exc}")

    if not isinstance(result, dict) or "ok" not in result:  # pragma: no cover - contract guard
        result = tool_error(f"Tool '{name}' returned an unexpected result shape.")

    result.setdefault("data", None)
    result.setdefault("warning", None)
    result["tool"] = name
    result["args"] = args
    return result
