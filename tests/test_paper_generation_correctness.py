import json
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException

from app.schemas.paper import DifficultyLevel, GenerationMode, QuestionType
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


class MockChapter:
    def __init__(self, ch_id, chapter_number, name):
        self.id = ch_id
        self.chapter_number = chapter_number
        self.name = name


# =====================================================================
# 1. CHAPTER ALLOCATION TESTS (Hamilton-Hare / Largest Remainder)
# =====================================================================

def test_chapter_allocation_equal_12_5_percent():
    """
    100 marks / 8 chapters / 12.5% each:
    Must produce: 13, 13, 13, 13, 12, 12, 12, 12
    Sum must be exactly 100.
    No dumping +4 remainder onto a single chapter (e.g. 16, 12, 12, ...).
    """
    chapters = [MockChapter(uuid4(), i, f"Chapter {i}") for i in range(1, 9)]
    allocs = PaperGeneratorService.calculate_proportional_chapter_allocations(
        ordered_chapters=chapters,
        total_marks=100,
    )

    marks = [a["allocated_marks"] for a in allocs]
    assert marks == [13, 13, 13, 13, 12, 12, 12, 12], f"Expected [13, 13, 13, 13, 12, 12, 12, 12], got {marks}"
    assert sum(marks) == 100
    for a in allocs:
        assert a["weightage_percentage"] == 12.5


def test_chapter_allocation_unequal_weights():
    """
    Custom weights: Chapter 1: 50%, Chapter 2: 30%, Chapter 3: 20% on 70 marks.
    Raw: 35.0, 21.0, 14.0 -> Exact integers without remainder.
    """
    ch1, ch2, ch3 = MockChapter(uuid4(), 1, "Ch 1"), MockChapter(uuid4(), 2, "Ch 2"), MockChapter(uuid4(), 3, "Ch 3")
    weightage_lookup = {ch1.id: 50.0, ch2.id: 30.0, ch3.id: 20.0}
    allocs = PaperGeneratorService.calculate_proportional_chapter_allocations(
        ordered_chapters=[ch1, ch2, ch3],
        total_marks=70,
        weightage_lookup=weightage_lookup,
    )

    marks = [a["allocated_marks"] for a in allocs]
    assert marks == [35, 21, 14]
    assert sum(marks) == 70


def test_chapter_allocation_fractional_rounding():
    """
    Custom fractional weights: Ch 1: 33.33%, Ch 2: 33.33%, Ch 3: 33.34% on 50 marks.
    Raw: 16.665, 16.665, 16.670. Base: 16, 16, 16 (sum=48, surplus=2).
    Remainders: 0.665, 0.665, 0.670.
    Sorted by remainder descending: Ch 3 (0.670), then Ch 1 (0.665, tie-broken by ch_number 1), then Ch 2.
    Surplus 2 goes to Ch 3 and Ch 1.
    Expected: Ch 1 = 17, Ch 2 = 16, Ch 3 = 17. Sum = 50.
    """
    ch1, ch2, ch3 = MockChapter(uuid4(), 1, "Ch 1"), MockChapter(uuid4(), 2, "Ch 2"), MockChapter(uuid4(), 3, "Ch 3")
    weightage_lookup = {ch1.id: 33.33, ch2.id: 33.33, ch3.id: 33.34}
    allocs = PaperGeneratorService.calculate_proportional_chapter_allocations(
        ordered_chapters=[ch1, ch2, ch3],
        total_marks=50,
        weightage_lookup=weightage_lookup,
    )

    marks = [a["allocated_marks"] for a in allocs]
    assert marks == [17, 16, 17]
    assert sum(marks) == 50


def test_chapter_allocation_sum_equals_total_marks():
    """
    Test odd totals and prime chapter counts: 33 marks across 7 chapters, 80 marks across 9 chapters.
    Sum must ALWAYS equal total_marks exactly.
    """
    chapters_7 = [MockChapter(uuid4(), i, f"Ch {i}") for i in range(1, 8)]
    allocs_33 = PaperGeneratorService.calculate_proportional_chapter_allocations(chapters_7, total_marks=33)
    assert sum(a["allocated_marks"] for a in allocs_33) == 33

    chapters_9 = [MockChapter(uuid4(), i, f"Ch {i}") for i in range(1, 10)]
    allocs_80 = PaperGeneratorService.calculate_proportional_chapter_allocations(chapters_9, total_marks=80)
    assert sum(a["allocated_marks"] for a in allocs_80) == 80


