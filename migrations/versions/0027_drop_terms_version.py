"""drop terms_version from users

Revision ID: 0027_drop_terms_version
Revises: 0026_add_article_18_restriction
Create Date: 2026-10-08 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0027_drop_terms_version'
down_revision = '0026_add_article_18_restriction'
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.drop_column('users', 'terms_version')
    except Exception:
        pass


def downgrade() -> None:
    op.add_column('users', sa.Column('terms_version', sa.String(length=50), nullable=True))
