"""
Deterministic knowledge-graph builder.

``build_or_refresh_graph(db, full=False)`` populates ``graph_nodes`` /
``graph_edges`` from data the system already holds - never from model output
and never from anything invented at run time:

1. the fixed regulatory spine in :mod:`app.graph.entities` (statutes, rules,
   treaties, registries, regulators, IP routes, formulation categories,
   obligations, jurisdictions);
2. ingredient -> botanical-species -> product edges extracted from the
   ``ingredients`` table;
3. corpus document -> instrument edges from ``SourceDocument`` metadata, only
   on a confident normalised-name match (word-boundary alias match plus a
   jurisdiction compatibility check - anything else is skipped and counted);
4. ``PRODUCT -Classified_As-> FORMULATION_CATEGORY`` edges from recorded
   analyses (and the product's own recorded category as a fallback);
5. ``PRODUCT -Benefit_Sharing_Obligation-> OBLIGATION`` edges from recorded
   biodiversity screenings that flagged ABS considerations.

The builder is idempotent: nodes upsert on ``normalized_name`` and edges on
``(from_node_id, to_node_id, relation)``, so a re-run creates nothing new and
only refreshes evidence. ``full=True`` wipes the graph first.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.graph.entities import (
    FORMULATION_CATEGORIES,
    SEED_EDGES,
    SEED_NODES,
)
from app.graph.schema import (
    GraphEdge,
    GraphNode,
    NodeType,
    Relation,
    dumps_json,
    loads_json,
    normalize_name,
)

logger = logging.getLogger(__name__)

#: Minimum normalised alias length for corpus matching (word-boundary).
#: Short strings like "in", "cbd" or "pct" are too easy to hit by accident.
MIN_ALIAS_LENGTH = 5

#: Node types whose aliases may claim a corpus document as their official text.
INSTRUMENT_TYPES = {
    NodeType.STATUTE.value,
    NodeType.RULE.value,
    NodeType.TREATY.value,
    NodeType.OBLIGATION.value,
}

#: Jurisdiction codes seen in corpus metadata -> comparable names.
_JURISDICTION_ALIASES = {
    "in": "india",
    "ind": "india",
    "int": "international",
    "intl": "international",
    "global": "international",
    "world": "international",
}


# ============================================================
# Upsert primitives (public: tests and tooling use them directly)
# ============================================================

def _merge_attributes(existing: Dict, incoming: Dict) -> Dict:
    """Merge new attribute values into the stored ones.

    List values are unioned (so ``ingredient_ids`` accumulates instead of
    flapping between runs); scalars are replaced by the newest value.
    """
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if key.endswith("_ids") and isinstance(value, list):
            current = merged.get(key)
            if not isinstance(current, list):
                current = [current] if current else []
            merged[key] = sorted(set(current) | set(value))
        elif value is not None:
            merged[key] = value
    return merged


def upsert_node(
    db: Session,
    node_type: NodeType,
    canonical_name: str,
    *,
    identity: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    attributes: Optional[Dict] = None,
    source_document_ids: Optional[Sequence[int]] = None,
    stats: Optional[Dict] = None,
) -> GraphNode:
    """Create or refresh a node keyed by its normalised name.

    ``identity`` defaults to ``canonical_name``; corpus documents pass their
    own identity (title + document id) so two documents that happen to share a
    title never collapse into one node.

    ``stats`` (when given) records ``nodes_created`` / ``nodes_updated``.
    """
    if isinstance(node_type, NodeType):
        node_type = node_type.value
    key = normalize_name(identity or canonical_name)

    node = (
        db.query(GraphNode)
        .filter(GraphNode.normalized_name == key)
        .first()
    )

    if node is None:
        node = GraphNode(
            node_type=node_type,
            canonical_name=canonical_name,
            normalized_name=key,
            attributes_json=dumps_json(dict(attributes or {})),
            source_document_ids=(
                dumps_json(sorted({int(i) for i in source_document_ids}))
                if source_document_ids
                else None
            ),
            jurisdiction=jurisdiction,
        )
        db.add(node)
        db.flush()
        if stats is not None:
            stats["nodes_created"] = stats.get("nodes_created", 0) + 1
        return node

    # Existing node: refresh attributes / jurisdiction, never the identity.
    merged = _merge_attributes(loads_json(node.attributes_json, {}), dict(attributes or {}))
    node.attributes_json = dumps_json(merged)
    if jurisdiction and not node.jurisdiction:
        node.jurisdiction = jurisdiction
    if source_document_ids:
        current = loads_json(node.source_document_ids, []) or []
        node.source_document_ids = dumps_json(sorted(set(current) | {int(i) for i in source_document_ids}))
    if stats is not None:
        stats["nodes_updated"] = stats.get("nodes_updated", 0) + 1
    db.flush()
    return node


def upsert_edge(
    db: Session,
    from_node: GraphNode,
    to_node: GraphNode,
    relation: Relation,
    *,
    weight: float = 1.0,
    evidence: Optional[Dict] = None,
    source_document_id: Optional[int] = None,
    stats: Optional[Dict] = None,
) -> GraphEdge:
    """Create or refresh an edge keyed by ``(from, to, relation)``."""
    if isinstance(relation, Relation):
        relation = relation.value

    edge = (
        db.query(GraphEdge)
        .filter(
            GraphEdge.from_node_id == from_node.id,
            GraphEdge.to_node_id == to_node.id,
            GraphEdge.relation == relation,
        )
        .first()
    )

    if edge is None:
        edge = GraphEdge(
            from_node_id=from_node.id,
            to_node_id=to_node.id,
            relation=relation,
            weight=float(weight),
            evidence_json=dumps_json(dict(evidence or {})),
            source_document_id=source_document_id,
        )
        db.add(edge)
        db.flush()
        if stats is not None:
            stats["edges_created"] = stats.get("edges_created", 0) + 1
        return edge

    edge.weight = float(weight)
    merged = _merge_attributes(loads_json(edge.evidence_json, {}), dict(evidence or {}))
    edge.evidence_json = dumps_json(merged)
    if source_document_id:
        edge.source_document_id = source_document_id
    if stats is not None:
        stats["edges_updated"] = stats.get("edges_updated", 0) + 1
    db.flush()
    return edge


# ============================================================
# Stage 1 - the regulatory spine
# ============================================================

def _seed_spine(db: Session, stats: Dict) -> Dict[str, GraphNode]:
    """Write the hard-coded reference instruments, routes and categories."""
    nodes: Dict[str, GraphNode] = {}
    for seed in SEED_NODES:
        nodes[seed["canonical_name"]] = upsert_node(
            db,
            seed["node_type"],
            seed["canonical_name"],
            jurisdiction=seed.get("jurisdiction"),
            attributes=seed.get("attributes"),
            stats=stats,
        )

    for seed_edge in SEED_EDGES:
        src = nodes.get(seed_edge["from"])
        dst = nodes.get(seed_edge["to"])
        if src is None or dst is None:  # pragma: no cover - seed typo guard
            logger.error(
                "Seed edge references unknown node: %s -> %s",
                seed_edge["from"],
                seed_edge["to"],
            )
            continue
        evidence = dict(seed_edge.get("evidence") or {})
        evidence.setdefault("basis", "regulatory_spine")
        upsert_edge(
            db,
            src,
            dst,
            seed_edge["relation"],
            weight=seed_edge.get("weight", 1.0),
            evidence=evidence,
            stats=stats,
        )

    stats["spine_nodes"] = len(SEED_NODES)
    stats["spine_edges"] = len(SEED_EDGES)
    return nodes


# ============================================================
# Stage 3 - corpus documents -> instruments
# ============================================================

def _build_alias_index(seed_nodes: Sequence[Dict]) -> List[Tuple[str, Dict]]:
    """(normalised alias, seed node) pairs eligible for corpus matching."""
    entries: List[Tuple[str, Dict]] = []
    for seed in seed_nodes:
        if seed["node_type"].value not in INSTRUMENT_TYPES:
            continue
        for alias in [seed["canonical_name"], *seed.get("aliases", [])]:
            normalised = normalize_name(alias)
            if len(normalised) >= MIN_ALIAS_LENGTH:
                entries.append((normalised, seed))
    # Longest alias first: the most specific match wins.
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def _match_instrument(
    text: str, entries: Sequence[Tuple[str, Dict]]
) -> Optional[Tuple[Dict, str]]:
    """First (longest) alias found as a whole word in ``text``."""
    for alias, seed in entries:
        if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text):
            return seed, alias
    return None


def _jurisdiction_compatible(doc_jurisdiction: Optional[str], node_jurisdiction: Optional[str]) -> bool:
    """Conservative compatibility check; unknown values never block a match."""
    if not node_jurisdiction or node_jurisdiction == "International":
        return True
    if not doc_jurisdiction:
        return True
    doc = normalize_name(doc_jurisdiction)
    doc = _JURISDICTION_ALIASES.get(doc, doc)
    node = normalize_name(node_jurisdiction)
    node = _JURISDICTION_ALIASES.get(node, node)
    return doc == node or node in doc.split() or doc in node.split()


def _seed_corpus_documents(db: Session, stats: Dict) -> None:
    """Link corpus documents to instruments on confident name matches only."""
    from app.models.rag_models import SourceDocument

    entries = _build_alias_index(SEED_NODES)
    documents = db.query(SourceDocument).order_by(SourceDocument.id.asc()).all()
    matched = 0
    skipped = 0

    for doc in documents:
        haystack = normalize_name(
            " ".join(part for part in [doc.title or "", doc.source_url or ""] if part)
        )
        if not haystack:
            continue
        hit = _match_instrument(haystack, entries)
        if hit is None:
            skipped += 1
            continue
        seed, alias = hit
        if not _jurisdiction_compatible(doc.jurisdiction, seed.get("jurisdiction")):
            skipped += 1
            logger.info(
                "Graph: document %s (%r) skipped - jurisdiction %r vs node %r",
                doc.id, doc.title, doc.jurisdiction, seed.get("jurisdiction"),
            )
            continue

        doc_node = upsert_node(
            db,
            NodeType.CORPUS_DOCUMENT,
            doc.title or f"Document #{doc.id}",
            identity=f"{doc.title or ''} document {doc.id}",
            jurisdiction=doc.jurisdiction,
            attributes={
                "document_id": doc.id,
                "source_type": doc.source_type,
                "status": doc.status,
                "source_url": doc.source_url,
                "is_public": bool(doc.is_public),
                "chunk_count": doc.chunk_count or 0,
            },
            source_document_ids=[doc.id],
            stats=stats,
        )
        instrument_node = upsert_node(
            db,
            seed["node_type"],
            seed["canonical_name"],
            jurisdiction=seed.get("jurisdiction"),
            attributes=seed.get("attributes"),
            source_document_ids=[doc.id],
        )
        upsert_edge(
            db,
            doc_node,
            instrument_node,
            Relation.TEXT_OF,
            weight=1.0,
            evidence={
                "basis": "source_document",
                "matched_alias": alias,
                "document_title": doc.title,
                "document_id": doc.id,
                "jurisdiction": doc.jurisdiction,
            },
            source_document_id=doc.id,
            stats=stats,
        )
        matched += 1

    stats["documents_matched"] = matched
    stats["documents_skipped"] = skipped


# ============================================================
# Stage 2 - ingredients, species, products, markets
# ============================================================

def _extract_ingredients(db: Session, stats: Dict) -> None:
    """Ingredient / botanical-species / product nodes and Sources_From edges."""
    from app.models.ingredient_models import Ingredient, TargetMarket
    from app.models.product_models import Product, ProductVersion

    products = (
        db.query(Product)
        .filter(Product.is_active == True)  # noqa: E712
        .order_by(Product.id.asc())
        .all()
    )
    stats["products"] = len(products)

    for product in products:
        product_node = upsert_node(
            db,
            NodeType.PRODUCT,
            product.name,
            attributes={"product_id": product.id, "name": product.name},
            stats=stats,
        )

        version_ids = [
            row[0]
            for row in db.query(ProductVersion.id)
            .filter(ProductVersion.product_id == product.id)
            .all()
        ]
        if not version_ids:
            continue

        ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.product_version_id.in_(version_ids))
            .order_by(Ingredient.id.asc())
            .all()
        )
        for ingredient in ingredients:
            attrs: Dict = {"common_name": ingredient.common_name}
            if ingredient.sanskrit_name:
                attrs["sanskrit_name"] = ingredient.sanskrit_name
            if ingredient.plant_part:
                attrs["plant_part"] = ingredient.plant_part
            attrs["ingredient_ids"] = [ingredient.id]

            ingredient_node = upsert_node(
                db,
                NodeType.INGREDIENT,
                ingredient.common_name,
                attributes=attrs,
                stats=stats,
            )
            stats["ingredients"] = stats.get("ingredients", 0) + 1

            if not ingredient.botanical_name:
                continue
            species_node = upsert_node(
                db,
                NodeType.BOTANICAL_SPECIES,
                ingredient.botanical_name,
                attributes={"botanical_name": ingredient.botanical_name},
                stats=stats,
            )
            upsert_edge(
                db,
                ingredient_node,
                species_node,
                Relation.SOURCES_FROM,
                evidence={
                    "basis": "ingredients",
                    "ingredient_id": ingredient.id,
                    "product_version_id": ingredient.product_version_id,
                },
                stats=stats,
            )
            upsert_edge(
                db,
                product_node,
                species_node,
                Relation.SOURCES_FROM,
                evidence={
                    "basis": "ingredients",
                    "ingredient_id": ingredient.id,
                    "product_version_id": ingredient.product_version_id,
                },
                stats=stats,
            )

        markets = (
            db.query(TargetMarket)
            .filter(TargetMarket.product_version_id.in_(version_ids))
            .all()
        )
        for market in markets:
            if not market.country:
                continue
            upsert_node(
                db,
                NodeType.JURISDICTION,
                market.country,
                attributes={"country": market.country, "region": market.region},
                stats=stats,
            )


# ============================================================
# Stage 4 - recorded classifications
# ============================================================

def _extract_classifications(db: Session, stats: Dict) -> None:
    """PRODUCT -Classified_As-> FORMULATION_CATEGORY from recorded analyses."""
    from app.models.analysis_models import Analysis, AnalysisStatus, AnalysisType
    from app.models.product_models import Product

    # product_id -> (category_key, evidence); analyses win over the product row.
    classified: Dict[int, Tuple[str, Dict]] = {}

    rows = (
        db.query(Analysis)
        .filter(
            Analysis.status == AnalysisStatus.COMPLETED,
            Analysis.results.isnot(None),
            Analysis.analysis_type.in_(
                [AnalysisType.PRODUCT_CLASSIFICATION, AnalysisType.COMPREHENSIVE]
            ),
        )
        .order_by(Analysis.id.asc())
        .all()
    )
    for row in rows:
        try:
            payload = json.loads(row.results or "{}")
        except (TypeError, ValueError):
            continue
        classification = payload.get("product_classification") or {}
        category = (classification.get("category") or "").strip()
        if not category or classification.get("status") == "UNRESOLVED":
            continue
        product_id = _product_id_for_version(db, row.product_version_id)
        if product_id is None:
            continue
        classified[product_id] = (
            category,
            {
                "basis": "analysis",
                "analysis_id": row.id,
                "analysis_type": getattr(row.analysis_type, "value", row.analysis_type),
                "category": category,
                "preliminary": True,
                "review_required": True,
            },
        )

    # Fallback: the category recorded directly on the product row.
    for product_id, category in (
        db.query(Product.id, Product.category)
        .filter(Product.category.isnot(None), Product.is_active == True)  # noqa: E712
        .all()
    ):
        if product_id in classified:
            continue
        key = category.value if hasattr(category, "value") else str(category)
        classified[product_id] = (
            key,
            {
                "basis": "product.category",
                "category": key,
                "preliminary": True,
                "review_required": True,
            },
        )

    for product_id, (category_key, evidence) in sorted(classified.items()):
        product = db.get(Product, product_id)
        if product is None:
            continue
        canonical = FORMULATION_CATEGORIES.get(category_key)
        if canonical is None:
            # A recorded category the platform does not model: still link it,
            # rather than dropping recorded data.
            canonical = category_key.replace("_", " ").capitalize()
        product_node = upsert_node(
            db,
            NodeType.PRODUCT,
            product.name,
            attributes={"product_id": product.id, "name": product.name},
            stats=stats,
        )
        category_node = upsert_node(
            db,
            NodeType.FORMULATION_CATEGORY,
            canonical,
            attributes={"category_key": category_key},
            stats=stats,
        )
        upsert_edge(
            db,
            product_node,
            category_node,
            Relation.CLASSIFIED_AS,
            weight=1.0,
            evidence=evidence,
            stats=stats,
        )
        stats["classifications"] = stats.get("classifications", 0) + 1


def _product_id_for_version(db: Session, version_id: Optional[int]) -> Optional[int]:
    if not version_id:
        return None
    from app.models.product_models import ProductVersion

    row = (
        db.query(ProductVersion.product_id)
        .filter(ProductVersion.id == version_id)
        .first()
    )
    return row[0] if row else None


# ============================================================
# Stage 5 - recorded biodiversity screenings
# ============================================================

def _extract_screening_obligations(db: Session, stats: Dict) -> None:
    """PRODUCT -Benefit_Sharing_Obligation-> OBLIGATION, only when a recorded
    screening actually flagged ABS considerations."""
    from app.models.analysis_models import Analysis, AnalysisStatus, AnalysisType
    from app.models.product_models import Product

    rows = (
        db.query(Analysis)
        .filter(
            Analysis.status == AnalysisStatus.COMPLETED,
            Analysis.analysis_type == AnalysisType.BIODIVERSITY_SCREENING,
            Analysis.results.isnot(None),
        )
        .order_by(Analysis.id.asc())
        .all()
    )
    for row in rows:
        try:
            payload = json.loads(row.results or "{}")
        except (TypeError, ValueError):
            continue
        status = payload.get("status")
        if status not in ("POTENTIALLY_RELEVANT", "REVIEW_RECOMMENDED"):
            continue
        product_id = _product_id_for_version(db, row.product_version_id)
        if product_id is None:
            continue
        product = db.get(Product, product_id)
        if product is None:
            continue
        product_node = upsert_node(
            db,
            NodeType.PRODUCT,
            product.name,
            attributes={"product_id": product.id, "name": product.name},
            stats=stats,
        )
        obligation_node = upsert_node(
            db,
            NodeType.OBLIGATION,
            "Access and Benefit-Sharing Obligation",
            attributes={
                "instruments": [
                    "Convention on Biological Diversity 1992",
                    "Nagoya Protocol on Access and Benefit-Sharing 2010",
                    "Biological Diversity Act 2002",
                ],
                "review_required": True,
            },
            stats=stats,
        )
        upsert_edge(
            db,
            product_node,
            obligation_node,
            Relation.BENEFIT_SHARING_OBLIGATION,
            weight=0.9,
            evidence={
                "basis": "biodiversity_screening",
                "analysis_id": row.id,
                "status": status,
                "review_required": True,
                "note": (
                    "A recorded screening flagged access-and-benefit-sharing "
                    "considerations. This is not a determination that any "
                    "approval is required."
                ),
            },
            stats=stats,
        )
        stats["screening_obligations"] = stats.get("screening_obligations", 0) + 1


# ============================================================
# Entry point
# ============================================================

def build_or_refresh_graph(db: Session, *, full: bool = False) -> Dict:
    """Build (or refresh) the relational knowledge graph.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    full:
        When True, delete every node and edge first and rebuild from scratch.

    Returns
    -------
    Counts for the run (created/updated/totals per table plus per-stage
    counters). Safe to re-run: nodes upsert on normalised name and edges on
    ``(from, to, relation)``.
    """
    started = time.perf_counter()
    stats: Dict = {"full": bool(full)}

    try:
        if full:
            db.query(GraphEdge).delete(synchronize_session=False)
            db.query(GraphNode).delete(synchronize_session=False)
            db.flush()

        _seed_spine(db, stats)
        _seed_corpus_documents(db, stats)
        _extract_ingredients(db, stats)
        _extract_classifications(db, stats)
        _extract_screening_obligations(db, stats)

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Knowledge-graph build failed")
        raise

    stats["nodes_total"] = db.query(GraphNode).count()
    stats["edges_total"] = db.query(GraphEdge).count()
    stats.setdefault("documents_matched", 0)
    stats.setdefault("documents_skipped", 0)
    stats.setdefault("products", 0)
    stats.setdefault("ingredients", 0)
    stats.setdefault("classifications", 0)
    stats.setdefault("screening_obligations", 0)
    stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
    logger.info("Knowledge graph build: %s", stats)
    return stats
