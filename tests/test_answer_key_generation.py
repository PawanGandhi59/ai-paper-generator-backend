from unittest.mock import MagicMock, patch
import uuid
from uuid import uuid4
import pytest
from fastapi import UploadFile

from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.schemas.paper import (
    AnswerKeyItemSchema,
    AnswerKeySchema,
    AnswerKeySectionSchema,
    AnswerKeyUpdateRequest,
)
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_answer_key_schema_validation():
    sample_ak = {
        "total_marks": 50,
        "sections": [
            {
                "section_name": "Section A",
                "answers": [
                    {
                        "question_order": 1,
                        "choice_group": None,
                        "alternative_label": None,
                        "question_type": "MCQ",
                        "marks": 1,
                        "correct_answer": "B. Mitochondria",
                        "explanation": "Mitochondria are the powerhouse of the cell and produce ATP via cellular respiration.",
                    },
                    {
                        "question_order": 2,
                        "choice_group": None,
                        "alternative_label": None,
                        "question_type": "VERY_SHORT_ANSWER",
                        "marks": 1,
                        "correct_answer": "Chlorophyll",
                        "explanation": "Chlorophyll is a green pigment that traps sunlight for photosynthesis.",
                    },
                    {
                        "question_order": 3,
                        "choice_group": "Q3",
                        "alternative_label": "a",
                        "question_type": "SHORT_ANSWER",
                        "marks": 2,
                        "correct_answer": "V = I * R",
                        "explanation": "Ohm's Law states that current is directly proportional to potential difference across a conductor at constant temperature.",
                    },
                    {
                        "question_order": 4,
                        "choice_group": None,
                        "alternative_label": None,
                        "question_type": "NUMERICAL",
                        "marks": 3,
                        "correct_answer": "4.5 m/s²",
                        "explanation": "Formula: a = (v - u)/t. Given u = 0, v = 18 m/s, t = 4 s. Substitution: a = (18 - 0)/4 = 4.5 m/s².",
                    },
                ],
            }
        ],
    }

    schema = AnswerKeySchema(**sample_ak)
    assert schema.total_marks == 50
    assert len(schema.sections) == 1
    sec = schema.sections[0]
    assert sec.section_name == "Section A"
    assert len(sec.answers) == 4
    assert sec.answers[0].correct_answer == "B. Mitochondria"
    assert "Mitochondria are the powerhouse" in sec.answers[0].explanation
    assert sec.answers[1].question_type == "VERY_SHORT_ANSWER"
    assert sec.answers[3].correct_answer == "4.5 m/s²"
    assert "a = (v - u)/t" in sec.answers[3].explanation


def test_generate_answer_key_success():
    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = uuid4()
    paper.class_name = "Class 10"
    paper.total_marks = 10

    questions = [
        {
            "question_order": 1,
            "section_name": "Section A",
            "question_type": "MCQ",
            "marks": 1,
            "choice_group": None,
            "alternative_label": None,
            "question_text": "Which organelle produces ATP?",
            "mcq_options": ["Ribosome", "Mitochondria", "Nucleus", "Vacuole"],
        }
    ]

    mock_llm_response = """{
        "total_marks": 10,
        "sections": [
            {
                "section_name": "Section A",
                "answers": [
                    {
                        "question_order": 1,
                        "choice_group": null,
                        "alternative_label": null,
                        "question_type": "MCQ",
                        "marks": 1,
                        "correct_answer": "B. Mitochondria",
                        "explanation": "Mitochondria produce ATP via oxidative phosphorylation."
                    }
                ]
            }
        ]
    }"""

    service.ai_service = MagicMock()
    service.ai_service.generate_response.return_value = mock_llm_response

    result = service._generate_answer_key(
        paper=paper,
        blueprint=None,
        generated_questions=questions,
        context_text="Cell biology summary context",
        class_name="Class 10",
        subject_name="Biology",
    )

    assert result is not None
    assert result["total_marks"] == 10
    assert len(result["sections"]) == 1
    assert result["sections"][0]["answers"][0]["correct_answer"] == "B. Mitochondria"
    assert "Mitochondria produce ATP" in result["sections"][0]["answers"][0]["explanation"]


