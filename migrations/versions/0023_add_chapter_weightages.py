"""add chapter_weightages to generated_papers

Revision ID: 0023_add_chapter_weightages
Revises: 0022_drop_topic_focus
Create Date: 2026-09-23 11:43:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic (<= 32 chars).
revision = '0023_add_chapter_weightages'
down_revision = '0022_drop_topic_focus'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('generated_papers')]
    if 'chapter_weightages' not in columns:
        op.add_column(
            'generated_papers',
            sa.Column('chapter_weightages', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('generated_papers', 'chapter_weightages')
