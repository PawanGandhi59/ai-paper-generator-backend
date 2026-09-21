import json
import pytest
from unittest.mock import MagicMock, patch

from app.schemas.paper import DifficultyLevel, GenerationMode, QuestionType
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_partition_planned_sections_single_batch():
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=20,
        marks_per_question=1,
        total_section_marks=20,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=20, sections=[sec_a])
    planned = svc.preplan_blueprint_matrix(bp, difficulty=DifficultyLevel.EASY)

    batches = svc._partition_planned_sections_into_batches(planned, max_batch_size=100)
    assert len(batches) == 1
    total_q = sum(len(bs["groups"]) for bs in batches[0])
    assert total_q == 20


def test_partition_planned_sections_multiple_batches_150_questions():
    svc = PaperGeneratorService(db=MagicMock())
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=80,
        marks_per_question=1,
        total_section_marks=80,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=70,
        marks_per_question=2,
        total_section_marks=140,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=220, sections=[sec_a, sec_b])
    planned = svc.preplan_blueprint_matrix(bp, difficulty=DifficultyLevel.EASY)

    batches = svc._partition_planned_sections_into_batches(planned, max_batch_size=100)
    assert len(batches) == 2

    # Batch 1: exactly 100 questions (Section A: 80, Section B: 20)
    batch_1_count = sum(len(bs["groups"]) for bs in batches[0])
    assert batch_1_count == 100
    assert batches[0][0]["section_name"] == "Section A"
    assert len(batches[0][0]["groups"]) == 80
    assert batches[0][1]["section_name"] == "Section B"
    assert len(batches[0][1]["groups"]) == 20

    # Batch 2: remaining 50 questions of Section B
    batch_2_count = sum(len(bs["groups"]) for bs in batches[1])
    assert batch_2_count == 50
    assert batches[1][0]["section_name"] == "Section B"
    assert len(batches[1][0]["groups"]) == 50


def test_partition_planned_sections_chapter_clustering():
    """
    Verify that question slots are clustered chapter-by-chapter:
    - Chapter 1 has 80 questions.
    - Chapter 2 has 30 questions.
    - Chapter 3 has 40 questions.
    Total = 150 questions.
    Batch 1 (100 questions) gets all 80 of Ch 1 + 20 of Ch 2.
    Batch 2 (50 questions) gets remaining 10 of Ch 2 + all 40 of Ch 3.
    Chapter 1 NEVER appears in Batch 2!
    Chapter 3 NEVER appears in Batch 1!
    """
    svc = PaperGeneratorService(db=MagicMock())
    ch1 = "11111111-1111-1111-1111-111111111111"
    ch2 = "22222222-2222-2222-2222-222222222222"
    ch3 = "33333333-3333-3333-3333-333333333333"

    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=50,
        marks_per_question=1,
        total_section_marks=50,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=60,
        marks_per_question=1,
        total_section_marks=60,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    sec_c = SectionBlueprint(
        name="Section C",
        question_type=QuestionType.LONG_ANSWER,
        question_count=40,
        marks_per_question=1,
        total_section_marks=40,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=150, sections=[sec_a, sec_b, sec_c])

    # Ch 1: 80 marks (50 from Sec A + 30 from Sec B)
    # Ch 2: 30 marks (30 from Sec B)
    # Ch 3: 40 marks (40 from Sec C)
    chapter_weights = [
        {"chapter_id": ch1, "chapter_number": 1, "chapter_name": "Ch 1", "allocated_marks": 80},
        {"chapter_id": ch2, "chapter_number": 2, "chapter_name": "Ch 2", "allocated_marks": 30},
        {"chapter_id": ch3, "chapter_number": 3, "chapter_name": "Ch 3", "allocated_marks": 40},
    ]

    planned = svc.preplan_blueprint_matrix(bp, difficulty=DifficultyLevel.EASY, chapter_weightages_data=chapter_weights)
    batches = svc._partition_planned_sections_into_batches(planned, max_batch_size=100)

    assert len(batches) == 2

    # Batch 1: 100 questions
    b1_groups = [g for bs in batches[0] for g in bs["groups"]]
    assert len(b1_groups) == 100
    b1_ch1_count = sum(1 for g in b1_groups if g.get("chapter_id") == ch1)
    b1_ch2_count = sum(1 for g in b1_groups if g.get("chapter_id") == ch2)
    b1_ch3_count = sum(1 for g in b1_groups if g.get("chapter_id") == ch3)
    assert b1_ch1_count == 80  # ALL 80 questions of Ch 1 in Batch 1
    assert b1_ch2_count == 20  # First 20 questions of Ch 2 in Batch 1
    assert b1_ch3_count == 0   # ZERO questions of Ch 3 in Batch 1

    # Batch 2: 50 questions
    b2_groups = [g for bs in batches[1] for g in bs["groups"]]
    assert len(b2_groups) == 50
    b2_ch1_count = sum(1 for g in b2_groups if g.get("chapter_id") == ch1)
    b2_ch2_count = sum(1 for g in b2_groups if g.get("chapter_id") == ch2)
    b2_ch3_count = sum(1 for g in b2_groups if g.get("chapter_id") == ch3)
    assert b2_ch1_count == 0   # ZERO questions of Ch 1 in Batch 2 (Ch 1 is 100% completed!)
    assert b2_ch2_count == 10  # Remaining 10 questions of Ch 2
    assert b2_ch3_count == 40  # ALL 40 questions of Ch 3 in Batch 2


