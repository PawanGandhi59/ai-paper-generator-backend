from datetime import datetime, timezone
import uuid
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class GeneratedPaper(Base):
    __tablename__ = "generated_papers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_paper_id = Column(UUID(as_uuid=True), ForeignKey("reference_papers.id", ondelete="SET NULL"), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    generation_mode = Column(String(50), nullable=False)  # "CUSTOM", "REFERENCE"
    status = Column(String(50), nullable=False, default="PENDING")  # "PENDING", "GENERATING", "COMPLETED", "FAILED"
    total_marks = Column(Integer, nullable=False)
    time_allowed_minutes = Column(Integer, nullable=True)
    class_name = Column(String(100), nullable=True)
    difficulty = Column(String(50), nullable=False, default="MIXED")  # "EASY", "MEDIUM", "HARD", "MIXED"


    topic_focus = Column(Text, nullable=True)
    selected_chapter_ids = Column(JSONB, nullable=False)  # List[str] of chapter UUIDs
    include_answers = Column(Boolean, nullable=False, default=True)
    blueprint_json = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    pdf_path = Column(String(1024), nullable=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    processing_status = Column(String(50), nullable=True, default="NOT_SAVED")  # "NOT_SAVED", "PROCESSING", "READY", "FAILED"
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)



    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


    questions = relationship(
        "GeneratedPaperQuestion",
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="GeneratedPaperQuestion.question_order",
    )


class GeneratedPaperQuestion(Base):
    __tablename__ = "generated_paper_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id = Column(UUID(as_uuid=True), ForeignKey("generated_papers.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)

    question_order = Column(Integer, nullable=False)
    section_name = Column(String(100), nullable=False)
    question_type = Column(String(50), nullable=False)  # "MCQ", "SHORT_ANSWER", "LONG_ANSWER", "NUMERICAL"
    question_text = Column(Text, nullable=False)
    marks = Column(Integer, nullable=False)
    difficulty = Column(String(50), nullable=False)
    source_type = Column(String(50), nullable=False)  # "AI_GENERATED", "REFERENCE_REUSED", "REFERENCE_VARIATION"

    choice_group = Column(String(50), nullable=True)  # e.g., "Q4" or "4"
    alternative_label = Column(String(10), nullable=True)  # e.g., "a", "b"

    mcq_options = Column(JSONB, nullable=True)  # List of option strings
    correct_answer = Column(Text, nullable=True)
    expected_answer = Column(Text, nullable=True)
    numerical_values = Column(JSONB, nullable=True)
    solution_explanation = Column(Text, nullable=True)
    unit = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    paper = relationship("GeneratedPaper", back_populates="questions")
