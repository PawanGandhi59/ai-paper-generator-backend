"""add embedding status columns to documents

Revision ID: 0021_add_embedding_status
Revises: 0020_add_reasoning_style
Create Date: 2026-09-11 11:47:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic (<= 32 chars).
revision = '0021_add_embedding_status'
down_revision = '0020_add_reasoning_style'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('embedding_status', sa.String(length=50), nullable=False, server_default='NOT_STARTED')
    )
    op.add_column('documents', sa.Column('embedding_error', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('embedding_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_documents_embedding_status', 'documents', ['embedding_status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_documents_embedding_status', table_name='documents')
    op.drop_column('documents', 'embedding_completed_at')
    op.drop_column('documents', 'embedding_error')
    op.drop_column('documents', 'embedding_status')
