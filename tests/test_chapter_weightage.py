import uuid
import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from app.schemas.paper import (
    ChapterSelectionConfig,
    PaperGenerateRequest,
    GenerationMode,
    DifficultyLevel,
    QuestionType,
    QuestionConfigItem,
    PaperResponse,
)
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_unified_selected_chapters_with_weightage_success():
    """
    Verify unified selected_chapters with custom weightage percentages.
    """
    ch1 = uuid.uuid4()
    ch2 = uuid.uuid4()
    req = PaperGenerateRequest(
        book_id=uuid.uuid4(),
        selected_chapters=[
            ChapterSelectionConfig(chapter_id=ch1, weightage_percentage=30.0),
            ChapterSelectionConfig(chapter_id=ch2, weightage_percentage=70.0),
        ],
        generation_mode=GenerationMode.CUSTOM,
        total_marks=20,
        difficulty=DifficultyLevel.MIXED,
        question_configs=[
            QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=10, marks_per_question=2)
        ],
    )
    assert req.selected_chapters is not None
    assert len(req.selected_chapters) == 2
    assert req.selected_chapters[0].weightage_percentage == 30.0
    assert req.selected_chapters[1].weightage_percentage == 70.0


def test_unified_selected_chapters_without_weightages_auto_equal():
    """
    Verify unified selected_chapters without weightages defaults to None percentages.
    """
    ch1 = uuid.uuid4()
    ch2 = uuid.uuid4()
    req = PaperGenerateRequest(
        book_id=uuid.uuid4(),
        selected_chapters=[
            ChapterSelectionConfig(chapter_id=ch1),
            ChapterSelectionConfig(chapter_id=ch2),
        ],
        generation_mode=GenerationMode.CUSTOM,
        total_marks=20,
        difficulty=DifficultyLevel.MIXED,
        question_configs=[
            QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=10, marks_per_question=2)
        ],
    )
    assert len(req.selected_chapters) == 2
    assert req.selected_chapters[0].weightage_percentage is None
    assert req.selected_chapters[1].weightage_percentage is None


def test_unified_selected_chapters_duplicate_rejection():
    """
    Verify duplicate chapter_id rejection in selected_chapters.
    """
    ch1 = uuid.uuid4()
    with pytest.raises(ValidationError) as exc_info:
        PaperGenerateRequest(
            book_id=uuid.uuid4(),
            selected_chapters=[
                ChapterSelectionConfig(chapter_id=ch1, weightage_percentage=50.0),
                ChapterSelectionConfig(chapter_id=ch1, weightage_percentage=50.0),
            ],
            generation_mode=GenerationMode.CUSTOM,
            total_marks=20,
            difficulty=DifficultyLevel.MIXED,
            question_configs=[
                QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=10, marks_per_question=2)
            ],
        )
    assert "Duplicate chapter_id" in str(exc_info.value)


def test_unified_selected_chapters_sum_mismatch():
    """
    Verify rejection when chapter weightage percentages in selected_chapters do not sum to 100%.
    """
    ch1 = uuid.uuid4()
    ch2 = uuid.uuid4()
    with pytest.raises(ValidationError) as exc_info:
        PaperGenerateRequest(
            book_id=uuid.uuid4(),
            selected_chapters=[
                ChapterSelectionConfig(chapter_id=ch1, weightage_percentage=30.0),
                ChapterSelectionConfig(chapter_id=ch2, weightage_percentage=50.0),
            ],
            generation_mode=GenerationMode.CUSTOM,
            total_marks=20,
            difficulty=DifficultyLevel.MIXED,
            question_configs=[
                QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=10, marks_per_question=2)
            ],
        )
    assert "must sum to 100%" in str(exc_info.value)


def test_prompt_contains_chapter_weightages_and_dual_cap():
    """
    Verify _build_complete_paper_prompt includes chapter weightage breakdown and dual-cap reference rules.
    """
    service = PaperGeneratorService(db=None)
    blueprint = PaperBlueprint(
        total_marks=100,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=20,
                marks_per_question=5,
                total_section_marks=100,
            )
        ]
    )

    ch1_id = str(uuid.uuid4())
    ch2_id = str(uuid.uuid4())
    chapter_weightages_data = [
        {
            "chapter_id": ch1_id,
            "chapter_number": 1,
            "chapter_name": "Electrostatics",
            "weightage_percentage": 10.0,
            "allocated_marks": 10,
        },
        {
            "chapter_id": ch2_id,
            "chapter_number": 2,
            "chapter_name": "Current Electricity",
            "weightage_percentage": 90.0,
            "allocated_marks": 90,
        },
    ]

    sample_questions = [
        {"question_text": "Sample Q1 from Ref", "marks": 5, "source_type": "REFERENCE_REUSED"}
    ]

    prompt = service._build_complete_paper_prompt(
        blueprint=blueprint,
        context_text="Source context for chapters 1 and 2.",
        topic_focus="Calculations",
        difficulty=DifficultyLevel.MIXED,
        generation_mode=GenerationMode.REFERENCE,
        sample_questions=sample_questions,
        chapter_weightages_data=chapter_weightages_data,
    )

    assert "CHAPTER WEIGHTAGE & MARKS ALLOCATION BREAKDOWN:" in prompt
    assert "Chapter 1: \"Electrostatics\" -> 10.0% weightage (~10 marks allocated)" in prompt
    assert "Chapter 2: \"Current Electricity\" -> 90.0% weightage (~90 marks allocated)" in prompt
    assert "DUAL-CAP REUSE CONSTRAINTS:" in prompt
    assert "Per-Chapter Weightage Cap" in prompt
    assert "BALANCED 50/50 SPLIT PREFERENCE" in prompt


