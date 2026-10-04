"""Knowledge graph and agentic orchestration tables.

Revision ID: 013
Revises: 012
Create Date: 2026-10-03

Creates ``graph_nodes`` / ``graph_edges`` (``app.graph.schema``) and
``agent_runs`` (``app.agents.orchestrator``) - the tables the graph and
agent routers serve. Nodes upsert on the unique normalised name; edges on
the (from, to, relation) triple. ``downgrade`` drops the three tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(length=40), nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=True),
        sa.Column("source_document_ids", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_name", name="uq_graph_nodes_normalized_name"
        ),
    )
    op.create_index(op.f("ix_graph_nodes_id"), "graph_nodes", ["id"], unique=False)
    op.create_index(
        op.f("ix_graph_nodes_node_type"),
        "graph_nodes",
        ["node_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_graph_nodes_normalized_name"),
        "graph_nodes",
        ["normalized_name"],
        unique=True,
    )
    op.create_index(
        op.f("ix_graph_nodes_jurisdiction"),
        "graph_nodes",
        ["jurisdiction"],
        unique=False,
    )
    op.create_index(
        "ix_graph_nodes_type_name",
        "graph_nodes",
        ["node_type", "normalized_name"],
        unique=False,
    )

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=60), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_node_id"], ["graph_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["to_node_id"], ["graph_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_node_id",
            "to_node_id",
            "relation",
            name="uq_graph_edges_triple",
        ),
    )
    op.create_index(op.f("ix_graph_edges_id"), "graph_edges", ["id"], unique=False)
    op.create_index(
        op.f("ix_graph_edges_from_node_id"),
        "graph_edges",
        ["from_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_graph_edges_to_node_id"),
        "graph_edges",
        ["to_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_graph_edges_relation"),
        "graph_edges",
        ["relation"],
        unique=False,
    )
    op.create_index(
        "ix_graph_edges_from_relation",
        "graph_edges",
        ["from_node_id", "relation"],
        unique=False,
    )
    op.create_index(
        "ix_graph_edges_to_relation",
        "graph_edges",
        ["to_node_id", "relation"],
        unique=False,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=True),
        sa.Column("trace_json", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("graph_paths_json", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("confidence_reason", sa.Text(), nullable=True),
        sa.Column("insufficient_evidence", sa.Boolean(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("steps_used", sa.Integer(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["product_version_id"],
            ["product_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_id"), "agent_runs", ["id"], unique=False)
    op.create_index(
        op.f("ix_agent_runs_user_id"), "agent_runs", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_runs_product_version_id"),
        "agent_runs",
        ["product_version_id"],
        unique=False,
    )


def downgrade() -> None:
    for table, indexes in (
        ("agent_runs", ["id", "user_id", "product_version_id"]),
        (
            "graph_edges",
            ["id", "from_node_id", "to_node_id", "relation"],
        ),
        ("graph_nodes", ["id", "node_type", "normalized_name", "jurisdiction"]),
    ):
        for column in indexes:
            op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_index("ix_graph_nodes_type_name", table_name="graph_nodes")
    op.drop_index("ix_graph_edges_from_relation", table_name="graph_edges")
    op.drop_index("ix_graph_edges_to_relation", table_name="graph_edges")
    op.drop_table("agent_runs")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
