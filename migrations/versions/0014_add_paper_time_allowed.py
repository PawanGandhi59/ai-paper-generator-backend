"""add time_allowed_minutes to generated_papers

Revision ID: 0014_add_paper_time_allowed
Revises: 0013_soft_delete
Create Date: 2026-08-26 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014_add_paper_time_allowed'
down_revision = '0013_soft_delete'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_papers', sa.Column('time_allowed_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_papers', 'time_allowed_minutes')
