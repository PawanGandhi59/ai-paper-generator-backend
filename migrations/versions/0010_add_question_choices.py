"""add question choices columns

Revision ID: 0010_add_question_choices
Revises: 0009_create_generated_papers
Create Date: 2026-08-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010_add_question_choices'
down_revision = '0009_create_generated_papers'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_paper_questions', sa.Column('choice_group', sa.String(length=50), nullable=True))
    op.add_column('generated_paper_questions', sa.Column('alternative_label', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_paper_questions', 'alternative_label')
    op.drop_column('generated_paper_questions', 'choice_group')