# =====================================================================
# 2. INTERNAL-CHOICE PAIRING & RECOVERY TESTS
# =====================================================================

def _build_test_blueprint(question_count=3, marks_per_question=5, has_internal_choice=True):
    sec = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=question_count,
        marks_per_question=marks_per_question,
        total_section_marks=question_count * marks_per_question,
        has_internal_choice=has_internal_choice,
        alternatives_per_question=2 if has_internal_choice else 1,
        numerical_question_count=0,
    )
    return PaperBlueprint(
        total_marks=question_count * marks_per_question,
        sections=[sec],
    )


def test_internal_choice_pairing_complete_initial_generation():
    """
    Main call generates complete pairs with explicit choice metadata:
    Q1a, Q1b, Q2a, Q2b.
    Python maps them and validates matching choice_group and sequential order.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=2, marks_per_question=5, has_internal_choice=True)

    candidates = [
        {"question_text": "Text 1a", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans 1a"},
        {"question_text": "Text 1b", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans 1b"},
        {"question_text": "Text 2a", "choice_group": "Q2", "alternative_label": "a", "expected_answer": "Ans 2a"},
        {"question_text": "Text 2b", "choice_group": "Q2", "alternative_label": "b", "expected_answer": "Ans 2b"},
    ]

    with patch.object(svc.ai_service, "generate_response", return_value='{"questions": []}'):
        with patch.object(svc, "_parse_json_safely", return_value={"sections": [{"section_name": "Section B", "questions": candidates}]}):
            qs = svc._generate_complete_paper(
                blueprint=bp,
                context_text="Sample text",
                topic_focus=None,
                difficulty=DifficultyLevel.MEDIUM,
                generation_mode=GenerationMode.CUSTOM,
                sample_questions=None,
            )

    assert len(qs) == 4
    # Check Q1 pair
    assert qs[0]["choice_group"] == "Q1" and qs[0]["alternative_label"] == "a" and qs[0]["question_order"] == 1
    assert qs[1]["choice_group"] == "Q1" and qs[1]["alternative_label"] == "b" and qs[1]["question_order"] == 1
    # Check Q2 pair
    assert qs[2]["choice_group"] == "Q2" and qs[2]["alternative_label"] == "a" and qs[2]["question_order"] == 2
    assert qs[3]["choice_group"] == "Q2" and qs[3]["alternative_label"] == "b" and qs[3]["question_order"] == 2


def test_internal_choice_pairing_recovery_out_of_order_preservation():
    """
    CRITICAL USER TEST:
    Main call generates ONLY:
      Q1a, Q2a, Q3a
    Recovery returns in ARBITRARY order:
      Q3b, Q1b, Q2b

    The final result MUST still be:
      Q1a / Q1b (choice_group "Q1", question_order 1)
      Q2a / Q2b (choice_group "Q2", question_order 2)
      Q3a / Q3b (choice_group "Q3", question_order 3)

    Index-based pairing (cand_idx // 2) would have corrupted this into:
      Q1a/Q2a, Q3a/Q3b, Q1b/Q2b.
    The planned_groups slot grid MUST correctly pair Q1a with Q1b, Q2a with Q2b, Q3a with Q3b!
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=3, marks_per_question=5, has_internal_choice=True)

    # Initial main call returns only Q1a, Q2a, Q3a
    initial_candidates = [
        {"question_text": "Text Q1a", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans 1a"},
        {"question_text": "Text Q2a", "choice_group": "Q2", "alternative_label": "a", "expected_answer": "Ans 2a"},
        {"question_text": "Text Q3a", "choice_group": "Q3", "alternative_label": "a", "expected_answer": "Ans 3a"},
    ]

    # Recovery call returns Q3b, Q1b, Q2b (out of order!)
    recovery_candidates = [
        {"question_text": "Text Q3b", "choice_group": "Q3", "alternative_label": "b", "expected_answer": "Ans 3b"},
        {"question_text": "Text Q1b", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans 1b"},
        {"question_text": "Text Q2b", "choice_group": "Q2", "alternative_label": "b", "expected_answer": "Ans 2b"},
    ]

    mock_main_response = '{"sections": [{"section_name": "Section B", "questions": ' + str(initial_candidates).replace("'", '"') + '}]}'
    mock_recovery_response = '{"questions": ' + str(recovery_candidates).replace("'", '"') + '}'

    with patch.object(svc.ai_service, "generate_response", side_effect=[mock_main_response, mock_recovery_response]):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Sample educational material context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    assert len(qs) == 6

    # Verify pairing integrity
    q1a = next(q for q in qs if q["question_text"] == "Text Q1a")
    q1b = next(q for q in qs if q["question_text"] == "Text Q1b")
    assert q1a["choice_group"] == "Q1" and q1a["alternative_label"] == "a" and q1a["question_order"] == 1
    assert q1b["choice_group"] == "Q1" and q1b["alternative_label"] == "b" and q1b["question_order"] == 1

    q2a = next(q for q in qs if q["question_text"] == "Text Q2a")
    q2b = next(q for q in qs if q["question_text"] == "Text Q2b")
    assert q2a["choice_group"] == "Q2" and q2a["alternative_label"] == "a" and q2a["question_order"] == 2
    assert q2b["choice_group"] == "Q2" and q2b["alternative_label"] == "b" and q2b["question_order"] == 2

    q3a = next(q for q in qs if q["question_text"] == "Text Q3a")
    q3b = next(q for q in qs if q["question_text"] == "Text Q3b")
    assert q3a["choice_group"] == "Q3" and q3a["alternative_label"] == "a" and q3a["question_order"] == 3
    assert q3b["choice_group"] == "Q3" and q3b["alternative_label"] == "b" and q3b["question_order"] == 3

    # Verify that in sequential array, alternatives of the same question are adjacent
    assert qs[0]["question_text"] == "Text Q1a" and qs[1]["question_text"] == "Text Q1b"
    assert qs[2]["question_text"] == "Text Q2a" and qs[3]["question_text"] == "Text Q2b"
    assert qs[4]["question_text"] == "Text Q3a" and qs[5]["question_text"] == "Text Q3b"


def test_internal_choice_pairing_partial_alternatives():
    """
    Main call generates Q1a, Q1b, Q2a (Q2b is missing).
    Recovery returns only Q2b.
    Final output pairs Q1a/Q1b and Q2a/Q2b correctly.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=2, marks_per_question=5, has_internal_choice=True)

    initial_candidates = [
        {"question_text": "Text 1a", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans 1a"},
        {"question_text": "Text 1b", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans 1b"},
        {"question_text": "Text 2a", "choice_group": "Q2", "alternative_label": "a", "expected_answer": "Ans 2a"},
    ]
    recovery_candidates = [
        {"question_text": "Text 2b", "choice_group": "Q2", "alternative_label": "b", "expected_answer": "Ans 2b"},
    ]

    mock_main_response = '{"sections": [{"section_name": "Section B", "questions": ' + str(initial_candidates).replace("'", '"') + '}]}'
    mock_recovery_response = '{"questions": ' + str(recovery_candidates).replace("'", '"') + '}'

    with patch.object(svc.ai_service, "generate_response", side_effect=[mock_main_response, mock_recovery_response]):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    assert len(qs) == 4
    assert qs[2]["choice_group"] == "Q2" and qs[2]["alternative_label"] == "a"
    assert qs[3]["choice_group"] == "Q2" and qs[3]["alternative_label"] == "b"


def test_internal_choice_pairing_metadata_less_candidates():
    """
    Candidates returned without choice_group / alternative_label:
    Python must map them safely to primary 'a' slots (never blindly pair adjacent candidates
    into 'b' slots of unrelated questions). Missing 'b' slots are then recovered.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=2, marks_per_question=5, has_internal_choice=True)

    # Initial call returns 2 questions without metadata
    initial_candidates = [
        {"question_text": "Primary Question 1", "expected_answer": "Ans 1"},
        {"question_text": "Primary Question 2", "expected_answer": "Ans 2"},
    ]
    # Recovery generates the targeted missing 'b' slots
    recovery_candidates = [
        {"question_text": "Alternative Question 1b", "expected_answer": "Ans 1b"},
        {"question_text": "Alternative Question 2b", "expected_answer": "Ans 2b"},
    ]

    mock_main_response = '{"sections": [{"section_name": "Section B", "questions": ' + str(initial_candidates).replace("'", '"') + '}]}'
    mock_recovery_response = '{"questions": ' + str(recovery_candidates).replace("'", '"') + '}'

    with patch.object(svc.ai_service, "generate_response", side_effect=[mock_main_response, mock_recovery_response]):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    assert len(qs) == 4
    assert qs[0]["question_text"] == "Primary Question 1"
    assert qs[0]["choice_group"] == "Q1" and qs[0]["alternative_label"] == "a"
    assert qs[1]["question_text"] == "Alternative Question 1b"
    assert qs[1]["choice_group"] == "Q1" and qs[1]["alternative_label"] == "b"

    assert qs[2]["question_text"] == "Primary Question 2"
    assert qs[2]["choice_group"] == "Q2" and qs[2]["alternative_label"] == "a"
    assert qs[3]["question_text"] == "Alternative Question 2b"
    assert qs[3]["choice_group"] == "Q2" and qs[3]["alternative_label"] == "b"


def test_recovery_excess_candidates_ignored():
    """
    When recovery returns more candidates than the missing slots, only the needed
    slots are filled. Excess candidates are safely dropped.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=1, marks_per_question=5, has_internal_choice=True)

    initial_candidates = [
        {"question_text": "Question 1a text", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans 1a"},
    ]
    # Missing 1 slot (Q1b), but recovery returns 3 candidates
    recovery_candidates = [
        {"question_text": "Question 1b Needed", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans 1b"},
        {"question_text": "Question 1b Excess 1", "expected_answer": "Ans"},
        {"question_text": "Question 1b Excess 2", "expected_answer": "Ans"},
    ]

    mock_main = '{"sections": [{"section_name": "Section B", "questions": ' + str(initial_candidates).replace("'", '"') + '}]}'
    mock_rec = '{"questions": ' + str(recovery_candidates).replace("'", '"') + '}'

    with patch.object(svc.ai_service, "generate_response", side_effect=[mock_main, mock_rec]):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    assert len(qs) == 2
    assert qs[0]["question_text"] == "Question 1a text"
    assert qs[1]["question_text"] == "Question 1b Needed"


def test_recovery_duplicate_rejection_and_feedback():
    """
    When a recovery attempt generates a candidate that is a duplicate of an existing question,
    it must be rejected and its text must be fed back in the next recovery attempt's prompt
    under STRICT REJECTION FEEDBACK.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=1,
        marks_per_question=2,
        total_section_marks=2,
        has_internal_choice=True,
        alternatives_per_question=2,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=2, sections=[sec])

    initial_candidates = [
        {"question_text": "What is the equivalent capacitance of series capacitors?", "expected_answer": "Ans", "choice_group": "Q1", "alternative_label": "a"},
    ]
    # Recovery attempt 1 returns an exact normalized duplicate of Q1a (different casing and punctuation)
    rec1_candidates = [
        {"question_text": "what is the equivalent capacitance of series capacitors.", "expected_answer": "Ans"},
    ]
    # Recovery attempt 2 returns a fresh, non-duplicate question
    rec2_candidates = [
        {"question_text": "Explain the working principle of a van de graaff generator.", "expected_answer": "Ans"},
    ]

    mock_main = '{"sections": [{"section_name": "Section A", "questions": ' + json.dumps(initial_candidates) + '}]}'
    mock_rec1 = '{"questions": ' + json.dumps(rec1_candidates) + '}'
    mock_rec2 = '{"questions": ' + json.dumps(rec2_candidates) + '}'

    captured_prompts = []

    def mock_generate(prompt, system_instruction=None):
        captured_prompts.append(prompt)
        if len(captured_prompts) == 1:
            return mock_main
        elif len(captured_prompts) == 2:
            return mock_rec1
        else:
            return mock_rec2

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    assert len(captured_prompts) == 3
    # Prompt 3 (Recovery attempt 2) must include rejection feedback with the rejected candidate
    assert "STRICT REJECTION FEEDBACK" in captured_prompts[2]
    assert "what is the equivalent capacitance of series capacitors." in captured_prompts[2]
    # And the paper was completed successfully with the valid second recovery candidate
    assert len(qs) == 2
    assert qs[1]["question_text"] == "Explain the working principle of a van de graaff generator."
    assert qs[1]["alternative_label"] == "b"


