"""create generated papers

Revision ID: 0009_create_generated_papers
Revises: 0008_add_chapter_page_ranges
Create Date: 2026-08-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0009_create_generated_papers'
down_revision = '0008_add_chapter_page_ranges'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'generated_papers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('book_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reference_paper_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('reference_papers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('generation_mode', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('total_marks', sa.Integer(), nullable=False),
        sa.Column('difficulty', sa.String(length=50), nullable=False, server_default='MIXED'),
        sa.Column('topic_focus', sa.Text(), nullable=True),
        sa.Column('selected_chapter_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('include_answers', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('blueprint_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index(op.f('ix_generated_papers_user_id'), 'generated_papers', ['user_id'], unique=False)
    op.create_index(op.f('ix_generated_papers_workspace_id'), 'generated_papers', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_generated_papers_subject_id'), 'generated_papers', ['subject_id'], unique=False)
    op.create_index(op.f('ix_generated_papers_book_id'), 'generated_papers', ['book_id'], unique=False)
    op.create_index(op.f('ix_generated_papers_reference_paper_id'), 'generated_papers', ['reference_paper_id'], unique=False)

    op.create_table(
        'generated_paper_questions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('paper_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('generated_papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chapter_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chapters.id', ondelete='SET NULL'), nullable=True),
        sa.Column('question_order', sa.Integer(), nullable=False),
        sa.Column('section_name', sa.String(length=100), nullable=False),
        sa.Column('question_type', sa.String(length=50), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('marks', sa.Integer(), nullable=False),
        sa.Column('difficulty', sa.String(length=50), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('mcq_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('correct_answer', sa.Text(), nullable=True),
        sa.Column('expected_answer', sa.Text(), nullable=True),
        sa.Column('numerical_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('solution_explanation', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index(op.f('ix_generated_paper_questions_paper_id'), 'generated_paper_questions', ['paper_id'], unique=False)
    op.create_index(op.f('ix_generated_paper_questions_chapter_id'), 'generated_paper_questions', ['chapter_id'], unique=False)


def downgrade() -> None:
    op.drop_table('generated_paper_questions')
    op.drop_table('generated_papers')
