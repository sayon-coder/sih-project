"""
Knowledge-graph query layer.

Read-only traversal over ``graph_nodes`` / ``graph_edges``:

* :func:`neighbors`      - breadth-first neighbourhood of one node;
* :func:`shortest_path`  - unweighted BFS path between two nodes;
* :func:`reasoning_paths` - the human-readable multi-hop reasoning chain for a
  product toward an IP route (always with ``review_required: True`` - the
  graph never returns a conclusive legal statement);
* :func:`graph_context`  - the most relevant subgraph for a free-text query,
  for injection into an agent or RAG prompt;
* :func:`query_paths`    - short relational paths between the concepts a query
  matched (used by the orchestrator when no product context exists).

Every payload is JSON-serialisable and carries ``review_required: True``.
"""
from __future__ import annotations

import logging
import re
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.graph.entities import IP_ROUTE_KEYS
from app.graph.schema import (
    GRAPH_REVIEW_NOTE,
    GraphEdge,
    GraphNode,
    NodeType,
    Relation,
    edge_to_dict,
    loads_json,
    normalize_name,
    node_to_dict,
)

logger = logging.getLogger(__name__)

#: Depth cap for path searches (keeps BFS bounded on a dense graph).
MAX_PATH_DEPTH = 8

#: Order in which alternative routes are offered when a path contains a
#: barrier (Barred_By) edge - mirrors the "route via TK/GI/trade secret
#: instead" phrasing of the problem statement's example chain.
ALTERNATIVE_ROUTE_ORDER = [
    "Traditional Knowledge",
    "Geographical Indication (GI)",
    "Trade Secret",
    "Plant Variety",
    "Biodiversity / ABS",
    "Trademark",
    "Copyright",
    "Design",
    "Patent",
]

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "for", "to", "is", "are", "on",
    "with", "what", "which", "how", "does", "do", "can", "could", "my", "this",
    "that", "by", "from", "be", "as", "at", "it", "its", "their", "our", "we",
    "you", "i", "if", "into", "about", "between", "under", "over", "any",
    "all", "not", "no", "than", "then", "there", "their", "was", "were", "will",
}


# ============================================================
# Helpers
# ============================================================

def resolve_node(db: Session, ref: Any) -> Optional[GraphNode]:
    """Resolve a node id, numeric string, or name (canonical or normalised)."""
    if ref is None:
        return None
    if isinstance(ref, GraphNode):
        return ref
    if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
        node = db.get(GraphNode, int(ref))
        if node is not None:
            return node
        # fall through: a name may itself be numeric
    name = normalize_name(str(ref))
    if not name:
        return None
    return db.query(GraphNode).filter(GraphNode.normalized_name == name).first()


def _node_ref(node: Optional[GraphNode]) -> Dict[str, Any]:
    if node is None:
        return {}
    return {"id": node.id, "node_type": node.node_type, "name": node.canonical_name}


def _search_edges(db: Session, node_ids: Sequence[int]) -> List[GraphEdge]:
    ids = list({int(i) for i in node_ids})
    if not ids:
        return []
    return (
        db.query(GraphEdge)
        .filter(or_(GraphEdge.from_node_id.in_(ids), GraphEdge.to_node_id.in_(ids)))
        .all()
    )


def tokenize(text: str) -> List[str]:
    """Query tokens for subgraph retrieval (stopwords removed)."""
    words = re.findall(r"[\w]+", normalize_name(text or ""))
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _score_nodes(db: Session, query_text: str) -> List[Tuple[int, float]]:
    """Score every node against the query: phrase hits beat token overlap.

    Returns ``(node_id, score)`` pairs with ``score > 0``, best first. The
    graph is small (hundreds of rows), so scoring in Python keeps the match
    rules identical across PostgreSQL and the SQLite test suite.
    """
    query_norm = normalize_name(query_text or "")
    tokens = tokenize(query_text or "")
    if not query_norm or not tokens:
        return []

    scored: List[Tuple[int, float]] = []
    for node in db.query(GraphNode).all():
        score = 0.0
        name = node.normalized_name or ""
        attrs = normalize_name(str(loads_json(node.attributes_json, {}) or {}))

        if len(query_norm) >= 4 and query_norm in name:
            score += 6.0
        if len(query_norm) >= 4 and query_norm in attrs:
            score += 3.0

        name_tokens = set(name.split())
        for token in tokens:
            if token in name_tokens:
                score += 2.0
            elif len(token) >= 4 and re.search(rf"(?<!\w){re.escape(token)}", name):
                score += 1.5
            if len(token) >= 4 and token in attrs:
                score += 0.5

        if score > 0:
            scored.append((node.id, score))

    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