def test_exact_match_allows_similar_template_questions():
    """
    Legitimate questions with high template word overlap (e.g. electric field vs electric flux)
    must NOT be rejected as duplicates.
    """
    svc = PaperGeneratorService(db=MagicMock())
    q1 = {"question_text": "What is the SI unit of electric field?"}
    q2 = {"question_text": "What is the SI unit of electric flux?"}

    # Under 100% exact match, q2 must NOT be flagged as duplicate of q1
    assert svc._is_duplicate_question(q2, [q1]) is False

    # Exact duplicate (case/punctuation normalized) must be flagged
    q_dup = {"question_text": "what is the si unit of electric field."}
    assert svc._is_duplicate_question(q_dup, [q1]) is True


# =====================================================================
# 3. DIFFICULTY ASSIGNMENT & PROPAGATION TESTS
# =====================================================================

def test_difficulty_propagation_to_both_alternatives():
    """
    Both alternatives (a and b) in a choice group MUST inherit the exact same
    target difficulty planned by Python for that logical group.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=3, marks_per_question=5, has_internal_choice=True)

    # 3 groups planned with difficulty: EASY, MEDIUM, HARD
    with patch.object(svc, "_calculate_difficulty_distribution", return_value=["EASY", "MEDIUM", "HARD"]):
        candidates = [
            {"question_text": "Question 1a text", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans"},
            {"question_text": "Question 1b text", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans"},
            {"question_text": "Question 2a text", "choice_group": "Q2", "alternative_label": "a", "expected_answer": "Ans"},
            {"question_text": "Question 2b text", "choice_group": "Q2", "alternative_label": "b", "expected_answer": "Ans"},
            {"question_text": "Question 3a text", "choice_group": "Q3", "alternative_label": "a", "expected_answer": "Ans"},
            {"question_text": "Question 3b text", "choice_group": "Q3", "alternative_label": "b", "expected_answer": "Ans"},
        ]
        mock_main = '{"sections": [{"section_name": "Section B", "questions": ' + str(candidates).replace("'", '"') + '}]}'
        with patch.object(svc.ai_service, "generate_response", return_value=mock_main):
            qs = svc._generate_complete_paper(
                blueprint=bp,
                context_text="Context",
                topic_focus=None,
                difficulty=DifficultyLevel.MEDIUM,
                generation_mode=GenerationMode.CUSTOM,
                sample_questions=None,
            )

    assert len(qs) == 6
    # Group 1: Both EASY
    assert qs[0]["difficulty"] == "EASY" and qs[1]["difficulty"] == "EASY"
    # Group 2: Both MEDIUM
    assert qs[2]["difficulty"] == "MEDIUM" and qs[3]["difficulty"] == "MEDIUM"
    # Group 3: Both HARD
    assert qs[4]["difficulty"] == "HARD" and qs[5]["difficulty"] == "HARD"


def test_recovery_preserves_target_difficulty():
    """
    When a slot (e.g. Q3b) is missing, recovery receives the target difficulty (HARD)
    and the final question dict has difficulty HARD.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=3, marks_per_question=5, has_internal_choice=True)

    captured_prompts = []

    def mock_generate(prompt, **kwargs):
        captured_prompts.append(prompt)
        if len(captured_prompts) == 1:
            # Main call returns Q1a, Q1b, Q2a, Q2b, Q3a (Q3b missing)
            qs = [
                {"question_text": "Question 1a text", "choice_group": "Q1", "alternative_label": "a", "expected_answer": "Ans"},
                {"question_text": "Question 1b text", "choice_group": "Q1", "alternative_label": "b", "expected_answer": "Ans"},
                {"question_text": "Question 2a text", "choice_group": "Q2", "alternative_label": "a", "expected_answer": "Ans"},
                {"question_text": "Question 2b text", "choice_group": "Q2", "alternative_label": "b", "expected_answer": "Ans"},
                {"question_text": "Question 3a text", "choice_group": "Q3", "alternative_label": "a", "expected_answer": "Ans"},
            ]
            return '{"sections": [{"section_name": "Section B", "questions": ' + str(qs).replace("'", '"') + '}]}'
        else:
            # Recovery returns Q3b
            return '{"questions": [{"question_text": "Q3b Recovered", "choice_group": "Q3", "alternative_label": "b", "expected_answer": "Ans"}]}'

    with patch.object(svc, "_calculate_difficulty_distribution", return_value=["EASY", "MEDIUM", "HARD"]):
        with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate):
            qs = svc._generate_complete_paper(
                blueprint=bp,
                context_text="Context",
                topic_focus=None,
                difficulty=DifficultyLevel.MEDIUM,
                generation_mode=GenerationMode.CUSTOM,
                sample_questions=None,
            )

    assert len(captured_prompts) == 2
    recovery_prompt = captured_prompts[1]
    # Check that recovery prompt specifically requested HARD difficulty for Q3b
    assert "Target Difficulty: HARD" in recovery_prompt

    q3b = next(q for q in qs if q["question_text"] == "Q3b Recovered")
    assert q3b["difficulty"] == "HARD"
    assert q3b["choice_group"] == "Q3" and q3b["alternative_label"] == "b"


