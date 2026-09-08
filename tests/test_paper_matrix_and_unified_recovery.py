import json
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.schemas.paper import DifficultyLevel, GenerationMode, QuestionType
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_preplan_blueprint_matrix_denomination_aware():
    """
    Test denomination-aware chapter allocation:
    Two chapters:
    - Chapter 1: 15 marks allocated
    - Chapter 2: 10 marks allocated
    Total marks = 25.
    Sections:
    - Section A: 5 MCQs of 1 mark each = 5 marks
    - Section B: 4 Short Answer of 5 marks each = 20 marks
    The 5-mark questions must be allocated first to the chapter with largest deficit,
    and 1-mark questions fine-tune the remaining balance.
    Sum of attempted marks for each chapter must match allocations exactly.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=5,
        marks_per_question=1,
        total_section_marks=5,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=4,
        marks_per_question=5,
        total_section_marks=20,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=25, sections=[sec_a, sec_b])

    ch1_id = str(uuid4())
    ch2_id = str(uuid4())
    chapter_weightages = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Electrostatics", "allocated_marks": 15, "weightage_percentage": 60.0},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Current Electricity", "allocated_marks": 10, "weightage_percentage": 40.0},
    ]

    planned_sections = svc.preplan_blueprint_matrix(
        blueprint=bp,
        difficulty=DifficultyLevel.MIXED,
        chapter_weightages_data=chapter_weightages,
    )

    # Calculate attempted marks assigned to each chapter
    ch_marks = {ch1_id: 0, ch2_id: 0}
    for s in planned_sections:
        for g in s["groups"]:
            ch_marks[g["chapter_id"]] += g["marks"]

    assert ch_marks[ch1_id] == 15, f"Expected Ch 1 to have 15 marks, got {ch_marks[ch1_id]}"
    assert ch_marks[ch2_id] == 10, f"Expected Ch 2 to have 10 marks, got {ch_marks[ch2_id]}"


def test_preplan_blueprint_matrix_intra_chapter_binding():
    """
    Test that both alternatives in an internal choice group (e.g. Q1a and Q1b)
    are strictly bound to the exact same chapter and difficulty.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section C",
        question_type=QuestionType.LONG_ANSWER,
        question_count=3,
        marks_per_question=5,
        total_section_marks=15,
        has_internal_choice=True,
        alternatives_per_question=2,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=15, sections=[sec])

    ch1_id = str(uuid4())
    ch2_id = str(uuid4())
    chapter_weightages = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Optics", "allocated_marks": 10},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Magnetism", "allocated_marks": 5},
    ]

    planned_sections = svc.preplan_blueprint_matrix(
        blueprint=bp,
        difficulty=DifficultyLevel.MIXED,
        chapter_weightages_data=chapter_weightages,
    )

    groups = planned_sections[0]["groups"]
    assert len(groups) == 3
    for g in groups:
        assert g["required_alts"] == ["a", "b"]
        assert g["chapter_id"] in [ch1_id, ch2_id]
        assert g["difficulty"] in ["EASY", "MEDIUM", "HARD"]
        # Both alternatives share the exact same planned group attributes
        assert set(g["slots"].keys()) == {"a", "b"}


