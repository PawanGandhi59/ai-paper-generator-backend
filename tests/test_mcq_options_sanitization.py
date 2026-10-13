import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from app.schemas.paper import QuestionType, GenerationMode
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.services.paper.blueprint_service import SectionBlueprint
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.services.ai.prompts.paper_prompt import (
    PAPER_GENERATION_SYSTEM_INSTRUCTION,
    PAPER_RECOVERY_SYSTEM_INSTRUCTION,
)


def test_strip_mcq_option_prefix():
    """Verify PaperGeneratorService._strip_mcq_option_prefix strips letter prefixes correctly."""
    assert PaperGeneratorService._strip_mcq_option_prefix("A. Electric potential") == "Electric potential"
    assert PaperGeneratorService._strip_mcq_option_prefix("B. Electric field") == "Electric field"
    assert PaperGeneratorService._strip_mcq_option_prefix("(C) Electric flux") == "Electric flux"
    assert PaperGeneratorService._strip_mcq_option_prefix("d) Charge density") == "Charge density"
    assert PaperGeneratorService._strip_mcq_option_prefix("Option A: Velocity") == "Velocity"
    assert PaperGeneratorService._strip_mcq_option_prefix("option b: Velocity") == "Velocity"
    assert PaperGeneratorService._strip_mcq_option_prefix("A - Acceleration") == "Acceleration"
    assert PaperGeneratorService._strip_mcq_option_prefix("A. 1.0 × 10^7 N/C") == "1.0 × 10^7 N/C"
    # Already clean option strings remain untouched
    assert PaperGeneratorService._strip_mcq_option_prefix("Electric potential") == "Electric potential"
    assert PaperGeneratorService._strip_mcq_option_prefix("1.0 × 10^7 N/C") == "1.0 × 10^7 N/C"


def test_validate_question_structure_strips_mcq_options():
    """Verify _validate_question_structure strips option letter prefixes from candidate questions."""
    svc = PaperGeneratorService.__new__(PaperGeneratorService)
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=1,
        marks_per_question=1,
        total_section_marks=1,
    )

    q = {
        "question_text": "Which of the following physical quantities has the SI unit of volt-meter?",
        "question_type": "MCQ",
        "marks": 1,
        "mcq_options": [
            "A. Electric potential",
            "B. Electric field",
            "C. Electric flux",
            "D. Charge density",
        ],
        "is_numerical": False,
        "difficulty": "EASY",
    }

    valid = svc._validate_question_structure(q, sec)
    assert valid is True
    assert q["mcq_options"] == [
        "Electric potential",
        "Electric field",
        "Electric flux",
        "Charge density",
    ]


def test_build_paper_response_sanitizes_mcq_options():
    """Verify _build_paper_response sanitizes mcq_options before returning response."""
    svc = PaperGeneratorService.__new__(PaperGeneratorService)

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = uuid4()
    paper.workspace_id = uuid4()
    paper.subject_id = uuid4()
    paper.book_id = uuid4()
    paper.reference_paper_id = None
    paper.title = "Test Paper"
    paper.generation_mode = GenerationMode.CUSTOM
    paper.status = "COMPLETED"
    paper.total_marks = 1
    paper.time_allowed_minutes = 60
    paper.class_name = "Class 12"
    paper.easy_percentage = 100
    paper.medium_percentage = 0
    paper.hard_percentage = 0
    paper.selected_chapter_ids = []
    paper.blueprint_json = None
    paper.error_message = None
    paper.pdf_path = None
    paper.processing_status = "NOT_SAVED"
    paper.reference_eligible = False
    paper.created_at = None
    paper.updated_at = None

    q = MagicMock(spec=GeneratedPaperQuestion)
    q.id = uuid4()
    q.paper_id = paper.id
    q.chapter_id = None
    q.question_order = 1
    q.section_name = "Section A"
    q.question_type = "MCQ"
    q.question_text = "Which of the following is a vector quantity?"
    q.marks = 1
    q.difficulty = "EASY"
    q.source_type = "AI_GENERATED"
    q.is_numerical = False
    q.choice_group = None
    q.alternative_label = None
    q.reasoning_style = None
    q.section_description = None
    q.mcq_options = [
        "A. Electric potential",
        "B. Electric field",
        "C. Electric flux",
        "D. Charge density",
    ]
    q.visual_required = False
    q.visual_type = None
    q.visual_title = None
    q.visual_caption = None
    q.visual_spec = None
    q.visual_svg = None

    paper.questions = [q]

    resp = svc._build_paper_response(paper)
    assert len(resp.questions) == 1
    assert resp.questions[0].mcq_options == [
        "Electric potential",
        "Electric field",
        "Electric flux",
        "Charge density",
    ]


def test_system_prompt_instructions_prohibit_letter_prefixes():
    """Verify prompt instructions specify raw option text without letter prefixes."""
    assert "without letter prefixes" in PAPER_GENERATION_SYSTEM_INSTRUCTION.lower()
    assert "without letter prefixes" in PAPER_RECOVERY_SYSTEM_INSTRUCTION.lower()