# =====================================================================
# 4. REFERENCE MODE SHUFFLE TESTS
# =====================================================================

def test_reference_mode_shuffle_preserves_choice_pairs():
    """
    In REFERENCE mode, shuffling must shuffle logical groups as atomic units.
    Alternative pairs (Q_a, Q_b) must NEVER be separated or interleaved.
    """
    svc = PaperGeneratorService(db=MagicMock())
    bp = _build_test_blueprint(question_count=5, marks_per_question=5, has_internal_choice=True)

    candidates = []
    for i in range(1, 6):
        candidates.append({"question_text": f"Q{i}a text", "choice_group": f"Q{i}", "alternative_label": "a", "expected_answer": "Ans"})
        candidates.append({"question_text": f"Q{i}b text", "choice_group": f"Q{i}", "alternative_label": "b", "expected_answer": "Ans"})

    mock_main = '{"sections": [{"section_name": "Section B", "questions": ' + str(candidates).replace("'", '"') + '}]}'

    with patch.object(svc.ai_service, "generate_response", return_value=mock_main):
        qs = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.REFERENCE,
            sample_questions=[{"question_text": "Sample"}],
        )

    assert len(qs) == 10

    # Group questions by their choice_group in the generated list
    cg_positions = {}
    for idx, q in enumerate(qs):
        cg = q["choice_group"]
        cg_positions.setdefault(cg, []).append(idx)

    # Every choice group must have exactly 2 items, and they must be adjacent (diff in indices == 1)
    for cg, indices in cg_positions.items():
        assert len(indices) == 2, f"Group {cg} has {len(indices)} items"
        assert indices[1] - indices[0] == 1, f"Alternatives for {cg} were separated! Indices: {indices}"


