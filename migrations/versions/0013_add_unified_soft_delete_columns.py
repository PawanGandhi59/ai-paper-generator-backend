"""add unified soft_delete deleted_at columns

Revision ID: 0013_soft_delete
Revises: 0012_paper_pdf_and_soft_delete
Create Date: 2026-08-26 11:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013_soft_delete'
down_revision = '0012_paper_pdf_and_soft_delete'
branch_labels = None
depends_on = None


TABLES = [
    'subjects',
    'books',
    'chapters',
    'topics',
    'documents',
    'document_pages',
    'document_chunks',
    'reference_papers',
    'reference_paper_pages',
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        op.create_index(op.f(f'ix_{table}_deleted_at'), table, ['deleted_at'], unique=False)


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(op.f(f'ix_{table}_deleted_at'), table_name=table)
        op.drop_column(table, 'deleted_at')