def test_batched_generation_calls_gemini_multiple_times_and_scopes_context():
    svc = PaperGeneratorService(db=MagicMock())
    ch1_id = "11111111-1111-1111-1111-111111111111"
    ch2_id = "22222222-2222-2222-2222-222222222222"
    ch3_id = "33333333-3333-3333-3333-333333333333"

    # Set up chapter contexts map with 3 chapters
    svc._chapter_contexts_map = {
        ch1_id: "[Digest for Chapter 1 on Newton Laws]",
        ch2_id: "[Digest for Chapter 2 on Thermodynamics]",
        ch3_id: "[Digest for Chapter 3 on Optics]",
    }

    # Blueprint: 100 questions in Sec A (1m) and 20 questions in Sec B (1m) -> 120 questions total
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=100,
        marks_per_question=1,
        total_section_marks=100,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=20,
        marks_per_question=1,
        total_section_marks=20,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=120, sections=[sec_a, sec_b])

    # Chapter 1 has 110 marks, Chapter 2 has 10 marks.
    # Questions 1-100 (Batch 1) will all be allocated to Chapter 1.
    # Chapter 3 is not in the paper at all.
    chapter_weights = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Newton Laws", "allocated_marks": 110},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Thermodynamics", "allocated_marks": 10},
    ]

    captured_prompts = []

    def mock_generate(prompt, system_instruction=None, **kwargs):
        captured_prompts.append(prompt)
        if len(captured_prompts) == 1:
            # Batch 1: 100 questions from Section A
            qs_a = [
                {"question_order": i, "section_name": "Section A", "question_type": "MCQ", "question_text": f"MCQ Q{i}", "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"]}
                for i in range(1, 101)
            ]
            return json.dumps({
                "sections": [
                    {"section_name": "Section A", "questions": qs_a},
                ]
            })
        else:
            # Batch 2: 20 questions from Section B
            qs_b = [
                {"question_order": 100 + i, "section_name": "Section B", "question_type": "SHORT_ANSWER", "question_text": f"SA Q{100 + i}"}
                for i in range(1, 21)
            ]
            return json.dumps({
                "sections": [
                    {"section_name": "Section B", "questions": qs_b},
                ]
            })

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate), \
         patch.object(svc.ai_service, "count_tokens", return_value=500):
        questions = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Fallback context",
            topic_focus=None,
            difficulty=DifficultyLevel.MIXED,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
            chapter_weightages_data=chapter_weights,
        )

    # Assert exactly 2 LLM batch calls were made
    assert len(captured_prompts) == 2

    # Batch 1 had Questions 1-100 (strictly Chapter 1):
    # Its scoped context must include Chapter 1, and NOT Chapter 2 or Chapter 3!
    batch_1_prompt = captured_prompts[0]
    assert "[Digest for Chapter 1 on Newton Laws]" in batch_1_prompt
    assert "[Digest for Chapter 2 on Thermodynamics]" not in batch_1_prompt
    assert "[Digest for Chapter 3 on Optics]" not in batch_1_prompt

    # Batch 2 has questions from Chapter 2 and Chapter 1, but NEVER Chapter 3!
    batch_2_prompt = captured_prompts[1]
    assert "[Digest for Chapter 2 on Thermodynamics]" in batch_2_prompt
    assert "[Digest for Chapter 3 on Optics]" not in batch_2_prompt

    # All 120 questions are populated
    assert len(questions) == 120
    orders = [q["question_order"] for q in questions]
    assert orders == list(range(1, 121))


