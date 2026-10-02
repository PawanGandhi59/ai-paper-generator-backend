import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from app.schemas.paper import (
    ChapterSelectionConfig,
    DifficultyLevel,
    GenerationMode,
    PaperGenerateRequest,
    QuestionConfigItem,
    QuestionType,
)
from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_question_choice_effective_marks_and_validation():
    """
    Test that QuestionConfigItem correctly computes effective attempt count and
    contributing marks when attempt_question_count is specified.
    """
    # 8 questions generated of 5 marks each, student attempts any 5
    cfg = QuestionConfigItem(
        section_name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=8,
        attempt_question_count=5,
        marks_per_question=5,
    )
    assert cfg.effective_attempt_count == 5
    assert cfg.contributing_marks == 25  # 5 * 5, not 8 * 5 = 40

    # Normal section with no choice: effective attempt count equals question_count
    cfg_normal = QuestionConfigItem(
        section_name="Section A",
        question_type=QuestionType.MCQ,
        question_count=10,
        marks_per_question=1,
    )
    assert cfg_normal.effective_attempt_count == 10
    assert cfg_normal.contributing_marks == 10


def test_paper_generate_request_validation_with_question_choice():
    """
    Test PaperGenerateRequest validation with attempt_question_count:
    - Rejects attempt_question_count > question_count
    - Enforces sum(contributing_marks) == total_marks
    """
    ch_id = uuid4()
    chapters = [ChapterSelectionConfig(chapter_id=ch_id)]

    # 1. Invalid: attempt_question_count > question_count
    with pytest.raises(ValueError, match="cannot exceed question_count"):
        PaperGenerateRequest(
            book_id=uuid4(),
            selected_chapters=chapters,
            generation_mode=GenerationMode.CUSTOM,
            total_marks=25,
            question_configs=[
                QuestionConfigItem(
                    section_name="Section B",
                    question_type=QuestionType.SHORT_ANSWER,
                    question_count=5,
                    attempt_question_count=8,  # Invalid: 8 > 5
                    marks_per_question=5,
                )
            ],
        )

    # 2. Valid: Section A has 10 MCQs of 1 mark (10 marks).
    # Section B has 8 questions of 5 marks, attempt 5 (25 marks).
    # Total marks = 10 + 25 = 35 marks.
    req = PaperGenerateRequest(
        book_id=uuid4(),
        selected_chapters=chapters,
        generation_mode=GenerationMode.CUSTOM,
        total_marks=35,
        question_configs=[
            QuestionConfigItem(
                section_name="Section A",
                question_type=QuestionType.MCQ,
                question_count=10,
                marks_per_question=1,
            ),
            QuestionConfigItem(
                section_name="Section B",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=8,
                attempt_question_count=5,
                marks_per_question=5,
            ),
        ],
    )
    assert req.total_marks == 35


def test_build_custom_blueprint_with_question_choice_and_or_sections():
    """
    Test build_custom_blueprint with:
    - Section A: 5 questions of 2 marks, attempt 4 (contributing 8 marks), or_sections_count=1
    - Section B: 2 questions of 10 marks (contributing 20 marks)
    Total paper marks = 8 + 20 = 28 marks.
    """
    bp_service = BlueprintService(ai_service=MagicMock())
    configs = [
        QuestionConfigItem(
            section_name="Section A",
            question_type=QuestionType.SHORT_ANSWER,
            question_count=5,
            attempt_question_count=4,
            or_sections_count=1,
            marks_per_question=2,
        ),
        QuestionConfigItem(
            section_name="Section B",
            question_type=QuestionType.LONG_ANSWER,
            question_count=2,
            marks_per_question=10,
        ),
    ]

    bp = bp_service.build_custom_blueprint(
        question_configs=configs,
        total_marks=28,
    )

    # Must contain 3 sections: Section A, Section A (OR), Section B
    assert len(bp.sections) == 3
    sec_a, sec_a_or, sec_b = bp.sections

    # Primary Section A
    assert sec_a.name == "Section A"
    assert sec_a.question_count == 5
    assert sec_a.attempt_question_count == 4
    assert sec_a.or_sections_count == 1
    assert sec_a.is_or_alternative is False
    assert sec_a.total_section_marks == 8  # 4 * 2
    assert sec_a.choice_rule == "answer_4_of_5"

    # Alternative Section A (OR)
    assert sec_a_or.name == "Section A (OR)"
    assert sec_a_or.question_count == 5
    assert sec_a_or.attempt_question_count == 4
    assert sec_a_or.or_sections_count == 0
    assert sec_a_or.is_or_alternative is True
    assert sec_a_or.total_section_marks == 8
    assert sec_a_or.choice_rule == "answer_4_of_5"

    # Section B
    assert sec_b.name == "Section B"
    assert sec_b.question_count == 2
    assert sec_b.attempt_question_count is None
    assert sec_b.is_or_alternative is False
    assert sec_b.total_section_marks == 20

    # Blueprint validation passes
    bp_service.validate_blueprint(bp)


