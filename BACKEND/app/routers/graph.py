"""Relational knowledge graph + agentic orchestration router (Stage 2).

Endpoints (all authenticated with ``get_current_user_model``)::

    POST /api/graph/build                build/refresh the graph, returns counts
    GET  /api/graph/nodes                list nodes (?node_type=&q=&limit=)
    GET  /api/graph/nodes/{node_id}      one node with its edges
    GET  /api/graph/paths                shortest path (?from=&to=)
    POST /api/agent/run                  run the orchestrator -> AgentResult
    GET  /api/agent/tools                the tool registry (name, description, parameters)
    GET  /api/agent/traces               the caller's persisted runs
    GET  /api/agent/traces/{run_id}      one stored run with its full trace

Route paths are absolute (``/api/graph/...`` and ``/api/agent/...``) instead
of living under one ``APIRouter`` prefix, so this single ``router`` variable
covers both families. Register it with::

    from app.routers.graph import router as graph_router
    app.include_router(graph_router)

No endpoint ever returns a conclusive legal statement: every graph payload
carries ``review_required: true`` and every agent result carries the platform
disclaimer.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.orchestrator import AgentResult, run_agent
from app.agents.tools import tool_catalog
from app.database import get_db
from app.graph.builder import build_or_refresh_graph
from app.graph.query import shortest_path
from app.graph.schema import (
    GRAPH_REVIEW_NOTE,
    NODE_TYPE_VALUES,
    GraphEdge,
    GraphNode,
    edge_to_dict,
    node_to_dict,
    normalize_name,
)
from app.llm.provider import get_llm_provider, get_llm_provider_for
from app.models.models import User
from app.schemas.schemas import APIResponse
from app.utils import get_current_user_model

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Knowledge Graph & Agent"])

#: Keep list responses bounded.
DEFAULT_NODE_LIMIT = 50
MAX_NODE_LIMIT = 200


# ============================================================
# Request bodies
# ============================================================

class GraphBuildRequest(BaseModel):
    """``POST /api/graph/build`` body (both fields optional)."""

    full: bool = Field(
        default=False,
        description="Delete every node and edge first, then rebuild from scratch.",
    )


class AgentRunRequest(BaseModel):
    """``POST /api/agent/run`` body."""

    query: str = Field(..., min_length=1, max_length=4000)
    product_version_id: Optional[int] = None
    max_steps: int = Field(default=5, ge=1, le=5)
    provider: Optional[str] = None  # "groq" | "sarvam" | None (default chain)


# ============================================================
# Knowledge graph
# ============================================================

@router.post("/api/graph/build", response_model=APIResponse)
def build_graph(
    body: Optional[GraphBuildRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """Build or refresh the relational knowledge graph from recorded data.

    Idempotent: nodes upsert on their normalised name and edges on
    ``(from, to, relation)``, so re-running only refreshes evidence.
    """
    stats = build_or_refresh_graph(db, full=bool(body.full) if body else False)
    return APIResponse(
        success=True,
        data=stats,
        message="Knowledge graph built" if not (body and body.full)
        else "Knowledge graph rebuilt from scratch",
    )


@router.get("/api/graph/nodes", response_model=APIResponse)
def list_nodes(
    node_type: Optional[str] = Query(
        default=None, description="Filter by node type, e.g. STATUTE or IP_TYPE."
    ),
    q: Optional[str] = Query(
        default=None, description="Substring match on the normalised node name."
    ),
    limit: int = Query(default=DEFAULT_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """List graph nodes, newest identity first (stable order by name)."""
    if node_type and node_type.upper() not in NODE_TYPE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown node_type '{node_type}'. "
                f"Allowed: {', '.join(sorted(NODE_TYPE_VALUES))}"
            ),
        )

    query_ = db.query(GraphNode)
    if node_type:
        query_ = query_.filter(GraphNode.node_type == node_type.upper())
    if q:
        needle = normalize_name(q)
        if needle:
            query_ = query_.filter(GraphNode.normalized_name.ilike(f"%{needle}%"))

    rows = query_.order_by(GraphNode.node_type, GraphNode.canonical_name).limit(limit).all()
    total = query_.count()
    return APIResponse(
        success=True,
        data={
            "nodes": [node_to_dict(row) for row in rows],
            "count": len(rows),
            "total": total,
            "review_required": True,
            "note": GRAPH_REVIEW_NOTE,
        },
    )


@router.get("/api/graph/nodes/{node_id}", response_model=APIResponse)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """One node with every edge touching it (both directions)."""
    node = db.get(GraphNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Graph node not found.")

    edges = (
        db.query(GraphEdge)
        .filter((GraphEdge.from_node_id == node_id) | (GraphEdge.to_node_id == node_id))
        .order_by(GraphEdge.relation, GraphEdge.id)
        .all()
    )
    neighbour_ids = sorted(
        ({e.from_node_id for e in edges} | {e.to_node_id for e in edges}) - {node_id}
    )
    neighbours = {
        n.id: n for n in db.query(GraphNode).filter(GraphNode.id.in_(neighbour_ids)).all()
    } if neighbour_ids else {}

    edge_payloads: List[Dict[str, Any]] = []
    for edge in edges:
        payload = edge_to_dict(edge)
        payload["from"] = node_to_dict(neighbours.get(edge.from_node_id))
        payload["to"] = node_to_dict(neighbours.get(edge.to_node_id))
        edge_payloads.append(payload)

    return APIResponse(
        success=True,
        data={
            "node": node_to_dict(node),
            "edges": edge_payloads,
            "edge_count": len(edge_payloads),
            "review_required": True,
            "note": GRAPH_REVIEW_NOTE,
        },
    )


@router.get("/api/graph/paths", response_model=APIResponse)
def get_paths(
    from_ref: str = Query(..., alias="from", description="Start node name or id."),
    to_ref: str = Query(..., alias="to", description="End node name or id."),
    max_depth: int = Query(default=8, ge=1, le=8),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """Shortest relational path between two concepts (traversable both ways)."""
    path = shortest_path(db, from_ref, to_ref, max_depth=max_depth)
    if path is None:
        return APIResponse(
            success=True,
            data=None,
            message="No relational path found between those concepts.",
        )
    return APIResponse(
        success=True,
        data={"path": path, "review_required": True, "note": GRAPH_REVIEW_NOTE},
    )


# ============================================================
# Agent
# ============================================================

def _resolve_llm(provider: Optional[str]) -> Optional[Any]:
    """Resolve the model for this run; never fails the request.

    When no model can be built (missing key, unknown choice, provider error)
    the orchestrator degrades to its deterministic planner and summariser.
    """
    try:
        if provider and provider != "groq":
            return get_llm_provider_for(provider)
        return get_llm_provider()
    except Exception as exc:
        logger.warning("Agent run continues without a model: %s", exc)
        return None


@router.post("/api/agent/run", response_model=AgentResult)
def agent_run(
    body: AgentRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> AgentResult:
    """Run the multi-step agent loop and return its ``AgentResult``.

    The loop plans, executes one tool per step (budget ``max_steps``),
    observes, decides (continue / answer / abstain) and synthesises an answer
    whose corpus citations are validated against the retrieved passages.
    """
    if body.provider not in (None, "groq", "sarvam"):
        raise HTTPException(status_code=400, detail="provider must be 'groq' or 'sarvam'.")

    llm = _resolve_llm(body.provider)
    try:
        result = run_agent(
            db,
            body.query,
            user_id=current_user.id,
            product_version_id=body.product_version_id,
            max_steps=body.max_steps,
            llm=llm,
        )
    except Exception as exc:  # pragma: no cover - defensive isolation
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=f"Agent run failed: {exc}") from exc

    if llm is None:
        result.warnings.append(
            "No language model was available for this run; planning and "
            "summarising used the deterministic fallback."
        )
    return result


@router.get("/api/agent/tools", response_model=APIResponse)
def list_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """The tool registry: name, description and parameter contract per tool."""
    return APIResponse(success=True, data=tool_catalog())


def _run_summary(run: AgentRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "query": run.query,
        "answer_preview": (run.answer or "")[:240],
        "confidence": run.confidence,
        "insufficient_evidence": run.insufficient_evidence,
        "review_required": bool(run.review_required),
        "steps_used": run.steps_used,
        "max_steps": run.max_steps,
        "product_version_id": run.product_version_id,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _loads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - corrupt row
        return default


@router.get("/api/agent/traces", response_model=APIResponse)
def list_traces(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """The caller's persisted agent runs, newest first."""
    from app.agents.orchestrator import AgentRun

    runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == current_user.id)
        .order_by(AgentRun.id.desc())
        .limit(limit)
        .all()
    )
    return APIResponse(
        success=True,
        data={"traces": [_run_summary(run) for run in runs], "count": len(runs)},
    )


@router.get("/api/agent/traces/{run_id}", response_model=APIResponse)
def get_trace(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_model),
) -> APIResponse:
    """One stored run with its full plan, tool trace and graph paths."""
    from app.agents.orchestrator import AgentRun

    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != current_user.id:
        # Same rule as the rest of the API: never confirm another user's rows.
        raise HTTPException(status_code=404, detail="Agent trace not found.")

    return APIResponse(
        success=True,
        data={
            **_run_summary(run),
            "answer": run.answer,
            "plan": _loads(run.plan_json, {}),
            "trace": _loads(run.trace_json, []),
            "citations": _loads(run.citations_json, []),
            "sources_used": _loads(run.sources_json, []),
            "graph_paths": _loads(run.graph_paths_json, []),
            "warnings": _loads(run.warnings_json, []),
            "confidence_reason": run.confidence_reason,
        },
    )
