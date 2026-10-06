"""add Article 18 restriction and clean up consent columns for UK GDPR compliance

Revision ID: 0026_add_article_18_restriction
Revises: 0025_add_user_consent_metadata
Create Date: 2026-10-06 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0026_add_article_18_restriction'
down_revision = '0025_add_user_consent_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Article 18 processing restriction column
    op.add_column('users', sa.Column('is_restricted', sa.Boolean(), server_default='false', nullable=False))

    # Clean up unneeded columns from migration 0025 since application has no marketing/telemetry
    try:
        op.drop_column('users', 'marketing_opt_in')
    except Exception:
        pass
    try:
        op.drop_column('users', 'privacy_notice_acknowledged_at')
    except Exception:
        pass


def downgrade() -> None:
    op.drop_column('users', 'is_restricted')
    op.add_column('users', sa.Column('marketing_opt_in', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('privacy_notice_acknowledged_at', sa.DateTime(timezone=True), nullable=True))