def test_generate_answer_key_graceful_failure():
    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = uuid4()
    paper.class_name = "Class 10"

    questions = [{"question_order": 1, "section_name": "Section A", "question_type": "MCQ", "marks": 1}]

    service.ai_service = MagicMock()
    service.ai_service.generate_response.side_effect = RuntimeError("Gemini API rate limit exceeded")

    # Graceful degradation: must not crash, must return None
    result = service._generate_answer_key(
        paper=paper,
        blueprint=None,
        generated_questions=questions,
        context_text="Sample context",
        class_name="Class 10",
        subject_name="Biology",
    )
    assert result is None


def test_build_paper_response_includes_answer_key():
    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = uuid4()
    paper.workspace_id = uuid4()
    paper.subject_id = uuid4()
    paper.book_id = uuid4()
    paper.reference_paper_id = None
    paper.title = "Sample Paper"
    paper.generation_mode = "CUSTOM"
    paper.status = "COMPLETED"
    paper.total_marks = 50
    paper.time_allowed_minutes = 60
    paper.class_name = "Class 10"
    paper.easy_percentage = 30
    paper.medium_percentage = 40
    paper.hard_percentage = 30
    paper.selected_chapter_ids = []
    paper.chapter_weightages = []
    paper.blueprint_json = None
    paper.error_message = None
    paper.pdf_path = None
    paper.document_id = None
    paper.processing_status = "NOT_SAVED"
    paper.deleted_at = None
    paper.questions = []
    paper.created_at = None
    paper.updated_at = None
    paper.include_answers = True
    paper.answer_key_json = {
        "total_marks": 50,
        "sections": [
            {
                "section_name": "Section A",
                "answers": [
                    {
                        "question_order": 1,
                        "question_type": "MCQ",
                        "marks": 1,
                        "correct_answer": "A. Correct option",
                        "explanation": "Option A is correct according to basic principles.",
                    }
                ],
            }
        ],
    }

    # When include_answers is True
    resp = service._build_paper_response(paper, include_answers=True)
    assert resp.answer_key is not None
    assert resp.answer_key.total_marks == 50
    assert resp.answer_key.sections[0].answers[0].correct_answer == "A. Correct option"


    # When include_answers is False, answer_key must be stripped
    resp_no_answers = service._build_paper_response(paper, include_answers=False)
    assert resp_no_answers.answer_key is None


def test_update_answer_key():
    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    paper_id = uuid4()
    user_id = uuid4()

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = paper_id
    paper.workspace_id = uuid4()
    paper.subject_id = uuid4()
    paper.book_id = uuid4()
    paper.reference_paper_id = None
    paper.title = "Sample Paper"
    paper.generation_mode = "CUSTOM"
    paper.status = "COMPLETED"
    paper.total_marks = 50
    paper.time_allowed_minutes = 60
    paper.class_name = "Class 10"
    paper.easy_percentage = 30
    paper.medium_percentage = 40
    paper.hard_percentage = 30
    paper.selected_chapter_ids = []
    paper.chapter_weightages = []
    paper.blueprint_json = None
    paper.error_message = None
    paper.pdf_path = None
    paper.document_id = None
    paper.processing_status = "NOT_SAVED"
    paper.deleted_at = None
    paper.questions = []
    paper.created_at = None
    paper.updated_at = None
    paper.include_answers = True

    service.paper_repo = MagicMock()
    service.workspace_service = MagicMock()
    service.paper_repo.get_paper.return_value = paper
    service.workspace_service.get_subject.return_value = MagicMock()

    updated_ak = {
        "total_marks": 50,
        "sections": [
            {
                "section_name": "Section A",
                "answers": [
                    {
                        "question_order": 1,
                        "question_type": "MCQ",
                        "marks": 1,
                        "correct_answer": "C. Updated option",
                        "explanation": "Updated explanation statement.",
                    }
                ],
            }
        ],
    }

    paper.answer_key_json = updated_ak
    service.paper_repo.update_answer_key.return_value = paper

    resp = service.update_answer_key(
        paper_id=paper_id,
        current_user_id=user_id,
        answer_key=updated_ak,
    )

    service.paper_repo.update_answer_key.assert_called_once_with(
        paper_id=paper_id,
        answer_key_json=updated_ak,
    )
    assert resp.answer_key is not None
    assert resp.answer_key.sections[0].answers[0].correct_answer == "C. Updated option"
    assert resp.answer_key.sections[0].answers[0].explanation == "Updated explanation statement."



