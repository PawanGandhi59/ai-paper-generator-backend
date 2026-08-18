"""Create generated_visuals table

Revision ID: 0006_create_generated_visuals
Revises: 0005_document_chunks_pgvector
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006_create_generated_visuals'
down_revision: Union[str, None] = '0005_document_chunks_pgvector'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_visuals',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=False),
        sa.Column('mime_type', sa.String(length=64), nullable=False, server_default='image/png'),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generated_visuals_user_id'), 'generated_visuals', ['user_id'], unique=False)
    op.create_index(op.f('ix_generated_visuals_workspace_id'), 'generated_visuals', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_visuals_workspace_id'), table_name='generated_visuals')
    op.drop_index(op.f('ix_generated_visuals_user_id'), table_name='generated_visuals')
    op.drop_table('generated_visuals')
