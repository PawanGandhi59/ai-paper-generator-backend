"""add exam_digest to chapters

Revision ID: 0019_add_exam_digest_to_chapters
Revises: 0018_add_question_visual_columns
Create Date: 2026-09-08 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0019_add_exam_digest_to_chapters'
down_revision = '0018_add_question_visual_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chapters', sa.Column('exam_digest', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('chapters', 'exam_digest')