def test_partition_missing_slots_into_batches():
    """
    Test that _partition_missing_slots_into_batches clusters missing slots chapter-by-chapter
    and caps batches at 100 slots.
    """
    ch1_id = "11111111-1111-1111-1111-111111111111"
    ch2_id = "22222222-2222-2222-2222-222222222222"
    ch3_id = "33333333-3333-3333-3333-333333333333"

    missing = []
    # 80 slots from Ch 1
    for i in range(80):
        missing.append({"question_order": i + 1, "chapter_id": ch1_id, "chapter_number": 1})
    # 40 slots from Ch 2
    for i in range(40):
        missing.append({"question_order": 80 + i + 1, "chapter_id": ch2_id, "chapter_number": 2})
    # 30 slots from Ch 3
    for i in range(30):
        missing.append({"question_order": 120 + i + 1, "chapter_id": ch3_id, "chapter_number": 3})

    batches = PaperGeneratorService._partition_missing_slots_into_batches(missing, max_batch_size=100)
    assert len(batches) == 2

    # Batch 1: 100 slots (80 from Ch 1, 20 from Ch 2)
    assert len(batches[0]) == 100
    b1_ch1 = sum(1 for s in batches[0] if s["chapter_id"] == ch1_id)
    b1_ch2 = sum(1 for s in batches[0] if s["chapter_id"] == ch2_id)
    b1_ch3 = sum(1 for s in batches[0] if s["chapter_id"] == ch3_id)
    assert b1_ch1 == 80
    assert b1_ch2 == 20
    assert b1_ch3 == 0

    # Batch 2: 50 slots (remaining 20 from Ch 2, 30 from Ch 3)
    assert len(batches[1]) == 50
    b2_ch1 = sum(1 for s in batches[1] if s["chapter_id"] == ch1_id)
    b2_ch2 = sum(1 for s in batches[1] if s["chapter_id"] == ch2_id)
    b2_ch3 = sum(1 for s in batches[1] if s["chapter_id"] == ch3_id)
    assert b2_ch1 == 0
    assert b2_ch2 == 20
    assert b2_ch3 == 30


