from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GenerationMode(str, Enum):
    CUSTOM = "CUSTOM"
    REFERENCE = "REFERENCE"


class DifficultyLevel(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    MIXED = "MIXED"


class QuestionType(str, Enum):
    MCQ = "MCQ"
    SHORT_ANSWER = "SHORT_ANSWER"
    LONG_ANSWER = "LONG_ANSWER"
    NUMERICAL = "NUMERICAL"


class QuestionSource(str, Enum):
    AI_GENERATED = "AI_GENERATED"
    REFERENCE_REUSED = "REFERENCE_REUSED"
    REFERENCE_VARIATION = "REFERENCE_VARIATION"


class QuestionConfigItem(BaseModel):
    question_type: QuestionType
    question_count: int = Field(..., ge=1, description="Number of questions for this type")
    marks_per_question: int = Field(..., ge=1, description="Marks assigned to each question")
    section_name: Optional[str] = Field(None, max_length=100)


class PaperGenerateRequest(BaseModel):
    book_id: UUID
    selected_chapter_ids: List[UUID] = Field(..., min_length=1, description="Selected chapter IDs (HARD content boundary)")
    generation_mode: GenerationMode
    total_marks: int = Field(..., ge=1, le=1000, description="Total paper marks")
    difficulty: DifficultyLevel = DifficultyLevel.MIXED
    topic_focus: Optional[str] = Field(None, max_length=1000, description="Optional natural language topic focus/preference")
    include_answers: bool = Field(True, description="Whether to include answer keys in API response")
    title: Optional[str] = Field(None, max_length=255)

    # Custom mode configuration
    question_configs: Optional[List[QuestionConfigItem]] = None

    # Reference mode configuration
    reference_paper_id: Optional[UUID] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
        return v

    @field_validator("topic_focus")
    @classmethod
    def validate_topic_focus(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
        return v

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> "PaperGenerateRequest":
        if self.generation_mode == GenerationMode.CUSTOM:
            if not self.question_configs or len(self.question_configs) == 0:
                raise ValueError("question_configs is required for CUSTOM generation mode.")
            if self.reference_paper_id is not None:
                raise ValueError("reference_paper_id must not be provided for CUSTOM generation mode.")

            # Enforce sum(count * marks) == total_marks
            computed_total = sum(c.question_count * c.marks_per_question for c in self.question_configs)
            if computed_total != self.total_marks:
                raise ValueError(
                    f"Invalid question configuration: sum of configured marks ({computed_total}) "
                    f"does not equal paper total marks ({self.total_marks})."
                )
        elif self.generation_mode == GenerationMode.REFERENCE:
            if not self.reference_paper_id:
                raise ValueError("reference_paper_id is required for REFERENCE generation mode.")
            if self.question_configs and len(self.question_configs) > 0:
                raise ValueError("question_configs must not be provided for REFERENCE generation mode.")

        return self


class PaperQuestionResponse(BaseModel):
    id: UUID
    question_order: int
    section_name: str
    question_type: QuestionType
    question_text: str
    marks: int
    difficulty: str
    source_type: QuestionSource

    # Answer fields (conditionally included based on include_answers)
    mcq_options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    expected_answer: Optional[str] = None
    numerical_values: Optional[Dict[str, Any]] = None
    solution_explanation: Optional[str] = None
    unit: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PaperResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    subject_id: UUID
    book_id: UUID
    reference_paper_id: Optional[UUID] = None
    title: str
    generation_mode: GenerationMode
    status: str
    total_marks: int
    difficulty: DifficultyLevel
    topic_focus: Optional[str] = None
    selected_chapter_ids: List[UUID]
    include_answers: bool
    blueprint_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    questions: List[PaperQuestionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