def test_preplan_matrix_mirrors_or_section_chapters_and_difficulty():
    """
    Test that preplan_blueprint_matrix properly allocates chapter weightages
    to the primary section and mirrors the exact chapter, difficulty, and numerical
    flags to the corresponding slots in the alternative OR section.
    """
    svc = PaperGeneratorService(db=MagicMock())
    ch1_id = str(uuid4())
    ch2_id = str(uuid4())

    sec_main = SectionBlueprint(
        name="Section C",
        question_type=QuestionType.LONG_ANSWER,
        question_count=2,
        marks_per_question=10,
        total_section_marks=20,
        or_sections_count=1,
        is_or_alternative=False,
    )
    sec_or = SectionBlueprint(
        name="Section C (OR)",
        question_type=QuestionType.LONG_ANSWER,
        question_count=2,
        marks_per_question=10,
        total_section_marks=20,
        or_sections_count=0,
        is_or_alternative=True,
    )

    bp = PaperBlueprint(total_marks=20, sections=[sec_main, sec_or])
    chapter_weightages = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Magnetism", "allocated_marks": 10},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Optics", "allocated_marks": 10},
    ]

    planned = svc.preplan_blueprint_matrix(
        blueprint=bp,
        chapter_weightages_data=chapter_weightages,
        easy_pct=50,
        med_pct=50,
        hard_pct=0,
    )

    assert len(planned) == 2
    main_plan = planned[0]
    or_plan = planned[1]

    assert main_plan["section_name"] == "Section C"
    assert or_plan["section_name"] == "Section C (OR)"

    # Verify both slots match in chapter and difficulty
    for idx in range(2):
        main_g = main_plan["groups"][idx]
        or_g = or_plan["groups"][idx]
        assert main_g["chapter_number"] == or_g["chapter_number"]
        assert main_g["chapter_name"] == or_g["chapter_name"]
        assert main_g["difficulty"] == or_g["difficulty"]
        assert main_g["marks"] == or_g["marks"]


def test_analyze_reference_paper_with_section_choice_and_or_section():
    """
    Test that analyze_reference_paper correctly parses sections with
    attempt_question_count and is_or_alternative from AI response JSON.
    """
    import json
    mock_ai = MagicMock()
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 30,
        "sections": [
            {
                "name": "Section A",
                "question_type": "SHORT_ANSWER",
                "question_count": 8,
                "attempt_question_count": 5,
                "marks_per_question": 2,
                "total_section_marks": 10,
                "choice_rule": "answer_5_of_8",
            },
            {
                "name": "Section B",
                "question_type": "LONG_ANSWER",
                "question_count": 2,
                "marks_per_question": 10,
                "total_section_marks": 20,
                "or_sections_count": 1,
                "is_or_alternative": False,
            },
            {
                "name": "Section B (OR)",
                "question_type": "LONG_ANSWER",
                "question_count": 2,
                "marks_per_question": 10,
                "total_section_marks": 20,
                "or_sections_count": 0,
                "is_or_alternative": True,
            },
        ],
        "sample_questions": [],
    })

    bp_service = BlueprintService(ai_service=mock_ai)
    bp = bp_service.analyze_reference_paper(paper_pages_text=["Sample past paper text"])

    assert bp.total_marks == 30  # 10 + 20 (Section B (OR) is excluded from total)
    assert len(bp.sections) == 3
    assert bp.sections[0].attempt_question_count == 5
    assert bp.sections[0].total_section_marks == 10
    assert bp.sections[1].or_sections_count == 1
    assert bp.sections[1].is_or_alternative is False
    assert bp.sections[2].is_or_alternative is True


def test_validate_final_paper_integrity_with_section_choice_and_or_sections():
    """
    Test that _validate_final_paper_integrity accepts papers where:
    - Section A has 8 questions (2 marks each), attempt 5 (10 contributing marks).
    - Section B has 1 question of 10 marks (10 contributing marks).
    - Section B (OR) has 1 alternative question of 10 marks (0 extra contributing marks).
    Total paper marks = 20.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=8,
        attempt_question_count=5,
        marks_per_question=2,
        total_section_marks=10,
        choice_rule="answer_5_of_8",
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.LONG_ANSWER,
        question_count=1,
        marks_per_question=10,
        total_section_marks=10,
        or_sections_count=1,
        is_or_alternative=False,
    )
    sec_b_or = SectionBlueprint(
        name="Section B (OR)",
        question_type=QuestionType.LONG_ANSWER,
        question_count=1,
        marks_per_question=10,
        total_section_marks=10,
        or_sections_count=0,
        is_or_alternative=True,
    )
    bp = PaperBlueprint(total_marks=20, sections=[sec_a, sec_b, sec_b_or])

    questions = []
    # 8 questions for Section A
    for i in range(1, 9):
        questions.append({
            "section_name": "Section A",
            "question_order": i,
            "question_text": f"Section A unique question {i} regarding principle of conservation?",
            "marks": 2,
            "question_type": "SHORT_ANSWER",
            "difficulty": "MEDIUM",
        })
    # 1 question for Section B
    questions.append({
        "section_name": "Section B",
        "question_order": 9,
        "question_text": "Section B detailed derivation of electromagnetic wave equations.",
        "marks": 10,
        "question_type": "LONG_ANSWER",
        "difficulty": "HARD",
    })
    # 1 question for Section B (OR)
    questions.append({
        "section_name": "Section B (OR)",
        "question_order": 10,
        "question_text": "Section B (OR) alternative analysis of Maxwell equations in vacuum.",
        "marks": 10,
        "question_type": "LONG_ANSWER",
        "difficulty": "HARD",
    })

    # Should validate cleanly without raising HTTPException
    svc._validate_final_paper_integrity(
        blueprint=bp,
        generated_questions=questions,
        selected_chapter_ids=None,
        chapter_weightages_data=None,
        generation_mode=GenerationMode.CUSTOM,
    )


