"""Product Passport and Versioning models

Revision ID: 002
Revises: 001
Create Date: 2026-09-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types (PostgreSQL doesn't support IF NOT EXISTS for types, so we drop first)
    op.execute("DO $$ BEGIN CREATE TYPE productcategory AS ENUM ('CLASSICAL_TRADITIONAL', 'PROPRIETARY_AYURVEDIC', 'POSSIBLE_MEDICINAL', 'AYURVEDA_AAHARA', 'POSSIBLE_COSMETIC', 'RESEARCH_PRODUCT', 'INDUSTRIAL_PRODUCT'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE sourcetype AS ENUM ('CULTIVATED', 'WILD', 'UNKNOWN'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE claimtype AS ENUM ('WELLNESS', 'THERAPEUTIC', 'NUTRITIONAL', 'COSMETIC', 'STRUCTURE_FUNCTION', 'TRADITIONAL_USE'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE evidencestatus AS ENUM ('USER_PROVIDED', 'NEEDS_EVIDENCE', 'PARTIALLY_SUPPORTED', 'SUPPORTED', 'EXPERT_VERIFIED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE evidencetype AS ENUM ('SCIENTIFIC_PAPER', 'CLINICAL_TRIAL', 'TRADITIONAL_TEXT', 'PHARMACOPOEIA', 'REGULATORY_DOCUMENT', 'OTHER'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE verificationstatus AS ENUM ('PENDING', 'VERIFIED', 'REJECTED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE analysistype AS ENUM ('PRODUCT_CLASSIFICATION', 'IP_ROUTE_MAP', 'PATENT_SCREENING', 'BIODIVERSITY_SCREENING', 'TK_SCREENING', 'PUBLIC_DISCLOSURE_REVIEW', 'COMPREHENSIVE'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE analysisstatus AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")

    # Create products table
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', postgresql.ENUM('CLASSICAL_TRADITIONAL', 'PROPRIETARY_AYURVEDIC', 'POSSIBLE_MEDICINAL', 'AYURVEDA_AAHARA', 'POSSIBLE_COSMETIC', 'RESEARCH_PRODUCT', 'INDUSTRIAL_PRODUCT', name='productcategory', create_type=False), nullable=True),
        sa.Column('current_version_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_category'), 'products', ['category'], unique=False)
    op.create_index(op.f('ix_products_created_by'), 'products', ['created_by'], unique=False)
    op.create_index(op.f('ix_products_id'), 'products', ['id'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)

    # Create product_versions table
    op.create_table(
        'product_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('snapshot_data', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_product_versions_created_at'), 'product_versions', ['created_at'], unique=False)
    op.create_index(op.f('ix_product_versions_created_by'), 'product_versions', ['created_by'], unique=False)
    op.create_index(op.f('ix_product_versions_id'), 'product_versions', ['id'], unique=False)
    op.create_index(op.f('ix_product_versions_product_id'), 'product_versions', ['product_id'], unique=False)

    # Add foreign key for products.current_version_id
    op.create_foreign_key(
        'fk_products_current_version_id',
        'products', 'product_versions',
        ['current_version_id'], ['id']
    )

    # Create ingredients table
    op.create_table(
        'ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('common_name', sa.String(length=255), nullable=False),
        sa.Column('botanical_name', sa.String(length=255), nullable=True),
        sa.Column('sanskrit_name', sa.String(length=255), nullable=True),
        sa.Column('plant_part', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('quantity_unit', sa.String(length=20), nullable=True),
        sa.Column('preparation_method', sa.Text(), nullable=True),
        sa.Column('source_type', postgresql.ENUM('CULTIVATED', 'WILD', 'UNKNOWN', name='sourcetype', create_type=False), nullable=True),
        sa.Column('source_location', sa.String(length=255), nullable=True),
        sa.Column('source_documentation', sa.Text(), nullable=True),
        sa.Column('provenance', sa.String(length=50), nullable=False, server_default='USER_PROVIDED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingredients_botanical_name'), 'ingredients', ['botanical_name'], unique=False)
    op.create_index(op.f('ix_ingredients_id'), 'ingredients', ['id'], unique=False)
    op.create_index(op.f('ix_ingredients_product_version_id'), 'ingredients', ['product_version_id'], unique=False)

    # Create formulations table
    op.create_table(
        'formulations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('process_description', sa.Text(), nullable=True),
        sa.Column('extraction_method', sa.String(length=100), nullable=True),
        sa.Column('solvent', sa.String(length=100), nullable=True),
        sa.Column('temperature', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('temperature_unit', sa.String(length=10), nullable=True, server_default='C'),
        sa.Column('pressure', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('pressure_unit', sa.String(length=20), nullable=True),
        sa.Column('duration', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('duration_unit', sa.String(length=20), nullable=True),
        sa.Column('concentration', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('other_parameters', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_formulations_id'), 'formulations', ['id'], unique=False)
    op.create_index(op.f('ix_formulations_product_version_id'), 'formulations', ['product_version_id'], unique=True)

    # Create claims table
    op.create_table(
        'claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('claim_text', sa.Text(), nullable=False),
        sa.Column('claim_type', postgresql.ENUM('WELLNESS', 'THERAPEUTIC', 'NUTRITIONAL', 'COSMETIC', 'STRUCTURE_FUNCTION', 'TRADITIONAL_USE', name='claimtype', create_type=False), nullable=True),
        sa.Column('evidence_status', postgresql.ENUM('USER_PROVIDED', 'NEEDS_EVIDENCE', 'PARTIALLY_SUPPORTED', 'SUPPORTED', 'EXPERT_VERIFIED', name='evidencestatus', create_type=False), nullable=False, server_default='USER_PROVIDED'),
        sa.Column('evidence_notes', sa.Text(), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('review_status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('provenance', sa.String(length=50), nullable=False, server_default='USER_PROVIDED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_claims_claim_type'), 'claims', ['claim_type'], unique=False)
    op.create_index(op.f('ix_claims_evidence_status'), 'claims', ['evidence_status'], unique=False)
    op.create_index(op.f('ix_claims_id'), 'claims', ['id'], unique=False)
    op.create_index(op.f('ix_claims_product_version_id'), 'claims', ['product_version_id'], unique=False)

    # Create evidence_documents table
    op.create_table(
        'evidence_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('evidence_type', postgresql.ENUM('SCIENTIFIC_PAPER', 'CLINICAL_TRIAL', 'TRADITIONAL_TEXT', 'PHARMACOPOEIA', 'REGULATORY_DOCUMENT', 'OTHER', name='evidencetype', create_type=False), nullable=True),
        sa.Column('file_path', sa.String(length=1000), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('doi', sa.String(length=100), nullable=True),
        sa.Column('publication_date', sa.Date(), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('authors', sa.Text(), nullable=True),
        sa.Column('verification_status', postgresql.ENUM('PENDING', 'VERIFIED', 'REJECTED', name='verificationstatus', create_type=False), nullable=False, server_default='PENDING'),
        sa.Column('document_hash', sa.String(length=64), nullable=True),
        sa.Column('provenance', sa.String(length=50), nullable=False, server_default='USER_PROVIDED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evidence_documents_evidence_type'), 'evidence_documents', ['evidence_type'], unique=False)
    op.create_index(op.f('ix_evidence_documents_id'), 'evidence_documents', ['id'], unique=False)
    op.create_index(op.f('ix_evidence_documents_product_version_id'), 'evidence_documents', ['product_version_id'], unique=False)

    # Create target_markets table
    op.create_table(
        'target_markets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('country', sa.String(length=100), nullable=False),
        sa.Column('region', sa.String(length=100), nullable=True),
        sa.Column('regulatory_status', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_target_markets_country'), 'target_markets', ['country'], unique=False)
    op.create_index(op.f('ix_target_markets_id'), 'target_markets', ['id'], unique=False)
    op.create_index(op.f('ix_target_markets_product_version_id'), 'target_markets', ['product_version_id'], unique=False)

    # Create analyses table
    op.create_table(
        'analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_version_id', sa.Integer(), nullable=False),
        sa.Column('analysis_type', postgresql.ENUM('PRODUCT_CLASSIFICATION', 'IP_ROUTE_MAP', 'PATENT_SCREENING', 'BIODIVERSITY_SCREENING', 'TK_SCREENING', 'PUBLIC_DISCLOSURE_REVIEW', 'COMPREHENSIVE', name='analysistype', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', name='analysisstatus', create_type=False), nullable=False, server_default='PENDING'),
        sa.Column('results', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('recommendations', sa.Text(), nullable=True),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('flags', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analyses_analysis_type'), 'analyses', ['analysis_type'], unique=False)
    op.create_index(op.f('ix_analyses_created_at'), 'analyses', ['created_at'], unique=False)
    op.create_index(op.f('ix_analyses_created_by'), 'analyses', ['created_by'], unique=False)
    op.create_index(op.f('ix_analyses_id'), 'analyses', ['id'], unique=False)
    op.create_index(op.f('ix_analyses_product_version_id'), 'analyses', ['product_version_id'], unique=False)
    op.create_index(op.f('ix_analyses_status'), 'analyses', ['status'], unique=False)


def downgrade() -> None:
    # Drop analyses table
    op.drop_index(op.f('ix_analyses_status'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_product_version_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_created_by'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_created_at'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_analysis_type'), table_name='analyses')
    op.drop_table('analyses')
    op.execute('DROP TYPE IF EXISTS analysisstatus')
    op.execute('DROP TYPE IF EXISTS analysistype')

    # Drop target_markets table
    op.drop_index(op.f('ix_target_markets_product_version_id'), table_name='target_markets')
    op.drop_index(op.f('ix_target_markets_id'), table_name='target_markets')
    op.drop_index(op.f('ix_target_markets_country'), table_name='target_markets')
    op.drop_table('target_markets')

    # Drop evidence_documents table
    op.drop_index(op.f('ix_evidence_documents_product_version_id'), table_name='evidence_documents')
    op.drop_index(op.f('ix_evidence_documents_id'), table_name='evidence_documents')
    op.drop_index(op.f('ix_evidence_documents_evidence_type'), table_name='evidence_documents')
    op.drop_table('evidence_documents')
    op.execute('DROP TYPE IF EXISTS verificationstatus')
    op.execute('DROP TYPE IF EXISTS evidencetype')

    # Drop claims table
    op.drop_index(op.f('ix_claims_product_version_id'), table_name='claims')
    op.drop_index(op.f('ix_claims_id'), table_name='claims')
    op.drop_index(op.f('ix_claims_evidence_status'), table_name='claims')
    op.drop_index(op.f('ix_claims_claim_type'), table_name='claims')
    op.drop_table('claims')
    op.execute('DROP TYPE IF EXISTS evidencestatus')
    op.execute('DROP TYPE IF EXISTS claimtype')

    # Drop formulations table
    op.drop_index(op.f('ix_formulations_product_version_id'), table_name='formulations')
    op.drop_index(op.f('ix_formulations_id'), table_name='formulations')
    op.drop_table('formulations')

    # Drop ingredients table
    op.drop_index(op.f('ix_ingredients_product_version_id'), table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_id'), table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_botanical_name'), table_name='ingredients')
    op.drop_table('ingredients')
    op.execute('DROP TYPE IF EXISTS sourcetype')

    # Drop foreign key from products to product_versions
    op.drop_constraint('fk_products_current_version_id', 'products', type_='foreignkey')

    # Drop product_versions table
    op.drop_index(op.f('ix_product_versions_product_id'), table_name='product_versions')
    op.drop_index(op.f('ix_product_versions_id'), table_name='product_versions')
    op.drop_index(op.f('ix_product_versions_created_by'), table_name='product_versions')
    op.drop_index(op.f('ix_product_versions_created_at'), table_name='product_versions')
    op.drop_table('product_versions')

    # Drop products table
    op.drop_index(op.f('ix_products_name'), table_name='products')
    op.drop_index(op.f('ix_products_id'), table_name='products')
    op.drop_index(op.f('ix_products_created_by'), table_name='products')
    op.drop_index(op.f('ix_products_category'), table_name='products')
    op.drop_table('products')
    op.execute('DROP TYPE IF EXISTS productcategory')