# =====================================================================
# 5. FINAL VALIDATION TESTS
# =====================================================================

def test_final_validation_rejects_mcq_with_wrong_option_count():
    """
    MCQ with fewer or more than 4 options must raise HTTP 400.
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

    # 3 options -> Must fail
    invalid_mcq_3 = [
        {"question_text": "MCQ Question", "marks": 1, "section_name": "Section A", "question_type": "MCQ",
         "correct_answer": "A. 1", "mcq_options": ["A. 1", "B. 2", "C. 3"]}
    ]
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_final_paper_integrity(blueprint=bp, generated_questions=invalid_mcq_3, selected_chapter_ids=[])
    assert exc_info.value.status_code == 400
    assert "must have exactly 4 options" in exc_info.value.detail

    # 4 options -> Must pass
    valid_mcq_4 = [
        {"question_text": "MCQ Question", "marks": 1, "section_name": "Section A", "question_type": "MCQ",
         "correct_answer": "A. 1", "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"]}
    ]
    svc._validate_final_paper_integrity(blueprint=bp, generated_questions=valid_mcq_4, selected_chapter_ids=[])


def test_final_validation_choice_group_mismatch_rejection():
    """
    Choice group items with mismatched marks or difficulty must raise HTTP 400.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=1,
        marks_per_question=5,
        total_section_marks=5,
        has_internal_choice=True,
        alternatives_per_question=2,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=5, sections=[sec])

    # Mismatched marks (Q1a has 5 marks, Q1b has 4 marks)
    mismatched_marks = [
        {"question_text": "Q1a", "marks": 5, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "a", "difficulty": "MEDIUM", "expected_answer": "Ans"},
        {"question_text": "Q1b", "marks": 4, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "b", "difficulty": "MEDIUM", "expected_answer": "Ans"},
    ]
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_final_paper_integrity(blueprint=bp, generated_questions=mismatched_marks, selected_chapter_ids=[])
    assert exc_info.value.status_code == 400
    assert "mismatched marks" in exc_info.value.detail

    # Mismatched difficulty
    mismatched_diff = [
        {"question_text": "Q1a", "marks": 5, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "a", "difficulty": "EASY", "expected_answer": "Ans"},
        {"question_text": "Q1b", "marks": 5, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "b", "difficulty": "HARD", "expected_answer": "Ans"},
    ]
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_final_paper_integrity(blueprint=bp, generated_questions=mismatched_diff, selected_chapter_ids=[])
    assert exc_info.value.status_code == 400
    assert "mismatched difficulty" in exc_info.value.detail


