"""add pdf_path document_id processing_status and deleted_at to generated_papers

Revision ID: 0012_paper_pdf_and_soft_delete
Revises: 0011_create_paper_versions
Create Date: 2026-08-25 18:55:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0012_paper_pdf_and_soft_delete'
down_revision = '0011_create_paper_versions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_papers', sa.Column('pdf_path', sa.String(length=1024), nullable=True))
    op.add_column('generated_papers', sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('generated_papers', sa.Column('processing_status', sa.String(length=50), nullable=True, server_default='NOT_SAVED'))
    op.add_column('generated_papers', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        'fk_generated_papers_document_id',
        'generated_papers',
        'documents',
        ['document_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index(op.f('ix_generated_papers_document_id'), 'generated_papers', ['document_id'], unique=False)
    op.create_index(op.f('ix_generated_papers_deleted_at'), 'generated_papers', ['deleted_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_papers_deleted_at'), table_name='generated_papers')
    op.drop_index(op.f('ix_generated_papers_document_id'), table_name='generated_papers')
    op.drop_constraint('fk_generated_papers_document_id', 'generated_papers', type_='foreignkey')
    op.drop_column('generated_papers', 'deleted_at')
    op.drop_column('generated_papers', 'processing_status')
    op.drop_column('generated_papers', 'document_id')
    op.drop_column('generated_papers', 'pdf_path')
