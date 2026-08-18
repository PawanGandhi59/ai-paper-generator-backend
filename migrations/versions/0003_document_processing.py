"""Add document processing and document pages tables

Revision ID: 0003_document_processing
Revises: 0002_auth_and_hierarchy
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003_document_processing'
down_revision: Union[str, None] = '0002_auth_and_hierarchy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop previous document stub table if exists
    op.execute("DROP TABLE IF EXISTS documents CASCADE;")

    # 1. Re-create updated documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chapter_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chapters.id', ondelete='SET NULL'), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_path', sa.String(length=1024), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('processing_status', sa.String(length=50), server_default='UPLOADED', nullable=False),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_documents_book_id', 'documents', ['book_id'], unique=False)
    op.create_index('ix_documents_chapter_id', 'documents', ['chapter_id'], unique=False)
    op.create_index('ix_documents_processing_status', 'documents', ['processing_status'], unique=False)

    # 2. Create document_pages table
    op.create_table(
        'document_pages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=50), server_default='PAGE', nullable=False),
        sa.Column('text_content', sa.Text(), server_default='', nullable=False),
        sa.Column('image_path', sa.String(length=1024), nullable=True),
        sa.Column('metadata_json', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_document_pages_document_id', 'document_pages', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_table('document_pages')
    op.drop_table('documents')