def test_final_validation_total_marks_internal_choice_accounting():
    """
    Total marks validation must count logical/attempted marks.
    Internal choice alternatives (Q1b) must NOT be added as additional marks.
    For 1 question of 5 marks with 2 alternatives, total attempted marks is 5, NOT 10.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=1,
        marks_per_question=5,
        total_section_marks=5,
        has_internal_choice=True,
        alternatives_per_question=2,
        numerical_question_count=0,
    )
    bp = PaperBlueprint(total_marks=5, sections=[sec])

    questions = [
        {"question_text": "Q1a", "marks": 5, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "a", "difficulty": "MEDIUM", "expected_answer": "Ans"},
        {"question_text": "Q1b", "marks": 5, "section_name": "Section B", "choice_group": "Q1", "alternative_label": "b", "difficulty": "MEDIUM", "expected_answer": "Ans"},
    ]
    # Should pass cleanly because logical marks = 5 == blueprint.total_marks
    svc._validate_final_paper_integrity(blueprint=bp, generated_questions=questions, selected_chapter_ids=[])


def test_final_validation_rejects_missing_blueprint_section():
    """
    If a section defined in the blueprint is missing from the generated questions,
    final validation must reject with HTTP 400.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(name="Section A", question_type=QuestionType.MCQ, question_count=1, marks_per_question=1, total_section_marks=1, has_internal_choice=False, alternatives_per_question=1, numerical_question_count=0)
    sec_b = SectionBlueprint(name="Section B", question_type=QuestionType.SHORT_ANSWER, question_count=1, marks_per_question=4, total_section_marks=4, has_internal_choice=False, alternatives_per_question=1, numerical_question_count=0)
    bp = PaperBlueprint(total_marks=5, sections=[sec_a, sec_b])

    # Only Section A provided, Section B missing
    partial_qs = [
        {"question_text": "MCQ 1", "marks": 1, "section_name": "Section A", "question_type": "MCQ", "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"], "correct_answer": "A. 1"}
    ]
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_final_paper_integrity(blueprint=bp, generated_questions=partial_qs, selected_chapter_ids=[])
    assert exc_info.value.status_code == 400
