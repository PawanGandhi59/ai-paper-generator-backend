"""add answer_key_json to generated_papers

Revision ID: 0028_add_answer_key_json
Revises: 0027_drop_terms_version
Create Date: 2026-10-14 17:55:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic (<= 32 chars).
revision = '0028_add_answer_key_json'
down_revision = '0027_drop_terms_version'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('generated_papers')]
    if 'answer_key_json' not in columns:
        op.add_column(
            'generated_papers',
            sa.Column('answer_key_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('generated_papers', 'answer_key_json')
