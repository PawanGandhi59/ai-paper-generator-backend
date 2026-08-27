"""create password_reset_otps table

Revision ID: 0016_create_password_reset_otps
Revises: 0015_add_paper_class_name
Create Date: 2026-08-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0016_create_password_reset_otps'
down_revision = '0015_add_paper_class_name'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'password_reset_otps',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('otp_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_password_reset_otps_user_id'), 'password_reset_otps', ['user_id'], unique=False)
    op.create_index(op.f('ix_password_reset_otps_expires_at'), 'password_reset_otps', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_password_reset_otps_expires_at'), table_name='password_reset_otps')
    op.drop_index(op.f('ix_password_reset_otps_user_id'), table_name='password_reset_otps')
    op.drop_table('password_reset_otps')
