import uuid
from unittest.mock import MagicMock

import pytest

from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.schemas.paper import QuestionType, PaperQuestionResponse, GenerationMode, DifficultyLevel
from app.services.paper.blueprint_service import (
    CANONICAL_REASONING_STYLES,
    BlueprintService,
    PaperBlueprint,
    SectionBlueprint,
    normalize_reasoning_style,
)
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_normalize_reasoning_style():
    # Direct canonical and synonym hits
    assert normalize_reasoning_style("SCENARIO_BASED") == "SCENARIO_BASED"
    assert normalize_reasoning_style("scenario_based") == "SCENARIO_BASED"
    assert normalize_reasoning_style("SCENARIO") == "SCENARIO_BASED"
    assert normalize_reasoning_style("CASE SCENARIO") == "SCENARIO_BASED"

    # Open-ended flexible domain styles chosen by Gemini are preserved and standardized
    assert normalize_reasoning_style("DIRECT_RECALL") == "DIRECT_RECALL"
    assert normalize_reasoning_style("CONCEPT_EXPLANATION") == "CONCEPT_EXPLANATION"
    assert normalize_reasoning_style("MULTI_STEP_NUMERICAL") == "MULTI_STEP_NUMERICAL"
    assert normalize_reasoning_style("DERIVATION") == "DERIVATION"
    assert normalize_reasoning_style("EXPERIMENTAL_ANALYSIS") == "EXPERIMENTAL_ANALYSIS"
    assert normalize_reasoning_style("ASSERTION_REASON") == "ASSERTION_REASON"
    assert normalize_reasoning_style("COMPARATIVE_ANALYSIS") == "COMPARATIVE_ANALYSIS"
    assert normalize_reasoning_style("Clinical Case Vignette") == "CLINICAL_CASE_VIGNETTE"
    assert normalize_reasoning_style("applied situation") == "APPLIED_SITUATION"
    assert normalize_reasoning_style("assertion-reason") == "ASSERTION_REASON"
    assert normalize_reasoning_style("mathematical derivation") == "MATHEMATICAL_DERIVATION"
    assert normalize_reasoning_style("proof and deduction") == "PROOF_AND_DEDUCTION"
    assert normalize_reasoning_style("calculation problem") == "CALCULATION_PROBLEM"
    assert normalize_reasoning_style("MIXED") == "MIXED"

    # None and empty
    assert normalize_reasoning_style(None) is None
    assert normalize_reasoning_style("") is None
    assert normalize_reasoning_style("   ") is None


def test_section_blueprint_reasoning_style_validator():
    sec = SectionBlueprint(
        name="Section C",
        question_type=QuestionType.LONG_ANSWER,
        reasoning_style="CASE SCENARIO",
        section_description="Clinical vignettes assessing diagnostic criteria",
        question_count=5,
        marks_per_question=7,
        total_section_marks=35,
    )
    assert sec.reasoning_style == "SCENARIO_BASED"
    assert sec.section_description == "Clinical vignettes assessing diagnostic criteria"

    sec_direct = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.VERY_SHORT_ANSWER,
        reasoning_style="direct memory recall",
        question_count=5,
        marks_per_question=1,
        total_section_marks=5,
    )
    assert sec_direct.reasoning_style == "DIRECT_MEMORY_RECALL"


def test_adapt_reference_blueprint_preserves_reasoning_style():
    bp = PaperBlueprint(
        total_marks=60,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.VERY_SHORT_ANSWER,
                reasoning_style="DIRECT_RECALL",
                question_count=5,
                marks_per_question=1,
                total_section_marks=5,
            ),
            SectionBlueprint(
                name="Section B",
                question_type=QuestionType.SHORT_ANSWER,
                reasoning_style="CONCEPT_EXPLANATION",
                question_count=5,
                marks_per_question=4,
                total_section_marks=20,
            ),
            SectionBlueprint(
                name="Section C",
                question_type=QuestionType.LONG_ANSWER,
                reasoning_style="SCENARIO_BASED",
                section_description="Applied clinical case scenarios",
                question_count=5,
                marks_per_question=7,
                total_section_marks=35,
            ),
        ],
    )

    bs = BlueprintService()
    # Adapt to 40 marks
    adapted = bs.adapt_reference_blueprint(bp, target_total_marks=40)
    assert adapted.total_marks == 40
    assert len(adapted.sections) == 3

    # Section C must retain its reasoning style and description
    sec_c = next(s for s in adapted.sections if s.name == "Section C")
    assert sec_c.reasoning_style == "SCENARIO_BASED"
    assert sec_c.section_description == "Applied clinical case scenarios"


