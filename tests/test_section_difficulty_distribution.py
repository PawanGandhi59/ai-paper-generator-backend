import pytest
from unittest.mock import MagicMock

from app.schemas.paper import DifficultyLevel, QuestionType
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_calculate_difficulty_largest_remainder_33_33_34():
    svc = PaperGeneratorService(db=MagicMock())
    # 10 questions with 33% Easy, 33% Medium, 34% Hard -> 3 Easy, 3 Medium, 4 Hard
    res = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.MIXED,
        count=10,
        easy_pct=33,
        med_pct=33,
        hard_pct=34,
    )
    assert len(res) == 10
    assert res.count("EASY") == 3
    assert res.count("MEDIUM") == 3
    assert res.count("HARD") == 4
    # Check intra-section ordering (Easy -> Medium -> Hard)
    assert res == ["EASY"] * 3 + ["MEDIUM"] * 3 + ["HARD"] * 4


def test_calculate_difficulty_single_question_tie_and_highest():
    svc = PaperGeneratorService(db=MagicMock())

    # 1 question with 50% Easy / 50% Hard -> user approved MEDIUM
    res_tie = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.MIXED,
        count=1,
        easy_pct=50,
        med_pct=0,
        hard_pct=50,
    )
    assert res_tie == ["MEDIUM"]

    # 1 question with 33% Easy, 33% Medium, 34% Hard -> HARD (highest)
    res_hard = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.MIXED,
        count=1,
        easy_pct=33,
        med_pct=33,
        hard_pct=34,
    )
    assert res_hard == ["HARD"]

    # 1 question with 60% Easy, 20% Medium, 20% Hard -> EASY (highest)
    res_easy = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.MIXED,
        count=1,
        easy_pct=60,
        med_pct=20,
        hard_pct=20,
    )
    assert res_easy == ["EASY"]


def test_calculate_difficulty_two_questions_33_33_34():
    svc = PaperGeneratorService(db=MagicMock())
    # 2 questions with 33% Easy, 33% Medium, 34% Hard -> 1 EASY, 1 HARD
    res = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.MIXED,
        count=2,
        easy_pct=33,
        med_pct=33,
        hard_pct=34,
    )
    assert res == ["EASY", "HARD"]


def test_calculate_difficulty_uniform():
    svc = PaperGeneratorService(db=MagicMock())
    res = svc._calculate_difficulty_distribution(
        difficulty=DifficultyLevel.HARD,
        count=4,
    )
    assert res == ["HARD", "HARD", "HARD", "HARD"]


def test_preplan_blueprint_matrix_per_section_distribution():
    svc = PaperGeneratorService(db=MagicMock())
    blueprint = PaperBlueprint(
        total_marks=35,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=10,
                marks_per_question=1,
                total_section_marks=10,
                has_internal_choice=False,
                alternatives_per_question=1,
            ),
            SectionBlueprint(
                name="Section B",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=5,
                marks_per_question=3,
                total_section_marks=15,
                has_internal_choice=False,
                alternatives_per_question=1,
            ),
            SectionBlueprint(
                name="Section C",
                question_type=QuestionType.LONG_ANSWER,
                question_count=2,
                marks_per_question=5,
                total_section_marks=10,
                has_internal_choice=True,
                alternatives_per_question=2,
            ),
        ],
    )

    planned = svc.preplan_blueprint_matrix(
        blueprint=blueprint,
        difficulty=DifficultyLevel.MIXED,
        easy_pct=30,
        med_pct=20,
        hard_pct=50,
    )

    assert len(planned) == 3

    # Section A: 10 questions -> 3 Easy, 2 Medium, 5 Hard
    sec_a_diffs = [g["difficulty"] for g in planned[0]["groups"]]
    assert sec_a_diffs.count("EASY") == 3
    assert sec_a_diffs.count("MEDIUM") == 2
    assert sec_a_diffs.count("HARD") == 5
    assert sec_a_diffs == ["EASY"] * 3 + ["MEDIUM"] * 2 + ["HARD"] * 5

    # Section B: 5 questions (marks_per_q=3) -> 5*0.3=1.5, 5*0.2=1.0, 5*0.5=2.5
    # Base: 1 Easy, 1 Med, 2 Hard -> 1 needed. Tied between Easy (0.5) and Hard (0.5).
    # Default tie-break gives Easy -> 2 Easy, 1 Med, 2 Hard
    sec_b_diffs = [g["difficulty"] for g in planned[1]["groups"]]
    assert len(sec_b_diffs) == 5
    assert sec_b_diffs.count("MEDIUM") == 1
    assert sec_b_diffs.count("EASY") + sec_b_diffs.count("HARD") == 4
    # Intra-section ordering: Easy appears before Medium, Medium before Hard
    e_indices = [i for i, d in enumerate(sec_b_diffs) if d == "EASY"]
    m_indices = [i for i, d in enumerate(sec_b_diffs) if d == "MEDIUM"]
    h_indices = [i for i, d in enumerate(sec_b_diffs) if d == "HARD"]
    assert max(e_indices) < min(m_indices)
    assert max(m_indices) < min(h_indices)

    # Section C: 2 questions with internal choice (marks_per_q=5)
    # 2*0.3=0.6, 2*0.2=0.4, 2*0.5=1.0. Hard gets 1 (base 1). Remainder: 0.6 Easy > 0.4 Med -> 1 Easy.
    # Result: 1 Easy, 1 Hard
    sec_c_diffs = [g["difficulty"] for g in planned[2]["groups"]]
    assert sec_c_diffs == ["EASY", "HARD"]

    # Verify choice pair invariance: Q_a and Q_b share identical difficulty
    for g in planned[2]["groups"]:
        assert g["slots"]["a"] is None or g["slots"]["a"]["difficulty"] == g["difficulty"]
