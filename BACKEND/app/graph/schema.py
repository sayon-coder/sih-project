"""
Relational knowledge-graph schema (Stage 2 of the problem statement's staged
build).

Two tables carry the whole graph:

* ``graph_nodes`` - one row per entity (statute, rule, treaty, IP route,
  formulation category, product, ingredient, botanical species, jurisdiction,
  registry, case, obligation, regulator, corpus document). The node is unique
  on ``normalized_name``, which is what makes the builder idempotent: re-running
  it upserts instead of duplicating.

* ``graph_edges`` - one row per typed, directed relation between two nodes,
  with a weight, a JSON ``evidence`` payload (why the edge exists: which
  analysis, document or seed row produced it) and an optional
  ``source_document_id`` linking back to the corpus. Unique on
  ``(from_node_id, to_node_id, relation)``.

Nothing in these tables is an inference the platform invented at query time:
the builder only writes edges it can point at recorded data or the hard-coded
regulatory spine in ``app.graph.entities``.
"""
from __future__ import annotations

import enum
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


# ============================================================
# Enumerations
# ============================================================

class NodeType(str, enum.Enum):
    """Every kind of entity the knowledge graph models.

    ``CORPUS_DOCUMENT`` is a deliberate extension of the thirteen required
    types: without it there would be no node to hang the "corpus document ->
    statute" provenance edges on (the spec explicitly requires those edges).
    """

    STATUTE = "STATUTE"
    RULE = "RULE"
    TREATY = "TREATY"
    IP_TYPE = "IP_TYPE"
    FORMULATION_CATEGORY = "FORMULATION_CATEGORY"
    PRODUCT = "PRODUCT"
    INGREDIENT = "INGREDIENT"
    BOTANICAL_SPECIES = "BOTANICAL_SPECIES"
    JURISDICTION = "JURISDICTION"
    REGISTRY = "REGISTRY"
    CASE = "CASE"
    OBLIGATION = "OBLIGATION"
    REGULATOR = "REGULATOR"
    CORPUS_DOCUMENT = "CORPUS_DOCUMENT"


class Relation(str, enum.Enum):
    """Typed, directed relations between nodes.

    ``TEXT_OF`` is an extension: it carries the required
    "corpus document -> statute" edges (the document is the official text of
    the instrument).

    ``Prior_Art_For`` and ``Conflicts_With`` are part of the vocabulary but
    deliberately have no builder stage: the platform's recorded patent records
    are *candidate* overlaps, not established prior art, and emitting either
    edge would assert a legal conclusion the system has not established.
    """

    GOVERNS = "Governs"
    AMENDS = "Amends"
    IMPLEMENTED_BY = "Implemented_By"
    REQUIRES_PERMIT_FROM = "Requires_Permit_From"
    CONFLICTS_WITH = "Conflicts_With"
    BARRED_BY = "Barred_By"
    PROTECTS = "Protects"
    CLASSIFIED_AS = "Classified_As"
    SOURCES_FROM = "Sources_From"
    REGISTERED_IN = "Registered_In"
    APPLIES_IN = "Applies_In"
    PRIOR_ART_FOR = "Prior_Art_For"
    BENEFIT_SHARING_OBLIGATION = "Benefit_Sharing_Obligation"
    TEXT_OF = "Text_Of"


#: Node types are stable machine values; allowed lists for validation.
NODE_TYPE_VALUES = {member.value for member in NodeType}
RELATION_VALUES = {member.value for member in Relation}

#: Appended to every graph-derived payload: graph output is relational
#: reasoning support, never a conclusive legal statement.
GRAPH_REVIEW_NOTE = (
    "Knowledge-graph output is relational reasoning support, not a legal "
    "conclusion. Professional review required."
)


# ============================================================
# Normalisation / JSON helpers
# ============================================================

def normalize_name(name: str) -> str:
    """Canonical key used for node identity (upsert target).

    Lowercases, applies NFKC compatibility normalisation, replaces every
    run of non-alphanumeric characters (keeping unicode letters, so Sanskrit
    or regional-script names survive) with a single space, and collapses
    whitespace. Two spellings of the same instrument therefore resolve to one
    node.
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = text.lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def loads_json(value: Any, default: Any) -> Any:
    """Parse a JSON text column, tolerating dict input and bad data."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed is not None else default


def dumps_json(value: Any) -> Optional[str]:
    """Serialise a value for a JSON text column (None stays NULL)."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:  # pragma: no cover - already a string
        return str(value)


def node_to_dict(node: Optional["GraphNode"]) -> Dict[str, Any]:
    """JSON-serialisable view of a node (API / prompt injection)."""
    if node is None:
        return {}
    return {
        "id": node.id,
        "node_type": node.node_type,
        "canonical_name": node.canonical_name,
        "normalized_name": node.normalized_name,
        "attributes": loads_json(node.attributes_json, {}),
        "source_document_ids": loads_json(node.source_document_ids, []),
        "jurisdiction": node.jurisdiction,
        "created_at": _iso(node.created_at),
    }


def edge_to_dict(edge: Optional["GraphEdge"]) -> Dict[str, Any]:
    """JSON-serialisable view of an edge."""
    if edge is None:
        return {}
    return {
        "id": edge.id,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "relation": edge.relation,
        "weight": edge.weight,
        "evidence": loads_json(edge.evidence_json, {}),
        "source_document_id": edge.source_document_id,
        "created_at": _iso(edge.created_at),
    }


# ============================================================
# Tables
# ============================================================

class GraphNode(Base):
    """One entity in the relational knowledge graph."""

    __tablename__ = "graph_nodes"

    id = Column(Integer, primary_key=True, index=True)
    node_type = Column(String(40), nullable=False, index=True)
    canonical_name = Column(String(500), nullable=False)
    #: Lowercased/punctuation-stripped identity key; unique by design so the
    #: builder can upsert safely and re-run without duplicating entities.
    normalized_name = Column(String(500), nullable=False, unique=True, index=True)
    #: Free-form JSON attributes (year, route_key, product_id, note, ...).
    attributes_json = Column(Text, nullable=True)
    #: JSON array of source_documents.id values this node is evidenced by.
    source_document_ids = Column(Text, nullable=True)
    jurisdiction = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_graph_nodes_normalized_name"),
        Index("ix_graph_nodes_type_name", "node_type", "normalized_name"),
    )

    def __repr__(self) -> str:
        return f"<GraphNode(id={self.id}, type={self.node_type}, name={self.canonical_name!r})>"


class GraphEdge(Base):
    """A typed, directed, weighted relation between two graph nodes."""

    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    from_node_id = Column(
        Integer,
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_node_id = Column(
        Integer,
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation = Column(String(60), nullable=False, index=True)
    weight = Column(Float, nullable=False, default=1.0)
    #: JSON: why the edge exists (seed entry, analysis id, matched alias, ...).
    evidence_json = Column(Text, nullable=True)
    source_document_id = Column(
        Integer,
        ForeignKey("source_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "from_node_id",
            "to_node_id",
            "relation",
            name="uq_graph_edges_triple",
        ),
        Index("ix_graph_edges_from_relation", "from_node_id", "relation"),
        Index("ix_graph_edges_to_relation", "to_node_id", "relation"),
    )

    def __repr__(self) -> str:
        return (
            f"<GraphEdge(id={self.id}, {self.from_node_id}-[{self.relation}]->"
            f"{self.to_node_id})>"
        )