# ============================================================
# Neighbours
# ============================================================

def neighbors(
    db: Session,
    node_id: Any,
    relation: Optional[str] = None,
    depth: int = 1,
) -> Dict[str, Any]:
    """Breadth-first neighbourhood of one node.

    Parameters
    ----------
    node_id:
        Node id or name.
    relation:
        Optional relation filter (validated against :class:`Relation`).
    depth:
        Number of hops (>= 1).

    Returns
    -------
    ``{node, depth, relation, nodes, edges, node_count, edge_count,
    review_required}``.
    """
    node = resolve_node(db, node_id)
    if node is None:
        return {"node": None, "depth": depth, "relation": relation,
                "nodes": [], "edges": [], "node_count": 0, "edge_count": 0,
                "review_required": True, "note": GRAPH_REVIEW_NOTE}

    if relation is not None and relation not in Relation.__members__ and relation not in {r.value for r in Relation}:
        raise ValueError(f"Unknown relation: {relation!r}")
    depth = max(1, int(depth))

    seen_nodes: Dict[int, GraphNode] = {node.id: node}
    seen_edges: Dict[int, GraphEdge] = {}
    frontier: List[int] = [node.id]

    for _ in range(depth):
        edges = _search_edges(db, frontier)
        next_frontier: List[int] = []
        for edge in edges:
            if relation is not None and edge.relation != relation:
                continue
            seen_edges[edge.id] = edge
            for neighbour_id in (edge.from_node_id, edge.to_node_id):
                if neighbour_id not in seen_nodes:
                    neighbour = db.get(GraphNode, neighbour_id)
                    if neighbour is not None:
                        seen_nodes[neighbour_id] = neighbour
                        next_frontier.append(neighbour_id)
        if not next_frontier:
            break
        frontier = next_frontier

    return {
        "node": node_to_dict(node),
        "depth": depth,
        "relation": relation,
        "nodes": [node_to_dict(n) for n in seen_nodes.values()],
        "edges": [edge_to_dict(e) for e in seen_edges.values()],
        "node_count": len(seen_nodes),
        "edge_count": len(seen_edges),
        "review_required": True,
        "note": GRAPH_REVIEW_NOTE,
    }


# ============================================================
# Shortest path
# ============================================================