def test_dual_cap_reference_reuse_in_memory_enforcement():
    """
    Verify that in REFERENCE mode, candidate questions marked as REFERENCE_REUSED
    are capped both by the overall 20% limit AND by the chapter's allocated weightage marks.
    """
    service = PaperGeneratorService(db=None)
    service.ai_service = MagicMock()
    service.ai_service.count_tokens.return_value = 500

    blueprint = PaperBlueprint(
        total_marks=100,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=20,
                marks_per_question=5,
                total_section_marks=100,
            )
        ]
    )

    ch1_id = str(uuid.uuid4())
    ch2_id = str(uuid.uuid4())
    chapter_weightages_data = [
        {
            "chapter_id": ch1_id,
            "chapter_number": 1,
            "chapter_name": "Electrostatics",
            "weightage_percentage": 10.0,
            "allocated_marks": 10,
        },
        {
            "chapter_id": ch2_id,
            "chapter_number": 2,
            "chapter_name": "Current Electricity",
            "weightage_percentage": 90.0,
            "allocated_marks": 90,
        },
    ]

    mock_questions = []
    ch1_topics = [
        "State and explain Coulomb's inverse square law in electrostatics.",
        "Define electric field intensity due to a point charge at distance r.",
        "Derive an expression for electric potential on the axial line of a dipole.",
        "State Gauss's theorem and apply it to an infinitely long charged wire."
    ]
    for i, topic in enumerate(ch1_topics, 1):
        mock_questions.append({
            "question_text": topic,
            "question_type": "SHORT_ANSWER",
            "marks": 5,
            "difficulty": "MEDIUM",
            "chapter_number": 1,
            "source_type": "REFERENCE_REUSED",
            "correct_answer": f"Answer {i}",
            "expected_answer": f"Expected answer for {topic}",
            "solution_explanation": f"Step by step explanation for {topic}",
            "visual": None
        })

    ch2_topics = [
        "Define electric current and derive relation between current and drift velocity.",
        "State Ohm's law and write its microscopic vector form.",
        "What is electrical resistivity? Explain its temperature dependence in metals.",
        "Explain the principle and working of a Wheatstone bridge circuit.",
        "State Kirchhoff's first rule (junction rule) with an illustrative diagram.",
        "State Kirchhoff's second rule (loop rule) based on energy conservation.",
        "Derive equivalent emf and internal resistance for two cells connected in parallel.",
        "Derive condition for maximum power transfer from a battery to external load.",
        "Explain internal resistance of a cell and factors on which it depends.",
        "Define electromotive force (emf) and differentiate it from terminal potential difference.",
        "Describe how a potentiometer can be used to compare emfs of two primary cells.",
        "Explain the color code system used for carbon resistors with an example.",
        "Derive the heating effect of electric current (Joule's heating law).",
        "Calculate electrical energy consumed by a device rated 1000 W operated for 5 hours.",
        "Explain why copper wires are preferred for connecting leads in electrical circuits.",
        "Discuss electrical conductivity in electrolytes compared to metallic conductors."
    ]
    for i, topic in enumerate(ch2_topics, 5):
        mock_questions.append({
            "question_text": topic,
            "question_type": "SHORT_ANSWER",
            "marks": 5,
            "difficulty": "MEDIUM",
            "chapter_number": 2,
            "source_type": "AI_GENERATED",
            "correct_answer": f"Answer {i}",
            "expected_answer": f"Expected answer for {topic}",
            "solution_explanation": f"Step by step explanation for {topic}",
            "visual": None
        })

    mock_gemini_json = {
        "sections": [
            {
                "section_name": "Section A",
                "questions": mock_questions,
            }
        ]
    }

    import json
    service.ai_service.generate_response.return_value = json.dumps(mock_gemini_json)

    sample_questions = [
        {"question_text": "Sample Reference Q", "marks": 5}
    ]

    questions = service._generate_complete_paper(
        blueprint=blueprint,
        context_text="Context text",
        topic_focus=None,
        difficulty=DifficultyLevel.MIXED,
        generation_mode=GenerationMode.REFERENCE,
        sample_questions=sample_questions,
        chapter_weightages_data=chapter_weightages_data,
    )

    assert len(questions) == 20
    ch1_reused = [q for q in questions if q.get("chapter_id") == ch1_id and q.get("source_type") == "REFERENCE_REUSED"]
    ch1_reused_marks = sum(q.get("marks", 5) for q in ch1_reused)

    assert ch1_reused_marks <= 10, f"Chapter 1 reused marks ({ch1_reused_marks}) exceeded its allocated weightage of 10 marks!"