def test_validate_question_structure_scenario_enforcement():
    svc = PaperGeneratorService(db=MagicMock())

    sec_scenario = SectionBlueprint(
        name="Section C",
        question_type=QuestionType.LONG_ANSWER,
        reasoning_style="SCENARIO_BASED",
        question_count=5,
        marks_per_question=7,
        total_section_marks=35,
    )

    # 1. Bare direct recall question in a scenario section should be rejected
    bare_cand = {
        "question_text": "What is depression? Explain its signs.",
        "marks": 7,
    }
    assert svc._validate_question_structure(bare_cand, sec_scenario) is False

    # 2. Domain-agnostic: Clinical scenario (Psychology)
    psych_cand = {
        "question_text": (
            "A 34-year-old corporate executive presents with persistent low mood, loss of appetite, "
            "and anhedonia lasting for over six months following a company reorganization. "
            "Identify the clinical condition and recommend an evidence-based behavioral intervention."
        ),
        "marks": 7,
    }
    assert svc._validate_question_structure(psych_cand, sec_scenario) is True
    assert psych_cand["reasoning_style"] == "SCENARIO_BASED"
    assert psych_cand["section_name"] == "Section C"

    # 3. Domain-agnostic: Business Management case scenario
    business_cand = {
        "question_text": (
            "Alpha Logistics Ltd. faces severe supply chain delays across its regional distribution centers, "
            "leading to a 25% decrease in customer satisfaction ratings. As an operations consultant, "
            "propose a just-in-time inventory control strategy to mitigate these bottlenecks."
        ),
        "marks": 7,
    }
    assert svc._validate_question_structure(business_cand, sec_scenario) is True
    assert business_cand["reasoning_style"] == "SCENARIO_BASED"

    # 4. Domain-agnostic: Biology experimental scenario
    bio_cand = {
        "question_text": (
            "A research team isolates a novel enzyme from thermophilic bacteria inhabiting deep-sea hydrothermal vents. "
            "During in vitro assays, the catalytic rate peaks at 85°C but plummets drastically above 95°C. "
            "Analyze the structural modifications responsible for thermostability."
        ),
        "marks": 7,
    }
    assert svc._validate_question_structure(bio_cand, sec_scenario) is True
    assert bio_cand["reasoning_style"] == "SCENARIO_BASED"


