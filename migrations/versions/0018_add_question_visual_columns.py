"""add visual columns to generated_paper_questions

Revision ID: 0018_add_question_visual_columns
Revises: 0017_add_is_numerical
Create Date: 2026-09-02 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '0018_add_question_visual_columns'
down_revision = '0017_add_is_numerical'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_paper_questions', sa.Column('visual_required', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('generated_paper_questions', sa.Column('visual_type', sa.String(length=50), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('visual_title', sa.String(length=255), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('visual_caption', sa.Text(), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('visual_spec', JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('visual_svg', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_paper_questions', 'visual_svg')
    op.drop_column('generated_paper_questions', 'visual_spec')
    op.drop_column('generated_paper_questions', 'visual_caption')
    op.drop_column('generated_paper_questions', 'visual_title')
    op.drop_column('generated_paper_questions', 'visual_type')
    op.drop_column('generated_paper_questions', 'visual_required')
