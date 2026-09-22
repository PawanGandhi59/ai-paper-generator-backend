"""add reasoning_style and section_description

Revision ID: 0020_add_reasoning_style
Revises: 0019_add_exam_digest_to_chapters
Create Date: 2026-09-11 11:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic (must be <= 32 chars).
revision = '0020_add_reasoning_style'
down_revision = '0019_add_exam_digest_to_chapters'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_paper_questions', sa.Column('reasoning_style', sa.String(length=100), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('section_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_paper_questions', 'section_description')
    op.drop_column('generated_paper_questions', 'reasoning_style')
