"""add blueprint_json to reference_papers

Revision ID: 0011_add_blueprint_json_to_ref_papers
Revises: 0010_add_question_choices
Create Date: 2026-08-25 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0011_create_paper_versions'
down_revision = '0010_add_question_choices'
branch_labels = None
depends_on = None



def upgrade() -> None:
    op.add_column('reference_papers', sa.Column('blueprint_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('reference_papers', 'blueprint_json')