def test_authoritative_marks_synchronization():
    """
    Test Fix 1: LLM hallucinates total_marks: 36 and Q14 marks: 1.
    Backend must authoritatively overwrite Q14 marks to 2 and total_marks to 30.
    """
    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    paper = MagicMock(spec=GeneratedPaper)
    paper.id = uuid4()
    paper.class_name = "Class 12"
    paper.total_marks = 30

    questions = [
        {
            "question_order": 13,
            "section_name": "Section C",
            "question_type": "SHORT_ANSWER",
            "marks": 2,
            "choice_group": None,
            "alternative_label": None,
            "question_text": "Define drift velocity.",
        },
        {
            "question_order": 14,
            "section_name": "Section C",
            "question_type": "SHORT_ANSWER",
            "marks": 2,  # Authoritative marks is 2
            "choice_group": None,
            "alternative_label": None,
            "question_text": "State Kirchhoff's junction rule.",
        },
    ]

    # LLM hallucinates total_marks: 36 and marks: 1 for Q14
    mock_llm_response = """{
        "total_marks": 36,
        "sections": [
            {
                "section_name": "Section C",
                "answers": [
                    {
                        "question_order": 13,
                        "choice_group": null,
                        "alternative_label": null,
                        "question_type": "SHORT_ANSWER",
                        "marks": 2,
                        "correct_answer": "Drift velocity is the average velocity acquired by electrons under an electric field.",
                        "explanation": "Free electrons undergo repeated scattering with positive metal ions. An external electric field exerts force causing net average motion opposite to field direction."
                    },
                    {
                        "question_order": 14,
                        "choice_group": null,
                        "alternative_label": null,
                        "question_type": "SHORT_ANSWER",
                        "marks": 1,
                        "correct_answer": "Sum of entering currents equals sum of leaving currents.",
                        "explanation": "Founded on conservation of electric charge: charge cannot accumulate at an ideal circuit junction."
                    }
                ]
            }
        ]
    }"""

    service.ai_service = MagicMock()
    service.ai_service.generate_response.return_value = mock_llm_response

    result = service._generate_answer_key(
        paper=paper,
        blueprint=None,
        generated_questions=questions,
        context_text="Physics summary context",
        class_name="Class 12",
        subject_name="Physics",
    )

    assert result is not None
    # Must be synced to authoritative paper total_marks (30)
    assert result["total_marks"] == 30
    ans_14 = result["sections"][0]["answers"][1]
    assert ans_14["question_order"] == 14
    # Must be synced to authoritative question marks (2, not 1)
    assert ans_14["marks"] == 2


def test_preplan_blueprint_matrix_syllabus_order():
    """
    Test Fix 2: Question slots should be planned progressing in syllabus sequence.
    """
    from app.schemas.paper import QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint

    mock_db = MagicMock()
    service = PaperGeneratorService(mock_db)

    sections = [
        SectionBlueprint(
            name="Section A",
            question_type=QuestionType.MCQ,
            question_count=2,
            marks_per_question=1,
            total_section_marks=2,
            has_internal_choice=False,
            alternatives_per_question=1,
            choice_rule="ALL",
            numerical_question_count=0,
        ),
        SectionBlueprint(
            name="Section B",
            question_type=QuestionType.SHORT_ANSWER,
            question_count=2,
            marks_per_question=2,
            total_section_marks=4,
            has_internal_choice=False,
            alternatives_per_question=1,
            choice_rule="ALL",
            numerical_question_count=0,
        ),
    ]
    blueprint = PaperBlueprint(total_marks=6, sections=sections, sample_questions=[])

    chapter_weightages = [
        {"chapter_id": "ch1", "chapter_number": 1, "chapter_name": "Chapter 1", "allocated_marks": 3},
        {"chapter_id": "ch2", "chapter_number": 2, "chapter_name": "Chapter 2", "allocated_marks": 3},
    ]

    planned = service.preplan_blueprint_matrix(
        blueprint=blueprint,
        chapter_weightages_data=chapter_weightages,
    )

    sec_a_groups = planned[0]["groups"]
    # Q1 should start with Chapter 1 in syllabus order
    assert sec_a_groups[0]["question_order"] == 1
    assert sec_a_groups[0]["chapter_number"] == 1