def test_unified_whole_paper_recovery_multi_section():
    """
    Test single-pass whole-paper inspection and unified recovery:
    When Section A and Section B both have missing slots,
    the system must make AT MOST ONE unified recovery call covering both sections together,
    rather than looping per-section.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=2,
        marks_per_question=1,
        total_section_marks=2,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=2,
        marks_per_question=2,
        total_section_marks=4,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=6, sections=[sec_a, sec_b])

    # Initial main call returns only 1 question for Sec A (missing 1) and 1 question for Sec B (missing 1)
    main_response = {
        "sections": [
            {"section_name": "Section A", "questions": [{"question_text": "Sec A Q1 MCQ", "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"]}]},
            {"section_name": "Section B", "questions": [{"question_text": "Sec B Q1 SA"}]},
        ]
    }

    # Unified recovery returns both missing questions in ONE response
    recovery_response = {
        "questions": [
            {"section_name": "Section A", "question_text": "Sec A Q2 MCQ Replacement", "mcq_options": ["A. x", "B. y", "C. z", "D. w"]},
            {"section_name": "Section B", "question_text": "Sec B Q2 SA Replacement"},
        ]
    }

    recorded_prompts = []

    def mock_generate(prompt, system_instruction=None, response_schema=None):
        recorded_prompts.append(prompt)
        if len(recorded_prompts) == 1:
            return json.dumps(main_response)
        return json.dumps(recovery_response)

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Global textbook context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    # Exactly 2 AI calls: 1 main generation + 1 unified recovery
    assert len(recorded_prompts) == 2
    assert len(qs) == 4

    # Both missing slots were filled
    q_texts = [q["question_text"] for q in qs]
    assert "Sec A Q1 MCQ" in q_texts
    assert "Sec A Q2 MCQ Replacement" in q_texts
    assert "Sec B Q1 SA" in q_texts
    assert "Sec B Q2 SA Replacement" in q_texts


def test_unified_recovery_scoped_context():
    """
    Test scoped context optimization during recovery:
    If missing slots belong ONLY to Chapter 2,
    the recovery prompt must include ONLY Chapter 2 context excerpts,
    excluding Chapter 1 and reducing token payload by >90%.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=2,
        marks_per_question=2,
        total_section_marks=4,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=4, sections=[sec])

    ch1_id = str(uuid4())
    ch2_id = str(uuid4())
    chapter_weightages = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Ch 1 Mechanics", "allocated_marks": 2},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Ch 2 Waves", "allocated_marks": 2},
    ]

    # Pre-populate chapter contexts map
    svc._chapter_contexts_map = {
        ch1_id: "CHAPTER 1 DETAILED CONTENT (100,000 TOKENS OF MECHANICS)",
        ch2_id: "CHAPTER 2 SPECIFIC CONTENT (WAVES AND OSCILLATIONS)",
    }

    # Main call returns only Q1 (from Chapter 1). Q2 (from Chapter 2) is missing.
    main_response = {
        "sections": [
            {"section_name": "Section A", "questions": [{"question_text": "Mechanics Q1 Text", "chapter_number": 1}]}
        ]
    }
    recovery_response = {
        "questions": [
            {"section_name": "Section A", "question_text": "Waves Q2 Replacement", "chapter_number": 2}
        ]
    }

    recorded_prompts = []

    def mock_generate(prompt, system_instruction=None, response_schema=None):
        recorded_prompts.append(prompt)
        if len(recorded_prompts) == 1:
            return json.dumps(main_response)
        return json.dumps(recovery_response)

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Complete multi-chapter text",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
            chapter_weightages_data=chapter_weightages,
        )

    assert len(recorded_prompts) == 2
    recovery_prompt = recorded_prompts[1]

    # Recovery prompt MUST contain Chapter 2 context and MUST NOT contain Chapter 1 context!
    assert "CHAPTER 2 SPECIFIC CONTENT (WAVES AND OSCILLATIONS)" in recovery_prompt
    assert "CHAPTER 1 DETAILED CONTENT (100,000 TOKENS OF MECHANICS)" not in recovery_prompt


def test_pure_question_paper_validation_allows_none_answers():
    """
    Test pure question paper generation:
    Questions generated without correct_answer, expected_answer, or solution_explanation
    must pass structure and final paper integrity validation without errors.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=1,
        marks_per_question=1,
        total_section_marks=1,
        has_internal_choice=False,
        alternatives_per_question=1,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=1, sections=[sec])

    mcq_q = {
        "question_order": 1,
        "section_name": "Section A",
        "question_type": "MCQ",
        "question_text": "What is the SI unit of electric capacitance?",
        "marks": 1,
        "difficulty": "EASY",
        "mcq_options": ["A. Farad", "B. Henry", "C. Tesla", "D. Weber"],
        "correct_answer": None,
        "expected_answer": None,
        "solution_explanation": None,
    }

    # 1. Structure validation
    assert svc._validate_question_structure(mcq_q, sec) is True

    # 2. Final paper integrity validation
    svc._validate_final_paper_integrity(
        blueprint=bp,
        generated_questions=[mcq_q],
        selected_chapter_ids=[],
    )