def shortest_path(
    db: Session,
    source: Any,
    target: Any,
    max_depth: int = MAX_PATH_DEPTH,
) -> Optional[Dict[str, Any]]:
    """Unweighted BFS path between two nodes (edge direction is traversable
    in both directions, with the traversal direction recorded per hop).

    Returns ``None`` when either node is unknown or no path within
    ``max_depth`` hops exists. Otherwise a dict with ``steps``,
    ``human_readable`` and ``review_required: True``.
    """
    start = resolve_node(db, source)
    goal = resolve_node(db, target)
    if start is None or goal is None:
        return None
    if start.id == goal.id:
        return {
            "from": _node_ref(start),
            "to": _node_ref(goal),
            "hops": 0,
            "steps": [],
            "human_readable": start.canonical_name,
            "review_required": True,
            "note": GRAPH_REVIEW_NOTE,
        }

    # BFS over the edge table (depth tracked in the queue so the search is
    # O(V+E) instead of re-walking parents at every pop).
    parent: Dict[int, Tuple[int, str]] = {}  # node_id -> (edge_id, direction)
    visited = {start.id}
    queue: deque = deque([(start.id, 0)])

    while queue:
        current_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in _search_edges(db, [current_id]):
            if edge.from_node_id == current_id:
                neighbour_id, direction = edge.to_node_id, "forward"
            else:
                neighbour_id, direction = edge.from_node_id, "reverse"
            if neighbour_id in visited:
                continue
            visited.add(neighbour_id)
            parent[neighbour_id] = (edge.id, direction)
            if neighbour_id == goal.id:
                queue.clear()
                break
            queue.append((neighbour_id, depth + 1))

    if goal.id not in parent:
        return None

    # Reconstruct the walk.
    steps: List[Dict[str, Any]] = []
    cursor = goal.id
    while cursor != start.id:
        edge_id, direction = parent[cursor]
        edge = db.get(GraphEdge, edge_id)
        if edge is None:  # pragma: no cover - concurrent delete
            return None
        if direction == "forward":
            previous_id = edge.from_node_id
        else:
            previous_id = edge.to_node_id
        previous = db.get(GraphNode, previous_id)
        current = db.get(GraphNode, cursor)
        steps.append(
            {
                "edge_id": edge.id,
                "relation": edge.relation,
                "direction": direction,
                "weight": edge.weight,
                "from": _node_ref(previous),
                "to": _node_ref(current),
                "traversed_to": _node_ref(current),
                "evidence": loads_json(edge.evidence_json, {}),
            }
        )
        cursor = previous_id
    steps.reverse()

    chain: List[str] = [start.canonical_name]
    for step in steps:
        chain.append(step["relation"])
        chain.append(step["traversed_to"]["name"])

    return {
        "from": _node_ref(start),
        "to": _node_ref(goal),
        "hops": len(steps),
        "steps": steps,
        "human_readable": " -> ".join(chain),
        "review_required": True,
        "note": GRAPH_REVIEW_NOTE,
    }


# ============================================================
# Reasoning paths for a product + target IP route
# ============================================================

def _find_product_node(db: Session, product_id: int) -> Optional[GraphNode]:
    for node in db.query(GraphNode).filter(GraphNode.node_type == NodeType.PRODUCT.value).all():
        attrs = loads_json(node.attributes_json, {})
        if attrs.get("product_id") == product_id:
            return node
    return None


def _resolve_ip_type(db: Session, target: Any) -> Optional[GraphNode]:
    if target is None:
        return None
    if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
        node = resolve_node(db, target)
        if node is not None and node.node_type == NodeType.IP_TYPE.value:
            return node
    key = str(target).strip()
    route_name = IP_ROUTE_KEYS.get(key) or key
    node = resolve_node(db, route_name)
    if node is not None and node.node_type == NodeType.IP_TYPE.value:
        return node
    wanted = normalize_name(route_name)
    for node in db.query(GraphNode).filter(GraphNode.node_type == NodeType.IP_TYPE.value).all():
        if node.normalized_name == wanted:
            return node
    return None


