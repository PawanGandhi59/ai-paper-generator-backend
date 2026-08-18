"""Create document_chunks table with pgvector column and indexes

Revision ID: 0005_document_chunks_pgvector
Revises: 0004_document_pages_unique
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005_document_chunks_pgvector'
down_revision: Union[str, None] = '0004_document_pages_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure pgvector extension is active
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        'document_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('document_page_id', sa.UUID(), nullable=True),
        sa.Column('chapter_id', sa.UUID(), nullable=True),
        sa.Column('book_id', sa.UUID(), nullable=False),
        sa.Column('subject_id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False, server_default='TEXT'),
        sa.Column('metadata_json', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_page_id'], ['document_pages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'chunk_index', name='uq_document_chunks_document_id_chunk_index')
    )

    # Standard B-tree indexes for fast filtered retrieval
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_document_page_id'), 'document_chunks', ['document_page_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_chapter_id'), 'document_chunks', ['chapter_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_book_id'), 'document_chunks', ['book_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_subject_id'), 'document_chunks', ['subject_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_workspace_id'), 'document_chunks', ['workspace_id'], unique=False)

    # HNSW Vector Cosine Similarity Index
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")
    op.drop_index(op.f('ix_document_chunks_workspace_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_subject_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_book_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_chapter_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_document_page_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_table('document_chunks')
