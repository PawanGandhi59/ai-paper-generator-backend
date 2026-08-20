"""Add start_page and end_page columns to chapters table

Revision ID: 0008_add_chapter_page_ranges
Revises: 0007_create_reference_papers
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_add_chapter_page_ranges'
down_revision: Union[str, None] = '0007_create_reference_papers'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chapters', sa.Column('start_page', sa.Integer(), nullable=True))
    op.add_column('chapters', sa.Column('end_page', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('chapters', 'end_page')
    op.drop_column('chapters', 'start_page')