def reasoning_paths(
    db: Session,
    product_id: int,
    target_ip_type: Any,
) -> List[Dict[str, Any]]:
    """Multi-hop reasoning chain: product -> ... -> target IP route.

    Returns a list of path dicts (empty when either endpoint is unknown or no
    path exists). Each dict has the alternating relation chain the spec asks
    for, e.g.::

        Ashwagandha Capsule -Classified_As-> Classical/Traditional Formulation
        -Barred_By-> Section 3(p) (Patents Act 1970) -Implemented_By->
        Patents Act 1970 -Governs-> Patent
        - therefore consider reviewing Traditional Knowledge,
        Geographical Indication (GI) and Trade Secret instead (review required)

    The chain is a *relational path, not a legal conclusion*: ``review_required``
    is always ``True`` and no eligibility/approval statement is ever produced.
    """
    product_node = _find_product_node(db, product_id)
    route_node = _resolve_ip_type(db, target_ip_type)
    if product_node is None or route_node is None:
        return []

    path = shortest_path(db, product_node.id, route_node.id, max_depth=MAX_PATH_DEPTH)
    if path is None:
        return []

    barriers = [
        step
        for step in path["steps"]
        if step["relation"] == Relation.BARRED_BY.value
    ]
    path_names = {path["from"]["name"]}
    for step in path["steps"]:
        path_names.add(step["from"]["name"])
        path_names.add(step["to"]["name"])

    if barriers:
        alternatives = [
            route
            for route in ALTERNATIVE_ROUTE_ORDER
            if route not in path_names
        ][:3]
        if alternatives:
            suffix = (
                " - therefore consider reviewing "
                + ", ".join(alternatives)
                + " instead (review required)"
            )
        else:  # pragma: no cover - every route already on the path
            suffix = " - review required"
    else:
        suffix = " - preliminary relational path; professional review required"

    chain = path["human_readable"] + suffix

    return [
        {
            "from": _node_ref(product_node),
            "to": _node_ref(route_node),
            "target_route": route_node.canonical_name,
            "hops": path["hops"],
            "steps": path["steps"],
            "chain": chain,
            "has_barrier": bool(barriers),
            "barred_by": [
                step["to"]["name"] if step["direction"] == "forward" else step["from"]["name"]
                for step in barriers
            ],
            "review_required": True,
            "note": GRAPH_REVIEW_NOTE,
        }
    ]


# ============================================================
# Subgraph retrieval for prompts
# ============================================================

def graph_context(db: Session, query_text: str, limit: int = 8) -> Dict[str, Any]:
    """Most relevant subgraph for a free-text query.

    Scores nodes on normalised-name / attribute overlap, keeps the best
    ``limit`` matches, and expands them by one hop. Always returns
    ``review_required: True`` - the caller may inject the nodes and edges into
    a prompt, never a conclusion.
    """
    limit = max(1, int(limit))
    scored = _score_nodes(db, query_text)
    seed_ids = [node_id for node_id, _ in scored[:limit]]

    nodes: Dict[int, GraphNode] = {}
    for node_id in seed_ids:
        node = db.get(GraphNode, node_id)
        if node is not None:
            nodes[node_id] = node

    edges: Dict[int, GraphEdge] = {}
    if nodes:
        for edge in _search_edges(db, list(nodes.keys())):
            edges[edge.id] = edge
        # one extra hop so the matched nodes arrive with their context
        neighbour_ids = [
            nid for edge in edges.values() for nid in (edge.from_node_id, edge.to_node_id)
            if nid not in nodes
        ]
        for edge in _search_edges(db, neighbour_ids):
            edges[edge.id] = edge
        for node_id in {nid for edge in edges.values() for nid in (edge.from_node_id, edge.to_node_id)}:
            if node_id not in nodes:
                node = db.get(GraphNode, node_id)
                if node is not None:
                    nodes[node_id] = node

    scores = {str(node_id): score for node_id, score in scored if node_id in nodes}
    return {
        "query": query_text,
        "matched_node_ids": seed_ids,
        "scores": scores,
        "nodes": [node_to_dict(n) for n in nodes.values()],
        "edges": [edge_to_dict(e) for e in edges.values()],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "review_required": True,
        "note": GRAPH_REVIEW_NOTE,
    }


def query_paths(db: Session, query_text: str, max_pairs: int = 3) -> List[Dict[str, Any]]:
    """Short relational paths between the concepts a query matched.

    Used by the agent when there is no product context: if a query mentions
    two things the graph knows and they are connected, the connecting path is
    exactly the "deepened multi-step reasoning" evidence the answer can rest
    on. Always ``review_required: True``.
    """
    scored = _score_nodes(db, query_text)
    matched = [node_id for node_id, _ in scored[:4]]
    paths: List[Dict[str, Any]] = []
    for i in range(len(matched)):
        for j in range(i + 1, len(matched)):
            if len(paths) >= max_pairs:
                return paths
            path = shortest_path(db, matched[i], matched[j], max_depth=4)
            if path is not None and path["hops"] > 0:
                paths.append(path)
    return paths