def test_batched_recovery_more_than_100_missing():
    """
    Test that when recovery has > 100 missing slots, it partitions them into
    batches of <= 100 questions, calling the LLM multiple times with scoped context.
    """
    svc = PaperGeneratorService(db=MagicMock())
    ch1_id = "11111111-1111-1111-1111-111111111111"
    ch2_id = "22222222-2222-2222-2222-222222222222"

    svc._chapter_contexts_map = {
        ch1_id: "[Digest for Chapter 1]",
        ch2_id: "[Digest for Chapter 2]",
    }

    # 120 questions across Sec A (100) and Sec B (20)
    sec_a = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=100,
        marks_per_question=1,
        total_section_marks=100,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    sec_b = SectionBlueprint(
        name="Section B",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=20,
        marks_per_question=1,
        total_section_marks=20,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=120, sections=[sec_a, sec_b])

    chapter_weights = [
        {"chapter_id": ch1_id, "chapter_number": 1, "chapter_name": "Ch 1", "allocated_marks": 100},
        {"chapter_id": ch2_id, "chapter_number": 2, "chapter_name": "Ch 2", "allocated_marks": 20},
    ]

    captured_prompts = []

    def mock_generate(prompt, system_instruction=None, **kwargs):
        captured_prompts.append((prompt, system_instruction))
        # Initial calls return empty questions so all slots remain missing
        if len(captured_prompts) <= 2:
            return json.dumps({"sections": []})
        
        # Recovery call 1: batch of 100 slots (from Ch 1)
        if len(captured_prompts) == 3:
            qs = [
                {
                    "section_name": "Section A",
                    "question_order": i + 1,
                    "question_text": f"Recovered Q{i + 1}",
                    "question_type": "SHORT_ANSWER",
                    "chapter_number": 1,
                    "marks": 1,
                    "difficulty": "EASY",
                }
                for i in range(100)
            ]
            return json.dumps({"questions": qs})

        # Recovery call 2: batch of 20 slots (from Ch 2)
        if len(captured_prompts) == 4:
            qs = [
                {
                    "section_name": "Section B",
                    "question_order": 100 + i + 1,
                    "question_text": f"Recovered Q{100 + i + 1}",
                    "question_type": "SHORT_ANSWER",
                    "chapter_number": 2,
                    "marks": 1,
                    "difficulty": "EASY",
                }
                for i in range(20)
            ]
            return json.dumps({"questions": qs})

        return json.dumps({"questions": []})

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate), \
         patch.object(svc.ai_service, "count_tokens", return_value=500):
        questions = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Fallback context",
            topic_focus=None,
            difficulty=DifficultyLevel.EASY,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
            chapter_weightages_data=chapter_weights,
        )

    # 2 initial batch calls + 2 recovery batch calls = 4 calls total
    assert len(captured_prompts) == 4

    # Recovery call 1 (index 2): exactly 100 missing slots requested, scoped to Ch 1
    rec_1_prompt = captured_prompts[2][0]
    assert "Generate 100 unique" in rec_1_prompt
    assert "[Digest for Chapter 1]" in rec_1_prompt
    assert "[Digest for Chapter 2]" not in rec_1_prompt

    # Recovery call 2 (index 3): 20 missing slots requested, scoped to Ch 2
    rec_2_prompt = captured_prompts[3][0]
    assert "Generate 20 unique" in rec_2_prompt
    assert "[Digest for Chapter 2]" in rec_2_prompt
    assert "[Digest for Chapter 1]" not in rec_2_prompt

    # All 120 slots filled
    assert len(questions) == 120


def test_recovery_max_attempts_is_five():
    """
    Test that unified recovery retries up to 5 attempts when candidates fail/reject.
    """
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.SHORT_ANSWER,
        question_count=1,
        marks_per_question=5,
        total_section_marks=5,
        has_internal_choice=False,
        alternatives_per_question=1,
    )
    bp = PaperBlueprint(total_marks=5, sections=[sec])

    recovery_calls = []

    def mock_generate(prompt, system_instruction=None, **kwargs):
        if "RECOVERY" in str(system_instruction or "") or "missing slot" in prompt:
            recovery_calls.append(prompt)
            # Return empty questions so recovery fails each attempt
            return json.dumps({"questions": []})
        return json.dumps({"sections": []})

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate), \
         patch.object(svc.ai_service, "count_tokens", return_value=500):
        questions = svc._generate_complete_paper(
            blueprint=bp,
            context_text="Context",
            topic_focus=None,
            difficulty=DifficultyLevel.EASY,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=None,
        )

    # Exactly 5 recovery attempts were made before falling back to deterministic question
    assert len(recovery_calls) == 5
    assert len(questions) == 1
    assert questions[0]["source_type"] == "AI_GENERATED"
    assert "concept" in questions[0]["question_text"]

