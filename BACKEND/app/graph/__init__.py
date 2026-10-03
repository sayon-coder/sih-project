"""Relational knowledge graph: schema, static spine, builder and queries.

Only :mod:`app.graph.schema` and :mod:`app.graph.entities` are imported here
on purpose: ``app.models`` re-exports ``GraphNode`` / ``GraphEdge`` so the
tables register with ``Base.metadata`` for ``create_all`` and Alembic, and
importing the builder/query layers from this package would pull SQLAlchemy
sessions (and, via ``app.graph.builder``, the analysis modules) into that
import chain.

Import the other layers explicitly when needed::

    from app.graph.builder import build_or_refresh_graph
    from app.graph.query import neighbors, shortest_path, reasoning_paths
"""
from __future__ import annotations

from app.graph.entities import (
    CANONICAL_FORMULATION_CATEGORIES,
    FORMULATION_CATEGORIES,
    IP_ROUTE_KEYS,
    SEED_EDGES,
    SEED_NODES,
)
from app.graph.schema import (
    GRAPH_REVIEW_NOTE,
    NODE_TYPE_VALUES,
    RELATION_VALUES,
    GraphEdge,
    GraphNode,
    NodeType,
    Relation,
    dumps_json,
    edge_to_dict,
    loads_json,
    node_to_dict,
    normalize_name,
)

__all__ = [
    "CANONICAL_FORMULATION_CATEGORIES",
    "FORMULATION_CATEGORIES",
    "GRAPH_REVIEW_NOTE",
    "GraphEdge",
    "GraphNode",
    "IP_ROUTE_KEYS",
    "NODE_TYPE_VALUES",
    "NodeType",
    "RELATION_VALUES",
    "Relation",
    "SEED_EDGES",
    "SEED_NODES",
    "dumps_json",
    "edge_to_dict",
    "loads_json",
    "node_to_dict",
    "normalize_name",
]
