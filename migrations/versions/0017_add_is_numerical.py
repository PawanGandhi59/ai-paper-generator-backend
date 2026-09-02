"""add is_numerical to generated_paper_questions and percentage fields to generated_papers

Revision ID: 0017_add_is_numerical_and_percentages
Revises: 0016_create_password_reset_otps
Create Date: 2026-09-01 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0017_add_is_numerical'
down_revision = '0016_create_password_reset_otps'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_paper_questions', sa.Column('is_numerical', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('generated_papers', sa.Column('easy_percentage', sa.Integer(), nullable=True))
    op.add_column('generated_papers', sa.Column('medium_percentage', sa.Integer(), nullable=True))
    op.add_column('generated_papers', sa.Column('hard_percentage', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_papers', 'hard_percentage')
    op.drop_column('generated_papers', 'medium_percentage')
    op.drop_column('generated_papers', 'easy_percentage')
    op.drop_column('generated_paper_questions', 'is_numerical')
