"""add class_name to generated_papers

Revision ID: 0015_add_paper_class_name
Revises: 0014_add_paper_time_allowed
Create Date: 2026-08-26 13:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0015_add_paper_class_name'
down_revision = '0014_add_paper_time_allowed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_papers', sa.Column('class_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_papers', 'class_name')
