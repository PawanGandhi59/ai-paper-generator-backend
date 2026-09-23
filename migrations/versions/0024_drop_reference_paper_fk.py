"""drop foreign key constraint on generated_papers.reference_paper_id

Revision ID: 0024_drop_reference_paper_fk
Revises: 0023_add_chapter_weightages
Create Date: 2026-09-23 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0024_drop_reference_paper_fk'
down_revision = '0023_add_chapter_weightages'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the foreign key constraint so reference_paper_id can point to either an uploaded reference paper or an AI-generated paper
    op.execute(
        "ALTER TABLE generated_papers DROP CONSTRAINT IF EXISTS generated_papers_reference_paper_id_fkey;"
    )


def downgrade() -> None:
    op.create_foreign_key(
        'generated_papers_reference_paper_id_fkey',
        'generated_papers',
        'reference_papers',
        ['reference_paper_id'],
        ['id'],
        ondelete='SET NULL'
    )
