"""drop topic_focus from generated_papers

Revision ID: 0022_drop_topic_focus
Revises: 0021_add_embedding_status
Create Date: 2026-09-22 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic (<= 32 chars).
revision = '0022_drop_topic_focus'
down_revision = '0021_add_embedding_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop topic_focus column from generated_papers if it exists
    op.drop_column('generated_papers', 'topic_focus')


def downgrade() -> None:
    # Re-add topic_focus as nullable Text
    op.add_column('generated_papers', sa.Column('topic_focus', sa.Text(), nullable=True))
