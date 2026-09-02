import re
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
    VERY_SHORT_ANSWER = "VERY_SHORT_ANSWER"
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
    alternatives_per_question: int = Field(1, ge=1, description="Number of alternatives per question number (e.g. 1 for mandatory, 2 for (a) OR (b))")

    @property
    def has_internal_choice(self) -> bool:
        return self.alternatives_per_question > 1



class PaperGenerateRequest(BaseModel):
    book_id: UUID
    selected_chapter_ids: List[UUID] = Field(..., min_length=1, description="Selected chapter IDs (HARD content boundary)")
    generation_mode: GenerationMode
    total_marks: int = Field(..., ge=1, le=1000, description="Total paper marks")
    time_allowed_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Time allowed for paper in minutes (e.g. 180 for 3 hours)")
    class_name: Optional[str] = Field(None, max_length=100, description="Optional class/grade name (e.g. Class 10, Grade 12)")

    difficulty: DifficultyLevel = DifficultyLevel.MIXED
    easy_percentage: Optional[int] = Field(None, ge=0, le=100, description="Optional percentage of Easy questions (0-100%)")
    medium_percentage: Optional[int] = Field(None, ge=0, le=100, description="Optional percentage of Medium questions (0-100%)")
    hard_percentage: Optional[int] = Field(None, ge=0, le=100, description="Optional percentage of Hard questions (0-100%)")


    topic_focus: Optional[str] = Field(None, max_length=1000, description="Optional natural language topic focus/preference")
    include_answers: bool = Field(True, description="Whether to include answer keys in API response")
    title: Optional[str] = Field(None, max_length=255)

    enable_numerical_percentage: bool = Field(False, description="Whether to distribute a percentage of numerical questions across sections")
    numerical_percentage: Optional[int] = Field(None, ge=1, le=100, description="Percentage of numerical questions in each section (1-100%)")

    # Custom mode configuration
    question_configs: Optional[List[QuestionConfigItem]] = None

    # Reference mode configuration
    reference_paper_id: Optional[UUID] = Field(
        None,
        description="UUID of an uploaded reference paper OR an existing AI-generated paper to use as a structural template.",
    )


    @field_validator("time_allowed_minutes")
    @classmethod
    def validate_time_allowed_minutes(cls, v: Optional[int]) -> Optional[int]:
        if v is not None:
            if v <= 0:
                raise ValueError("time_allowed_minutes must be a positive integer greater than 0")
            if v > 1440:
                raise ValueError("time_allowed_minutes cannot exceed 1440 minutes (24 hours)")
        return v

    @field_validator("class_name")
    @classmethod
    def validate_class_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("class_name cannot be blank or an empty string")
            if not re.search(r"[a-zA-Z0-9\u00C0-\u024F\u1E00-\u1EFF]", v):
                raise ValueError("class_name must contain letters or numbers and cannot consist only of special characters")
            if not re.match(r"^[a-zA-Z0-9\u00C0-\u024F\u1E00-\u1EFF\s\-\.\,\(\)\/\\\_]+$", v):
                raise ValueError("class_name contains invalid special characters")
            return v
        return None

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
        pct_fields = [self.easy_percentage, self.medium_percentage, self.hard_percentage]
        provided_pcts = [p for p in pct_fields if p is not None]

        if len(provided_pcts) > 0:
            if len(provided_pcts) < 3:
                raise ValueError("All three percentages (easy_percentage, medium_percentage, hard_percentage) must be provided together.")
            total_pct = self.easy_percentage + self.medium_percentage + self.hard_percentage
            if total_pct != 100:
                raise ValueError(
                    f"Invalid custom difficulty distribution: sum of easy_percentage ({self.easy_percentage}%), "
                    f"medium_percentage ({self.medium_percentage}%), and hard_percentage ({self.hard_percentage}%) "
                    f"must equal exactly 100% (got {total_pct}%)."
                )

        if self.enable_numerical_percentage:
            if self.numerical_percentage is None or self.numerical_percentage < 1 or self.numerical_percentage > 100:
                raise ValueError("numerical_percentage between 1 and 100 must be provided when enable_numerical_percentage is True.")
        else:
            self.numerical_percentage = None

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
    is_numerical: bool = False

    choice_group: Optional[str] = None
    alternative_label: Optional[str] = None

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
    time_allowed_minutes: Optional[int] = None
    class_name: Optional[str] = None
    difficulty: DifficultyLevel
    easy_percentage: Optional[int] = None
    medium_percentage: Optional[int] = None
    hard_percentage: Optional[int] = None


    topic_focus: Optional[str] = None
    selected_chapter_ids: List[UUID]
    include_answers: bool
    blueprint_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    has_saved_pdf: bool = False
    pdf_url: Optional[str] = None
    processing_status: Optional[str] = "NOT_SAVED"
    reference_eligible: bool = False

    questions: List[PaperQuestionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GeminiGeneratedQuestionSchema(BaseModel):
    question_text: str = Field(..., description="Full text of the question item")
    mcq_options: Optional[List[str]] = Field(None, description="Exactly 4 option strings for MCQs ('A. ...', 'B. ...', 'C. ...', 'D. ...')")
    correct_answer: str = Field(..., description="Unambiguously correct option or short answer")
    expected_answer: Optional[str] = Field(None, description="Detailed expected answer or model solution")
    solution_explanation: str = Field(..., description="Step-by-step solution, derivation, or explanation")
    is_numerical: bool = Field(False, description="Whether question involves quantitative calculation")
    chapter_number: Optional[int] = Field(None, description="1-based integer chapter number for chapter attribution")
    difficulty: Optional[str] = Field(None, description="'EASY', 'MEDIUM', or 'HARD'")
    source_type: Optional[str] = Field(None, description="'AI_GENERATED', 'REFERENCE_REUSED', or 'REFERENCE_VARIATION'")


class GeminiSectionQuestionsSchema(BaseModel):
    section_name: str = Field(..., description="Name of the blueprint section")
    questions: List[GeminiGeneratedQuestionSchema] = Field(default_factory=list)


class GeminiCompletePaperSchema(BaseModel):
    sections: List[GeminiSectionQuestionsSchema] = Field(default_factory=list)

