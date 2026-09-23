import json
import pytest
from unittest.mock import MagicMock

from app.schemas.paper import QuestionType
from app.services.ai.gemini_service import GeminiService
from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint


def test_normal_question_with_passage_null():
    """1. Normal question with passage = null."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 10,
        "sections": [
            {
                "name": "SECTION A",
                "question_type": "MCQ",
                "question_count": 1,
                "marks_per_question": 1,
            }
        ],
        "sample_questions": [
            {
                "section_name": "SECTION A",
                "question_type": "MCQ",
                "passage": None,
                "question_text": "What is the capital of France?",
                "mcq_options": ["(a) Paris", "(b) London", "(c) Rome", "(d) Berlin"],
                "marks": 1,
            }
        ],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample page text"],
        requested_total_marks=10,
    )

    assert len(bp.sample_questions) == 1
    sq = bp.sample_questions[0]
    assert sq["passage"] is None
    assert sq["question_text"] == "What is the capital of France?"
    assert sq["mcq_options"] == ["(a) Paris", "(b) London", "(c) Rome", "(d) Berlin"]


def test_passage_based_question():
    """2. Passage-based question with stimulus in passage and clean question_text."""
    stimulus = "He was the first psychologist who formalised the concept of intelligence."
    prompt_text = "Which psychologist has been referred in this passage? Also name the theory."

    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 4,
        "sections": [
            {
                "name": "SECTION E",
                "question_type": "SHORT_ANSWER",
                "question_count": 2,
                "marks_per_question": 2,
            }
        ],
        "sample_questions": [
            {
                "section_name": "SECTION E",
                "question_type": "SHORT_ANSWER",
                "passage": stimulus,
                "question_text": prompt_text,
                "mcq_options": None,
                "marks": 2,
            },
            {
                "section_name": "SECTION E",
                "question_type": "SHORT_ANSWER",
                "passage": stimulus,
                "question_text": "What is the significance about the title of his theory?",
                "mcq_options": None,
                "marks": 2,
            },
        ],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample page with passage and 2 sub-questions."],
        requested_total_marks=4,
    )

    assert len(bp.sample_questions) == 2
    for sq in bp.sample_questions:
        assert sq["passage"] == stimulus
        assert stimulus not in sq["question_text"]
    assert bp.sample_questions[0]["question_text"] == prompt_text


def test_two_questions_with_different_passages():
    """3. Two questions in a section with different passages (Case Study 1 vs Case Study 2)."""
    passage_1 = "Case Study 1: Patient A exhibits persistent elevated blood glucose levels..."
    passage_2 = "Case Study 2: Patient B presents with acute tachycardia and chest pain..."

    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 8,
        "sections": [
            {
                "name": "SECTION D",
                "question_type": "SHORT_ANSWER",
                "question_count": 2,
                "marks_per_question": 4,
            }
        ],
        "sample_questions": [
            {
                "section_name": "SECTION D",
                "question_type": "SHORT_ANSWER",
                "passage": passage_1,
                "question_text": "Identify the metabolic condition of Patient A and recommend initial therapy.",
                "mcq_options": None,
                "marks": 4,
            },
            {
                "section_name": "SECTION D",
                "question_type": "SHORT_ANSWER",
                "passage": passage_2,
                "question_text": "Describe the immediate emergency diagnostic procedure required for Patient B.",
                "mcq_options": None,
                "marks": 4,
            },
        ],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample clinical cases page text."],
        requested_total_marks=8,
    )

    assert len(bp.sample_questions) == 2
    assert bp.sample_questions[0]["passage"] == passage_1
    assert bp.sample_questions[1]["passage"] == passage_2
    assert bp.sample_questions[0]["passage"] != bp.sample_questions[1]["passage"]


def test_passage_not_duplicated_into_question_text():
    """4. Ensure passage text is not duplicated into question_text."""
    passage_text = "Photosynthesis occurs primarily in the chloroplasts of plant cells."
    question_stem = "Explain the light-dependent reactions."

    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 5,
        "sections": [
            {
                "name": "SECTION C",
                "question_type": "LONG_ANSWER",
                "question_count": 1,
                "marks_per_question": 5,
            }
        ],
        "sample_questions": [
            {
                "section_name": "SECTION C",
                "question_type": "LONG_ANSWER",
                "passage": passage_text,
                "question_text": question_stem,
                "mcq_options": None,
                "marks": 5,
            }
        ],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample biology paper"],
        requested_total_marks=5,
    )

    sq = bp.sample_questions[0]
    assert sq["passage"] == passage_text
    assert sq["question_text"] == question_stem
    # Assert strict non-overlap
    assert passage_text not in sq["question_text"]


def test_existing_blueprint_generation_still_works():
    """5. Ensure legacy blueprints without passage field are normalized safely with passage=None."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 20,
        "sections": [
            {
                "name": "Part A",
                "question_type": "SHORT_ANSWER",
                "question_count": 4,
                "marks_per_question": 5,
            }
        ],
        "sample_questions": [
            {
                "section_name": "Part A",
                "question_type": "SHORT_ANSWER",
                "question_text": "State Newton's third law of motion.",
                "marks": 5,
            }
        ],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample mechanics exam."],
        requested_total_marks=20,
    )

    assert bp.total_marks == 20
    assert len(bp.sample_questions) == 1
    # Missing passage in legacy output is safely set to None
    assert bp.sample_questions[0].get("passage") is None
    assert bp.sample_questions[0]["question_text"] == "State Newton's third law of motion."