def test_build_paper_response_maps_reasoning_style():
    svc = PaperGeneratorService(db=MagicMock())

    paper_id = uuid.uuid4()
    bp_dict = {
        "total_marks": 40,
        "sections": [
            {
                "name": "Part A",
                "question_type": "MCQ",
                "question_count": 5,
                "marks_per_question": 1,
                "total_section_marks": 5,
                "reasoning_style": "DIRECT_RECALL",
            },
            {
                "name": "Part C",
                "question_type": "LONG_ANSWER",
                "question_count": 5,
                "marks_per_question": 7,
                "total_section_marks": 35,
                "reasoning_style": "SCENARIO_BASED",
            },
        ],
    }

    mock_paper = MagicMock(spec=GeneratedPaper)
    mock_paper.id = paper_id
    mock_paper.workspace_id = uuid.uuid4()
    mock_paper.subject_id = uuid.uuid4()
    mock_paper.book_id = uuid.uuid4()
    mock_paper.reference_paper_id = None
    mock_paper.title = "Test Paper"
    mock_paper.generation_mode = GenerationMode.REFERENCE
    mock_paper.status = "COMPLETED"
    mock_paper.total_marks = 40
    mock_paper.difficulty = DifficultyLevel.MIXED
    mock_paper.blueprint_json = bp_dict
    mock_paper.selected_chapter_ids = []
    mock_paper.chapter_weightages = []
    mock_paper.pdf_path = None
    mock_paper.document_id = None
    mock_paper.processing_status = "NOT_SAVED"
    mock_paper.deleted_at = None
    mock_paper.error_message = None
    mock_paper.time_allowed_minutes = None
    mock_paper.class_name = None
    mock_paper.topic_focus = None
    mock_paper.easy_percentage = None
    mock_paper.medium_percentage = None
    mock_paper.hard_percentage = None

    q1 = MagicMock(spec=GeneratedPaperQuestion)
    q1.id = uuid.uuid4()
    q1.chapter_id = None
    q1.question_order = 1
    q1.section_name = "Part A"
    q1.question_type = "MCQ"
    q1.question_text = "What is X?"
    q1.marks = 1
    q1.difficulty = "EASY"
    q1.source_type = "AI_GENERATED"
    q1.is_numerical = False
    q1.choice_group = None
    q1.alternative_label = None
    q1.mcq_options = ["A. 1", "B. 2", "C. 3", "D. 4"]
    q1.correct_answer = "A. 1"
    q1.expected_answer = None
    q1.section_description = None
    q1.numerical_values = None
    q1.solution_explanation = None
    q1.unit = None
    q1.visual_required = False

    q2 = MagicMock(spec=GeneratedPaperQuestion)
    q2.id = uuid.uuid4()
    q2.chapter_id = None
    q2.question_order = 11
    q2.section_name = "Part C"
    q2.question_type = "LONG_ANSWER"
    q2.question_text = "In a clinical case study, a patient displays symptoms..."
    q2.marks = 7
    q2.difficulty = "HARD"
    q2.source_type = "AI_GENERATED"
    q2.is_numerical = False
    q2.choice_group = None
    q2.alternative_label = None
    q2.reasoning_style = "SCENARIO_BASED"
    q2.section_description = "Applied clinical vignettes"
    q2.mcq_options = None
    q2.correct_answer = None
    q2.expected_answer = None
    q2.numerical_values = None
    q2.solution_explanation = None
    q2.unit = None
    q2.visual_required = False

    mock_paper.questions = [q1, q2]

    resp = svc._build_paper_response(mock_paper, include_answers=True)
    assert len(resp.questions) == 2

    # Verify reasoning_style and section_description mapped onto PaperQuestionResponse
    assert resp.questions[0].reasoning_style == "DIRECT_RECALL"
    assert resp.questions[0].section_description is None
    assert resp.questions[1].reasoning_style == "SCENARIO_BASED"
    assert resp.questions[1].section_description == "Applied clinical vignettes"

    # Verify blueprint reconstruction from generated paper extracts both fields
    bp_svc = BlueprintService(ai_service=MagicMock())
    reconstructed_bp = bp_svc.build_blueprint_from_generated_paper(mock_paper)
    assert len(reconstructed_bp.sample_questions) == 2
    assert reconstructed_bp.sample_questions[1]["reasoning_style"] == "SCENARIO_BASED"
    assert reconstructed_bp.sample_questions[1]["section_description"] == "Applied clinical vignettes"


def test_custom_invented_reasoning_styles():
    """Verify that custom domain-specific styles invented by Gemini pass normalization, prompt construction, and validation."""
    svc = PaperGeneratorService(db=MagicMock())

    sec_custom = SectionBlueprint(
        name="Section D",
        question_type=QuestionType.LONG_ANSWER,
        reasoning_style="CLINICAL_CASE_VIGNETTE",
        section_description="Patient diagnosis vignettes with differential diagnosis",
        question_count=2,
        marks_per_question=10,
        total_section_marks=20,
    )

    # 1. Custom style is preserved cleanly
    assert sec_custom.reasoning_style == "CLINICAL_CASE_VIGNETTE"

    # 2. Bare recall rejected for custom case/vignette style
    bare_cand = {
        "question_text": "Define schizophrenia and list three symptoms.",
        "marks": 10,
    }
    assert svc._validate_question_structure(bare_cand, sec_custom) is False

    # 3. Contextual clinical case accepted and tagged
    valid_cand = {
        "question_text": (
            "A 45-year-old male with a history of chronic hypertension presents to the emergency room "
            "with sudden-onset severe chest pain radiating to his interscapular region. Blood pressure is 190/110 mmHg. "
            "Formulate the primary differential diagnosis and detail the immediate pharmacological management."
        ),
        "marks": 10,
    }
    assert svc._validate_question_structure(valid_cand, sec_custom) is True
    assert valid_cand["reasoning_style"] == "CLINICAL_CASE_VIGNETTE"

    # 4. Fallback generation produces appropriate context for custom case style
    fallback = svc._create_fallback_question(sec_custom, order=1, difficulty="HARD")
    assert fallback["reasoning_style"] == "CLINICAL_CASE_VIGNETTE"
    assert "scenario" in fallback["question_text"].lower()
