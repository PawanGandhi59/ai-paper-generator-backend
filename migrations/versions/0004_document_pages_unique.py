"""Add unique constraint to document_pages (document_id, page_number)

Revision ID: 0004_document_pages_unique
Revises: 0003_document_processing
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0004_document_pages_unique'
down_revision: Union[str, None] = '0003_document_processing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate any pre-existing duplicate page records before applying constraint
    op.execute(
        """
        DELETE FROM document_pages a USING (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY document_id, page_number ORDER BY created_at ASC) as rnum
            FROM document_pages
        ) b
        WHERE a.id = b.id AND b.rnum > 1;
        """
    )

    op.create_unique_constraint(
        'uq_document_pages_document_id_page_number',
        'document_pages',
        ['document_id', 'page_number']
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_document_pages_document_id_page_number',
        'document_pages',
        type_='unique'
    )
