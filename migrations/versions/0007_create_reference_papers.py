"""Create reference_papers and reference_paper_pages tables

Revision ID: 0007_create_reference_papers
Revises: 0006_create_generated_visuals
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007_create_reference_papers'
down_revision: Union[str, None] = '0006_create_generated_visuals'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create reference_papers table
    op.create_table(
        'reference_papers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('exam_type', sa.String(length=100), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_path', sa.String(length=1024), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reference_papers_subject_id'), 'reference_papers', ['subject_id'], unique=False)
    op.create_index(op.f('ix_reference_papers_workspace_id'), 'reference_papers', ['workspace_id'], unique=False)

    # 2. Create reference_paper_pages table
    op.create_table(
        'reference_paper_pages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reference_paper_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False, server_default='PAGE'),
        sa.Column('text_content', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['reference_paper_id'], ['reference_papers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference_paper_id', 'page_number', name='uq_reference_paper_pages_paper_id_page_number'),
    )
    op.create_index(op.f('ix_reference_paper_pages_reference_paper_id'), 'reference_paper_pages', ['reference_paper_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reference_paper_pages_reference_paper_id'), table_name='reference_paper_pages')
    op.drop_table('reference_paper_pages')

    op.drop_index(op.f('ix_reference_papers_workspace_id'), table_name='reference_papers')
    op.drop_index(op.f('ix_reference_papers_subject_id'), table_name='reference_papers')
    op.drop_table('reference_papers')
