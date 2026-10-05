"""add user consent and terms metadata columns for UK GDPR compliance

Revision ID: 0025_add_user_consent_metadata
Revises: 0024_drop_reference_paper_fk
Create Date: 2026-10-05 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0025_add_user_consent_metadata'
down_revision = '0024_drop_reference_paper_fk'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('terms_version', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('privacy_notice_acknowledged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('marketing_opt_in', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'marketing_opt_in')
    op.drop_column('users', 'privacy_notice_acknowledged_at')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'terms_version')
