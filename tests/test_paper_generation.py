import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion

client = TestClient(app)


def test_custom_mode_paper_generation_success():
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Paper Author", "email": f"author_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"OS_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"OS Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "CPU Scheduling", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 50,
        "difficulty": "MIXED",
        "topic_focus": "Generate questions mainly from CPU Scheduling, FCFS and Round Robin.",
        "include_answers": True,
        "title": "Operating Systems Midterm 2026",
        "question_configs": [
            {"question_type": "MCQ", "question_count": 5, "marks_per_question": 1, "section_name": "Section A"},
            {"question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 2, "section_name": "Section B"},
            {"question_type": "LONG_ANSWER", "question_count": 4, "marks_per_question": 5, "section_name": "Section C"},
            {"question_type": "NUMERICAL", "question_count": 3, "marks_per_question": 5, "section_name": "Section D"},
        ],
    }

    # Mock RAG retrieval and AI service response for test execution
    with patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()

    assert paper_data["title"] == "Operating Systems Midterm 2026"
    assert paper_data["generation_mode"] == "CUSTOM"
    assert paper_data["status"] == "COMPLETED"
    assert paper_data["total_marks"] == 50
    assert paper_data["difficulty"] == "MIXED"
    assert len(paper_data["questions"]) == 17
    assert paper_data["include_answers"] is True

    # Verify section breakdown and questions
    sections = [q["section_name"] for q in paper_data["questions"]]
    assert sections.count("Section A") == 5
    assert sections.count("Section B") == 5
    assert sections.count("Section C") == 4
    assert sections.count("Section D") == 3

    # Check answers present when include_answers=True
    mcq_q = next(q for q in paper_data["questions"] if q["question_type"] == "MCQ")
    assert mcq_q["mcq_options"] is not None
    assert mcq_q["correct_answer"] is not None


def test_custom_mode_validation_rejections():
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Tester", "email": f"test_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    # 1. Configured total (45) does not equal paper total_marks (50) -> 422 Unprocessable Entity
    invalid_sum = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 50,
        "question_configs": [
            {"question_type": "MCQ", "question_count": 5, "marks_per_question": 1},  # 5
            {"question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 2},  # 10
            {"question_type": "LONG_ANSWER", "question_count": 3, "marks_per_question": 5},  # 15
            {"question_type": "NUMERICAL", "question_count": 3, "marks_per_question": 5},  # 15 -> sum 45 != 50
        ],
    }
    res1 = client.post("/api/v1/papers/generate", json=invalid_sum, headers=headers)
    assert res1.status_code == 422

    # 2. Zero question_count -> 422
    zero_count = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 10,
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 0, "marks_per_question": 2},
        ],
    }
    res2 = client.post("/api/v1/papers/generate", json=zero_count, headers=headers)
    assert res2.status_code == 422

    # 3. Reference paper ID provided in CUSTOM mode -> 422
    ref_in_custom = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 10,
        "reference_paper_id": str(uuid4()),
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 2},
        ],
    }
    res3 = client.post("/api/v1/papers/generate", json=ref_in_custom, headers=headers)
    assert res3.status_code == 422


def test_answer_visibility_stripping():
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Teacher User", "email": f"teach_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 10,
        "include_answers": False,  # Hide answers in API response!
        "question_configs": [
            {"question_type": "MCQ", "question_count": 2, "marks_per_question": 1},
            {"question_type": "SHORT_ANSWER", "question_count": 4, "marks_per_question": 2},
        ],
    }

    with patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()
    assert paper_data["include_answers"] is False

    # Verify answer keys stripped in API response while MCQ options are retained for students
    for q in paper_data["questions"]:
        assert q["correct_answer"] is None
        assert q["expected_answer"] is None
        assert q["solution_explanation"] is None
        if q["question_type"] == "MCQ":
            assert q["mcq_options"] is not None

    # Verify answer key values are preserved in the DB model!
    paper_id = paper_data["id"]
    db = SessionLocal()
    try:
        db_questions = db.query(GeneratedPaperQuestion).filter(GeneratedPaperQuestion.paper_id == paper_id).all()
        assert len(db_questions) == 6
        mcq_db_q = next(q for q in db_questions if q.question_type == "MCQ")
        assert mcq_db_q.correct_answer is not None
        assert mcq_db_q.mcq_options is not None
    finally:
        db.close()

    # GET paper endpoint also honors include_answers=False
    get_res = client.get(f"/api/v1/papers/{paper_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["questions"][0]["correct_answer"] is None


def test_reference_mode_paper_generation_and_adaptation():
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Ref Mode User", "email": f"ref_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"DS_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"DS Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Trees & Graphs", "chapter_number": 1}, headers=headers).json()

    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Data Structures Reference Paper 2024 Exam Question 1")
    pdf_bytes = doc.tobytes()
    doc.close()

    ref_paper_res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "DS Exam 2024 (80 Marks)", "year": "2024", "exam_type": "FINAL"},
        files={"file": ("exam.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert ref_paper_res.status_code == 201
    ref_paper = ref_paper_res.json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 50,  # Requesting 50 marks adaptation from 80 marks reference
        "difficulty": "MIXED",
    }

    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
    mock_bp = PaperBlueprint(
        total_marks=80,
        sections=[
            SectionBlueprint(name="Section A", question_type="MCQ", question_count=10, marks_per_question=1, total_section_marks=10),
            SectionBlueprint(name="Section B", question_type="SHORT_ANSWER", question_count=10, marks_per_question=2, total_section_marks=20),
            SectionBlueprint(name="Section C", question_type="LONG_ANSWER", question_count=10, marks_per_question=5, total_section_marks=50),
        ],
    )

    bp_service = BlueprintService()
    adapted_bp = bp_service.adapt_reference_blueprint(mock_bp, 50)

    with patch.object(BlueprintService, "analyze_reference_paper", return_value=adapted_bp), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201, f"Response status {res.status_code}: {res.json()}"
    paper_data = res.json()
    assert paper_data["generation_mode"] == "REFERENCE"
    assert paper_data["total_marks"] == 50
    assert len(paper_data["questions"]) > 0

    # Total marks of generated paper questions strictly equals 50
    computed_marks = sum(q["marks"] for q in paper_data["questions"])
    assert computed_marks == 50


def test_multi_tenant_security_and_ownership():
    uid_a = uuid4().hex[:8]
    uid_b = uuid4().hex[:8]

    user_a = client.post("/api/v1/auth/register", json={"name": "Owner A", "email": f"own_{uid_a}@example.com", "password": "password123"}).json()
    user_b = client.post("/api/v1/auth/register", json={"name": "Attacker B", "email": f"att_{uid_b}@example.com", "password": "password123"}).json()

    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    ws_a = client.post("/api/v1/workspaces", json={"name": f"WS_{uid_a}"}, headers=headers_a).json()
    subj_a = client.post(f"/api/v1/workspaces/{ws_a['id']}/subjects", json={"name": f"Subj_{uid_a}"}, headers=headers_a).json()
    book_a = client.post(f"/api/v1/subjects/{subj_a['id']}/books", json={"name": f"Book_{uid_a}"}, headers=headers_a).json()
    ch_a = client.post(f"/api/v1/books/{book_a['id']}/chapters", json={"name": "Ch A", "chapter_number": 1}, headers=headers_a).json()

    # User A generates a paper
    gen_payload = {
        "book_id": book_a["id"],
        "selected_chapter_ids": [ch_a["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 10,
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 2},
        ],
    }

    with patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        paper_res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers_a).json()

    paper_id = paper_res["id"]

    # 1. User B attempts to access User A's generated paper -> 404 Not Found
    unauth_get = client.get(f"/api/v1/papers/{paper_id}", headers=headers_b)
    assert unauth_get.status_code == 404

    # 2. User B attempts to generate a paper using User A's book -> 404 Not Found
    unauth_gen = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers_b)
    assert unauth_gen.status_code == 404


def test_custom_mode_forces_ai_generated_source_type():
    """
    Regression Test: In CUSTOM mode, even if Gemini returns REFERENCE_REUSED or REFERENCE_VARIATION,
    the backend MUST override source_type to AI_GENERATED.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Source Type Tester", "email": f"st_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 10,
        "question_configs": [
            {"question_type": "MCQ", "question_count": 2, "marks_per_question": 1},
            {"question_type": "SHORT_ANSWER", "question_count": 4, "marks_per_question": 2},
        ],
    }

    # Simulate Gemini returning REFERENCE_REUSED and REFERENCE_VARIATION in CUSTOM mode
    fake_gemini_mcq_response = """
    {
      "questions": [
        {
          "question_text": "Sample MCQ Question 1?",
          "mcq_options": ["A. Opt 1", "B. Opt 2", "C. Opt 3", "D. Opt 4"],
          "correct_answer": "A. Opt 1",
          "solution_explanation": "Exp 1",
          "source_type": "REFERENCE_REUSED"
        },
        {
          "question_text": "Sample MCQ Question 2?",
          "mcq_options": ["A. Opt 1", "B. Opt 2", "C. Opt 3", "D. Opt 4"],
          "correct_answer": "B. Opt 2",
          "solution_explanation": "Exp 2",
          "source_type": "REFERENCE_VARIATION"
        }
      ]
    }
    """

    fake_gemini_short_response = """
    {
      "questions": [
        {
          "question_text": "Short Question 1?",
          "expected_answer": "Answer 1",
          "solution_explanation": "Exp 1",
          "source_type": "REFERENCE_REUSED"
        },
        {
          "question_text": "Short Question 2?",
          "expected_answer": "Answer 2",
          "solution_explanation": "Exp 2",
          "source_type": "REFERENCE_VARIATION"
        },
        {
          "question_text": "Short Question 3?",
          "expected_answer": "Answer 3",
          "solution_explanation": "Exp 3",
          "source_type": "AI_GENERATED"
        },
        {
          "question_text": "Short Question 4?",
          "expected_answer": "Answer 4",
          "solution_explanation": "Exp 4",
          "source_type": "REFERENCE_REUSED"
        }
      ]
    }
    """

    def mock_generate_response(prompt: str) -> str:
        if "MCQ" in prompt:
            return fake_gemini_mcq_response
        return fake_gemini_short_response

    with patch("app.services.paper.paper_generator_service.GeminiService.generate_response", side_effect=mock_generate_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()

    # Verify EVERY question in API response has source_type == "AI_GENERATED"
    for q in paper_data["questions"]:
        assert q["source_type"] == "AI_GENERATED", f"Question {q['id']} had source_type {q['source_type']}"

    # Verify EVERY question in Database model has source_type == "AI_GENERATED"
    paper_id = paper_data["id"]
    db = SessionLocal()
    try:
        db_questions = db.query(GeneratedPaperQuestion).filter(GeneratedPaperQuestion.paper_id == paper_id).all()
        assert len(db_questions) == 6
        for db_q in db_questions:
            assert db_q.source_type == "AI_GENERATED", f"DB Question {db_q.id} had source_type {db_q.source_type}"
    finally:
        db.close()


def test_prompt_construction_mode_awareness():
    """
    Regression Test: Verify that _build_generation_prompt creates mode-aware schema instructions.
    - CUSTOM mode prompt must require source_type = "AI_GENERATED" and not advertise reference types.
    - REFERENCE mode prompt must retain reference source types.
    """
    from app.schemas.paper import GenerationMode, QuestionType
    from app.services.paper.blueprint_service import SectionBlueprint
    from app.services.paper.paper_generator_service import PaperGeneratorService

    svc = PaperGeneratorService(db=None)
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=5,
        marks_per_question=1,
        total_section_marks=5,
    )

    # 1. Custom mode prompt
    custom_prompt = svc._build_generation_prompt(
        sec=sec,
        needed_count=5,
        difficulties=["EASY"] * 5,
        context_text="Sample Context",
        topic_focus=None,
        generation_mode=GenerationMode.CUSTOM,
        section_ref_questions=[],
    )

    assert '- "source_type": "AI_GENERATED"' in custom_prompt
    assert "REFERENCE_REUSED" not in custom_prompt
    assert "REFERENCE_VARIATION" not in custom_prompt

    # 2. Reference mode prompt with matching section_ref_questions
    ref_prompt = svc._build_generation_prompt(
        sec=sec,
        needed_count=5,
        difficulties=["EASY"] * 5,
        context_text="Sample Context",
        topic_focus=None,
        generation_mode=GenerationMode.REFERENCE,
        section_ref_questions=[{"section_name": "Section A", "question_type": "MCQ", "question_text": "Q1"}],
    )

    assert '- "source_type": "<AI_GENERATED | REFERENCE_REUSED | REFERENCE_VARIATION>"' in ref_prompt


def test_custom_mode_isolation_from_reference_paper():
    """
    Verify CUSTOM mode generation with reference_paper_id = null does not query ReferencePaper repository.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Isolation Tester", "email": f"iso_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 5,
        "question_configs": [
            {"question_type": "MCQ", "question_count": 5, "marks_per_question": 1},
        ],
    }

    with patch("app.repositories.reference_paper_repository.ReferencePaperRepository.get_reference_paper") as mock_get_ref, \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    mock_get_ref.assert_not_called()


def test_section_aligned_sample_question_selection():
    """
    Test section-aligned reference question matching logic:
    - MCQ section receives only MCQ reference questions.
    - SHORT_ANSWER section receives only SHORT_ANSWER reference questions.
    - LONG_ANSWER section receives only LONG_ANSWER reference questions.
    - Section with no matching question_type receives empty list.
    """
    from app.schemas.paper import QuestionType
    from app.services.paper.blueprint_service import SectionBlueprint
    from app.services.paper.paper_generator_service import PaperGeneratorService

    svc = PaperGeneratorService(db=None)

    sample_questions = [
        {"section_name": "Section A", "question_type": "MCQ", "question_text": "MCQ Ref Q1", "marks": 1},
        {"section_name": "Section A", "question_type": "MCQ", "question_text": "MCQ Ref Q2", "marks": 1},
        {"section_name": "Section B", "question_type": "SHORT_ANSWER", "question_text": "Short Ref Q1", "marks": 2},
        {"section_name": "Section C", "question_type": "LONG_ANSWER", "question_text": "Long Ref Q1", "marks": 5},
    ]

    sec_mcq = SectionBlueprint(name="Section A", question_type=QuestionType.MCQ, question_count=2, marks_per_question=1, total_section_marks=2)
    sec_short = SectionBlueprint(name="Section B", question_type=QuestionType.SHORT_ANSWER, question_count=1, marks_per_question=2, total_section_marks=2)
    sec_long = SectionBlueprint(name="Section C", question_type=QuestionType.LONG_ANSWER, question_count=1, marks_per_question=5, total_section_marks=5)
    sec_num = SectionBlueprint(name="Section D", question_type=QuestionType.NUMERICAL, question_count=1, marks_per_question=5, total_section_marks=5)

    res_mcq = svc._get_section_aligned_sample_questions(sec_mcq, sample_questions)
    assert len(res_mcq) == 2
    assert all(q["question_type"] == "MCQ" for q in res_mcq)

    res_short = svc._get_section_aligned_sample_questions(sec_short, sample_questions)
    assert len(res_short) == 1
    assert res_short[0]["question_type"] == "SHORT_ANSWER"

    res_long = svc._get_section_aligned_sample_questions(sec_long, sample_questions)
    assert len(res_long) == 1
    assert res_long[0]["question_type"] == "LONG_ANSWER"

    res_num = svc._get_section_aligned_sample_questions(sec_num, sample_questions)
    assert len(res_num) == 0


def test_reference_mode_source_type_overrides_when_no_matching_ref_questions():
    """
    Test REFERENCE mode behavior when a section has no matching reference questions:
    - If no ref questions exist for a section and Gemini outputs REFERENCE_REUSED or REFERENCE_VARIATION,
      the backend MUST override source_type to AI_GENERATED.
    """
    from app.schemas.paper import GenerationMode, QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint

    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Ref Override Tester", "email": f"refo_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Reference Paper Content")
    pdf_bytes = doc.tobytes()
    doc.close()

    ref_paper_res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Ref Paper 1"},
        files={"file": ("exam.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    ref_paper = ref_paper_res.json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 5,
    }

    # Reference blueprint has only MCQ sample questions, but blueprint section is NUMERICAL
    mock_bp = PaperBlueprint(
        total_marks=5,
        sections=[
            SectionBlueprint(name="Section A", question_type=QuestionType.NUMERICAL, question_count=1, marks_per_question=5, total_section_marks=5),
        ],
        sample_questions=[
            {"section_name": "Section A", "question_type": "MCQ", "question_text": "MCQ Only", "marks": 1},
        ],
    )

    # Gemini attempts to return REFERENCE_REUSED for NUMERICAL section (which had 0 matching ref questions)
    fake_numerical_response = """
    {
      "questions": [
        {
          "question_text": "Numerical Problem 1?",
          "numerical_values": {"x": 1},
          "correct_answer": "5 ms",
          "solution_explanation": "Sol 1",
          "unit": "ms",
          "source_type": "REFERENCE_REUSED"
        }
      ]
    }
    """

    with patch("app.services.paper.blueprint_service.BlueprintService.analyze_reference_paper", return_value=mock_bp), \
         patch("app.services.paper.paper_generator_service.GeminiService.generate_response", return_value=fake_numerical_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()
    q = paper_data["questions"][0]

    # Because NUMERICAL section had 0 matching sample questions, backend forces AI_GENERATED!
    assert q["source_type"] == "AI_GENERATED"


def test_reference_mode_preserves_source_type_when_questions_exist():
    """
    Test REFERENCE mode behavior when matching reference questions DO exist:
    - If relevant reference questions are supplied and Gemini returns REFERENCE_REUSED or REFERENCE_VARIATION,
      the backend preserves the label.
    """
    from app.schemas.paper import QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint

    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Ref Preserver Tester", "email": f"refp_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Reference Paper Content")
    pdf_bytes = doc.tobytes()
    doc.close()

    ref_paper_res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Ref Paper 1"},
        files={"file": ("exam.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    ref_paper = ref_paper_res.json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 2,
    }

    mock_bp = PaperBlueprint(
        total_marks=2,
        sections=[
            SectionBlueprint(name="Section A", question_type=QuestionType.MCQ, question_count=2, marks_per_question=1, total_section_marks=2),
        ],
        sample_questions=[
            {"section_name": "Section A", "question_type": "MCQ", "question_text": "MCQ Ref Q1", "marks": 1},
            {"section_name": "Section A", "question_type": "MCQ", "question_text": "MCQ Ref Q2", "marks": 1},
        ],
    )

    fake_mcq_response = """
    {
      "questions": [
        {
          "question_text": "Reused MCQ 1?",
          "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"],
          "correct_answer": "A. 1",
          "solution_explanation": "Sol 1",
          "source_type": "REFERENCE_REUSED"
        },
        {
          "question_text": "Variation MCQ 2?",
          "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"],
          "correct_answer": "B. 2",
          "solution_explanation": "Sol 2",
          "source_type": "REFERENCE_VARIATION"
        }
      ]
    }
    """

    with patch("app.services.paper.blueprint_service.BlueprintService.analyze_reference_paper", return_value=mock_bp), \
         patch("app.services.paper.paper_generator_service.GeminiService.generate_response", return_value=fake_mcq_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()
    q1 = paper_data["questions"][0]
    q2 = paper_data["questions"][1]

    # Matching ref questions existed, so REFERENCE_REUSED and REFERENCE_VARIATION are preserved!
    assert q1["source_type"] == "REFERENCE_REUSED"
    assert q2["source_type"] == "REFERENCE_VARIATION"


def test_cross_subject_reference_mode_grounding_isolation():
    """
    Regression Test for Cross-Subject Grounding Isolation:
    Reference paper: Blockchain
    Selected book: Grade 1 English ("Papa's Spectacles")
    topic_focus: "blockchain applications"
    Expected: Zero blockchain terminology in generated questions. Questions must be about English source material.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Grounding Tester", "email": f"grounding_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Eng_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Grade 1 English", "subject_id": subj["id"]}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Papa's Spectacles", "chapter_number": 1}, headers=headers).json()

    # Create dummy reference paper
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Blockchain Exam Paper 2024 Smart Contracts & Proof of Work")
    pdf_bytes = doc.tobytes()
    doc.close()

    ref_paper_res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Blockchain Exam 2024", "year": "2024", "exam_type": "FINAL"},
        files={"file": ("blockchain.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert ref_paper_res.status_code == 201
    ref_paper = ref_paper_res.json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 4,
        "topic_focus": "blockchain applications",
    }

    from app.schemas.paper import QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
    mock_bp = PaperBlueprint(
        total_marks=4,
        sections=[
            SectionBlueprint(name="Section A", question_type=QuestionType.SHORT_ANSWER, question_count=2, marks_per_question=2, total_section_marks=4),
        ],
        sample_questions=[],
    )

    english_context = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "page_number": 1,
            "chapter_id": ch1["id"],
            "book_id": book["id"],
            "subject_id": subj["id"],
            "workspace_id": ws["id"],
            "content": "Papa is searching for his spectacles. He looks on the table and under the bed. Papa's spectacles are on his head.",
            "content_type": "TEXT",
            "distance": 0.1,
            "metadata": {},
        }
    ]

    fake_grounded_response = """
    {
      "questions": [
        {
          "question_text": "Where was Papa searching for his spectacles?",
          "expected_answer": "Papa was searching on the table and under the bed.",
          "solution_explanation": "Papa searched on the table and under the bed.",
          "source_type": "AI_GENERATED"
        },
        {
          "question_text": "Where were Papa's spectacles finally found?",
          "expected_answer": "Papa's spectacles were found on his head.",
          "solution_explanation": "The spectacles were sitting on his head.",
          "source_type": "AI_GENERATED"
        }
      ]
    }
    """

    with patch("app.services.paper.blueprint_service.BlueprintService.analyze_reference_paper", return_value=mock_bp), \
         patch("app.services.paper.paper_generator_service.GeminiService.generate_response", return_value=fake_grounded_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=english_context):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.json()}"
    paper_data = res.json()
    assert paper_data["generation_mode"] == "REFERENCE"
    assert len(paper_data["questions"]) == 2

    forbidden_terms = ["blockchain", "cryptography", "smart contract", "decentralization", "hyperledger"]
    for q in paper_data["questions"]:
        q_str = f"{q['question_text']} {q.get('expected_answer', '')}".lower()
        for term in forbidden_terms:
            assert term not in q_str, f"Forbidden term '{term}' found in question: {q_str}"


def test_topic_focus_absent_from_source_is_ignored():
    """
    Test that an absent topic_focus ('quantum computing') is ignored when source context is Grade 1 English.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Topic Focus Tester", "email": f"tf_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 2,
        "topic_focus": "quantum computing",
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 1, "marks_per_question": 2, "section_name": "Section A"},
        ],
    }

    english_context = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "page_number": 1,
            "chapter_id": ch1["id"],
            "book_id": book["id"],
            "subject_id": subj["id"],
            "workspace_id": ws["id"],
            "content": "Papa is searching for his spectacles on the table.",
            "content_type": "TEXT",
            "distance": 0.1,
            "metadata": {},
        }
    ]

    fake_english_response = """
    {
      "questions": [
        {
          "question_text": "Why is Papa searching for his spectacles on the table?",
          "expected_answer": "Papa is searching for his spectacles on the table.",
          "solution_explanation": "Searching for spectacles.",
          "source_type": "AI_GENERATED"
        }
      ]
    }
    """

    with patch("app.services.paper.paper_generator_service.GeminiService.generate_response", return_value=fake_english_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=english_context):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()
    q_item = paper_data["questions"][0]
    full_str = f"{q_item['question_text']} {q_item.get('expected_answer', '')}".lower()
    assert "quantum" not in full_str
    assert "spectacles" in full_str


def test_insufficient_source_material_rejection():
    """
    Test that requesting more grounded questions than the source material supports returns HTTP 400.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Sufficiency Tester", "email": f"suff_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 50,
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 25, "marks_per_question": 2, "section_name": "Section A"},
        ],
    }

    english_context = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "page_number": 1,
            "chapter_id": ch1["id"],
            "book_id": book["id"],
            "subject_id": subj["id"],
            "workspace_id": ws["id"],
            "content": "Papa is searching for his spectacles.",
            "content_type": "TEXT",
            "distance": 0.1,
            "metadata": {},
        }
    ]

    # LLM returns ungrounded hallucinated response (e.g. quantum computing)
    fake_hallucinated_response = """
    {
      "questions": [
        {
          "question_text": "Explain quantum entanglement in superposition state.",
          "expected_answer": "Quantum states interact across spin channels.",
          "solution_explanation": "Entanglement explanation.",
          "source_type": "AI_GENERATED"
        }
      ]
    }
    """

    with patch("app.services.paper.paper_generator_service.GeminiService.generate_response", return_value=fake_hallucinated_response), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=english_context):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 400
    assert "Insufficient educational source material" in res.json()["detail"]


def test_internal_choice_blueprint_analysis():
    """
    Test that BlueprintService correctly parses reference paper internal choice structures:
    Section A: 3 questions x 1 mark (no choice) = 3 marks
    Section B: 5 questions x 4 marks (2 alternatives) = 20 marks
    Section C: 5 questions x 7 marks (2 alternatives) = 35 marks
    Total marks = 58
    """
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint

    fake_analysis_json = """
    {
      "total_marks": 58,
      "sections": [
        {
          "name": "Section A",
          "question_type": "SHORT_ANSWER",
          "question_count": 3,
          "marks_per_question": 1,
          "has_internal_choice": false,
          "alternatives_per_question": 1
        },
        {
          "name": "Section B",
          "question_type": "SHORT_ANSWER",
          "question_count": 5,
          "marks_per_question": 4,
          "has_internal_choice": true,
          "alternatives_per_question": 2,
          "choice_rule": "answer_one_of_two"
        },
        {
          "name": "Section C",
          "question_type": "LONG_ANSWER",
          "question_count": 5,
          "marks_per_question": 7,
          "has_internal_choice": true,
          "alternatives_per_question": 2,
          "choice_rule": "answer_one_of_two"
        }
      ]
    }
    """

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=fake_analysis_json):
        bp_service = BlueprintService()
        bp = bp_service.analyze_reference_paper(["Sample Reference Paper Text"])

    assert bp.total_marks == 58
    assert len(bp.sections) == 3

    sec_a = bp.sections[0]
    assert sec_a.name == "Section A"
    assert sec_a.question_count == 3
    assert sec_a.marks_per_question == 1
    assert sec_a.total_section_marks == 3
    assert sec_a.has_internal_choice is False
    assert sec_a.alternatives_per_question == 1

    sec_b = bp.sections[1]
    assert sec_b.name == "Section B"
    assert sec_b.question_count == 5
    assert sec_b.marks_per_question == 4
    assert sec_b.total_section_marks == 20  # 5 * 4 = 20, NOT 40
    assert sec_b.has_internal_choice is True
    assert sec_b.alternatives_per_question == 2

    sec_c = bp.sections[2]
    assert sec_c.name == "Section C"
    assert sec_c.question_count == 5
    assert sec_c.marks_per_question == 7
    assert sec_c.total_section_marks == 35  # 5 * 7 = 35, NOT 70
    assert sec_c.has_internal_choice is True
    assert sec_c.alternatives_per_question == 2


def test_internal_choice_marks_validation():
    """
    Verify that 5 questions x 2 alternatives x 4 marks is interpreted as 5 x 4 = 20 marks, not 40.
    """
    from app.schemas.paper import QuestionType, QuestionConfigItem
    from app.services.paper.blueprint_service import BlueprintService

    cfg = QuestionConfigItem(
        question_type=QuestionType.SHORT_ANSWER,
        question_count=5,
        marks_per_question=4,
        section_name="Section B",
        has_internal_choice=True,
        alternatives_per_question=2,
        choice_rule="answer_one_of_two"
    )

    bp_service = BlueprintService()
    custom_bp = bp_service.build_custom_blueprint([cfg], total_marks=20)

    assert custom_bp.total_marks == 20
    assert custom_bp.sections[0].total_section_marks == 20
    assert custom_bp.sections[0].has_internal_choice is True
    assert custom_bp.sections[0].alternatives_per_question == 2


def test_reference_mode_internal_choice_paper_generation():
    """
    Test full REFERENCE mode paper generation with internal choice reproduction:
    Section A: Q1, Q2, Q3 (1 mark each)
    Section B: Q4(a)/Q4(b) .. Q8(a)/Q8(b) (4 marks each)
    Section C: Q9(a)/Q9(b) .. Q13(a)/Q13(b) (7 marks each)
    Total marks = 58
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Internal Choice Tester", "email": f"ic_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    # Create reference paper
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Exam Paper with Internal Choice")
    pdf_bytes = doc.tobytes()
    doc.close()

    ref_paper_res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Internal Choice Ref Paper", "year": "2024", "exam_type": "FINAL"},
        files={"file": ("ic_ref.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert ref_paper_res.status_code == 201
    ref_paper = ref_paper_res.json()

    from app.schemas.paper import QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint

    mock_ic_bp = PaperBlueprint(
        total_marks=58,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=3,
                marks_per_question=1,
                total_section_marks=3,
                has_internal_choice=False,
                alternatives_per_question=1,
            ),
            SectionBlueprint(
                name="Section B",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=5,
                marks_per_question=4,
                total_section_marks=20,
                has_internal_choice=True,
                alternatives_per_question=2,
                choice_rule="answer_one_of_two",
            ),
            SectionBlueprint(
                name="Section C",
                question_type=QuestionType.LONG_ANSWER,
                question_count=5,
                marks_per_question=7,
                total_section_marks=35,
                has_internal_choice=True,
                alternatives_per_question=2,
                choice_rule="answer_one_of_two",
            ),
        ],
        sample_questions=[],
    )

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 58,
        "include_answers": True,
    }

    with patch("app.services.paper.blueprint_service.BlueprintService.analyze_reference_paper", return_value=mock_ic_bp), \
         patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.json()}"
    paper_data = res.json()
    assert paper_data["generation_mode"] == "REFERENCE"
    assert paper_data["total_marks"] == 58

    questions = paper_data["questions"]
    # Total items = 3 (Section A) + 10 (Section B) + 10 (Section C) = 23 question items
    assert len(questions) == 23

    # Section A checks (Q1, Q2, Q3)
    sec_a_qs = [q for q in questions if q["section_name"] == "Section A"]
    assert len(sec_a_qs) == 3
    for q in sec_a_qs:
        assert q["choice_group"] is None
        assert q["alternative_label"] is None
        assert q["marks"] == 1

    # Section B checks (Q4(a)/Q4(b) .. Q8(a)/Q8(b))
    sec_b_qs = [q for q in questions if q["section_name"] == "Section B"]
    assert len(sec_b_qs) == 10
    sec_b_groups = set(q["choice_group"] for q in sec_b_qs)
    assert sec_b_groups == {"Q4", "Q5", "Q6", "Q7", "Q8"}
    for q in sec_b_qs:
        assert q["alternative_label"] in ["a", "b"]
        assert q["marks"] == 4

    # Section C checks (Q9(a)/Q9(b) .. Q13(a)/Q13(b))
    sec_c_qs = [q for q in questions if q["section_name"] == "Section C"]
    assert len(sec_c_qs) == 10
    sec_c_groups = set(q["choice_group"] for q in sec_c_qs)
    assert sec_c_groups == {"Q9", "Q10", "Q11", "Q12", "Q13"}
    for q in sec_c_qs:
        assert q["alternative_label"] in ["a", "b"]
        assert q["marks"] == 7


def test_internal_choice_include_answers_stripping():
    """
    Test that include_answers=False correctly strips expected answers from all internal choice alternatives.
    """
    uid = uuid4().hex[:8]
    user = client.post(
        "/api/v1/auth/register",
        json={"name": "Answer Strip Tester", "email": f"strip_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Ch1", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch1["id"]],
        "generation_mode": "CUSTOM",
        "total_marks": 4,
        "include_answers": False,
        "question_configs": [
            {
                "question_type": "SHORT_ANSWER",
                "question_count": 1,
                "marks_per_question": 4,
                "section_name": "Section B",
                "has_internal_choice": True,
                "alternatives_per_question": 2,
                "choice_rule": "answer_one_of_two"
            }
        ],
    }

    with patch("app.services.paper.paper_generator_service.RetrievalService.retrieve_context", return_value=[]):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == 201
    paper_data = res.json()
    assert paper_data["include_answers"] is False
    assert len(paper_data["questions"]) == 2

    for q in paper_data["questions"]:
        assert q["choice_group"] == "Q1"
        assert q["alternative_label"] in ["a", "b"]
        assert q["expected_answer"] is None
        assert q["solution_explanation"] is None


def test_reference_blueprint_exact_preservation_60_marks():
    """
    Regression Test: Verify that when requested_total_marks == analyzed total_marks (60),
    the reference blueprint is preserved EXACTLY:
    - Section A = 5 x 1 = 5
    - Section B = 5 x 4 = 20 (internal choices)
    - Section C = 5 x 7 = 35 (internal choices)
    - Total = 60
    - NO section has marks_per_question == 16.
    """
    from unittest.mock import patch
    from app.services.paper.blueprint_service import BlueprintService

    mock_raw_60_response = """
    {
      "total_marks": 60,
      "sections": [
        {
          "name": "Part A",
          "question_type": "SHORT_ANSWER",
          "question_count": 5,
          "marks_per_question": 1,
          "has_internal_choice": false,
          "alternatives_per_question": 1,
          "choice_rule": null
        },
        {
          "name": "Part B",
          "question_type": "SHORT_ANSWER",
          "question_count": 5,
          "marks_per_question": 4,
          "has_internal_choice": true,
          "alternatives_per_question": 2,
          "choice_rule": "answer_one_of_two"
        },
        {
          "name": "Part C",
          "question_type": "LONG_ANSWER",
          "question_count": 5,
          "marks_per_question": 7,
          "has_internal_choice": true,
          "alternatives_per_question": 2,
          "choice_rule": "answer_one_of_two"
        }
      ]
    }
    """

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=mock_raw_60_response):
        bp_svc = BlueprintService()
        bp = bp_svc.analyze_reference_paper(["Sample OCR Text Page 1", "Sample OCR Text Page 2"], requested_total_marks=60)

    assert bp.total_marks == 60
    assert len(bp.sections) == 3

    # Part A
    sec_a = bp.sections[0]
    assert sec_a.question_count == 5
    assert sec_a.marks_per_question == 1
    assert sec_a.total_section_marks == 5
    assert sec_a.has_internal_choice is False

    # Part B
    sec_b = bp.sections[1]
    assert sec_b.question_count == 5
    assert sec_b.marks_per_question == 4
    assert sec_b.total_section_marks == 20
    assert sec_b.has_internal_choice is True
    assert sec_b.alternatives_per_question == 2

    # Part C
    sec_c = bp.sections[2]
    assert sec_c.question_count == 5
    assert sec_c.marks_per_question == 7
    assert sec_c.total_section_marks == 35
    assert sec_c.has_internal_choice is True
    assert sec_c.alternatives_per_question == 2

    # Verify no section has marks_per_question == 16
    for sec in bp.sections:
        assert sec.marks_per_question != 16


def test_end_to_end_reference_mode_60_marks_paper_generation():
    """
    End-to-End Regression Test:
    Using reference_paper_id = 3cca75b9-1978-4475-baf1-476ec3828891 (60 marks Blockchain reference paper),
    and selected English book = 95b10b9f-1346-4a75-af03-4ee2c24d6e29 (chapters 4550c9d0... and 25d70592...),
    verify that:
    1. Status is COMPLETED
    2. Total paper marks = 60
    3. Blueprint has 5x1, 5x4 choice, 5x7 choice (total 60)
    4. Database contains 25 physical question records:
       - 5 x 1 mark (Part A)
       - 10 x 4 marks (Part B: 5 choice groups)
       - 10 x 7 marks (Part C: 5 choice groups)
    5. NO generated question has marks == 16
    6. Content is grounded in the selected English textbook chapters.
    """
    from uuid import UUID
    from app.core.database import SessionLocal
    from app.models.reference_paper import ReferencePaper
    from app.models.workspace import Workspace
    from app.schemas.paper import PaperGenerateRequest, GenerationMode
    from app.services.paper.paper_generator_service import PaperGeneratorService

    from unittest.mock import patch

    db = SessionLocal()
    try:
        ref_paper = db.query(ReferencePaper).filter_by(id="3cca75b9-1978-4475-baf1-476ec3828891").first()
        if not ref_paper:
            pytest.skip("Reference paper 3cca75b9-1978-4475-baf1-476ec3828891 not found in test DB")

        ws = db.query(Workspace).filter_by(id=ref_paper.workspace_id).first()
        user_id = ws.owner_id

        req = PaperGenerateRequest(
            book_id=UUID("95b10b9f-1346-4a75-af03-4ee2c24d6e29"),
            selected_chapter_ids=[
                UUID("4550c9d0-eb6c-41f4-bb8a-286101dcbec4"),
                UUID("25d70592-5079-4fef-a4b6-869785181523"),
            ],
            generation_mode=GenerationMode.REFERENCE,
            reference_paper_id=ref_paper.id,
            total_marks=60,
            difficulty="MEDIUM",
            include_answers=False,
        )

        mock_bp_json = """
        {
          "total_marks": 60,
          "sections": [
            {
              "name": "Part A",
              "question_type": "SHORT_ANSWER",
              "question_count": 5,
              "marks_per_question": 1,
              "has_internal_choice": false,
              "alternatives_per_question": 1,
              "choice_rule": null
            },
            {
              "name": "Part B",
              "question_type": "SHORT_ANSWER",
              "question_count": 5,
              "marks_per_question": 4,
              "has_internal_choice": true,
              "alternatives_per_question": 2,
              "choice_rule": "answer_one_of_two"
            },
            {
              "name": "Part C",
              "question_type": "LONG_ANSWER",
              "question_count": 5,
              "marks_per_question": 7,
              "has_internal_choice": true,
              "alternatives_per_question": 2,
              "choice_rule": "answer_one_of_two"
            }
          ]
        }
        """

        mock_part_a_json = """
        {
          "questions": [
            {"question_text": "In Papa's Spectacles, where does Papa leave his glasses?", "expected_answer": "On his forehead", "correct_answer": "On his forehead", "solution_explanation": "Text detail", "source_type": "AI_GENERATED"},
            {"question_text": "Who finds Papa's spectacles in the story?", "expected_answer": "His daughter", "correct_answer": "His daughter", "solution_explanation": "Text detail", "source_type": "AI_GENERATED"},
            {"question_text": "What happens in Gone with the Scooter?", "expected_answer": "Family misadventures", "correct_answer": "Family misadventures", "solution_explanation": "Text detail", "source_type": "AI_GENERATED"},
            {"question_text": "Why was the family worried about the scooter?", "expected_answer": "Thought it was lost", "correct_answer": "Thought it was lost", "solution_explanation": "Text detail", "source_type": "AI_GENERATED"},
            {"question_text": "What is the lesson of Papa's Spectacles?", "expected_answer": "Look carefully", "correct_answer": "Look carefully", "solution_explanation": "Text detail", "source_type": "AI_GENERATED"}
          ]
        }
        """

        mock_part_b_json = """
        {
          "questions": [
            {"question_text": "Describe Papa's character in Papa's Spectacles.", "expected_answer": "Forgetful and funny", "correct_answer": "Forgetful and funny", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Explain the humor in searching for spectacles.", "expected_answer": "Glasses on head", "correct_answer": "Glasses on head", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "What role does the scooter play for the family?", "expected_answer": "Shared vehicle", "correct_answer": "Shared vehicle", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "How is the scooter issue resolved in the story?", "expected_answer": "Found parked nearby", "correct_answer": "Found parked nearby", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "What reactions do family members have to Papa?", "expected_answer": "Gentle teasing", "correct_answer": "Gentle teasing", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Why is Papa's Spectacles an appropriate title?", "expected_answer": "Central plot object", "correct_answer": "Central plot object", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Compare the setting of both English stories.", "expected_answer": "Indoors vs outdoors", "correct_answer": "Indoors vs outdoors", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Discuss daily routines in Papa's Spectacles.", "expected_answer": "Routine backdrop", "correct_answer": "Routine backdrop", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "What emotions occur in Gone with the Scooter?", "expected_answer": "Panic then relief", "correct_answer": "Panic then relief", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "How does humor enhance the reader connection in Papa's Spectacles?", "expected_answer": "Relatable warmth", "correct_answer": "Relatable warmth", "solution_explanation": "Detail", "source_type": "AI_GENERATED"}
          ]
        }
        """

        mock_part_c_json = """
        {
          "questions": [
            {"question_text": "Analyze themes of family unity in Papa's Spectacles story.", "expected_answer": "Affection and patience", "correct_answer": "Affection and patience", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Write a character study of Papa's forgetfulness in Papa's Spectacles.", "expected_answer": "Drives plot action", "correct_answer": "Drives plot action", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Examine narrative tension in Gone with the Scooter story.", "expected_answer": "Rising action search", "correct_answer": "Rising action search", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Compare narrative techniques in Papa's Spectacles and Gone with the Scooter.", "expected_answer": "Third person irony", "correct_answer": "Third person irony", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Discuss household objects driving Papa's Spectacles and Gone with the Scooter.", "expected_answer": "Spectacles and scooter", "correct_answer": "Spectacles and scooter", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "How does dialogue reflect Gopi's family relationships in Papa's Spectacles?", "expected_answer": "Playful banter", "correct_answer": "Playful banter", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Evaluate the ending of Gone with the Scooter in resolving Gopi's search.", "expected_answer": "Satisfying resolution", "correct_answer": "Satisfying resolution", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Explain childhood perspectives of Gopi in Papa's Spectacles.", "expected_answer": "Innocent amusement", "correct_answer": "Innocent amusement", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Analyze misunderstandings driving Gopi's scooter plot progress.", "expected_answer": "Minor misplacements", "correct_answer": "Minor misplacements", "solution_explanation": "Detail", "source_type": "AI_GENERATED"},
            {"question_text": "Discuss Papa's spectacles and scooter tone balance in both stories.", "expected_answer": "Playful tone", "correct_answer": "Playful tone", "solution_explanation": "Detail", "source_type": "AI_GENERATED"}
          ]
        }
        """

        responses = [mock_bp_json, mock_part_a_json, mock_part_b_json, mock_part_c_json]

        with patch("app.services.paper.paper_generator_service.GeminiService.generate_response", side_effect=responses), \
             patch("app.services.paper.blueprint_service.GeminiService.generate_response", side_effect=responses):
            svc = PaperGeneratorService(db)
            res = svc.generate_paper(current_user_id=user_id, request_data=req)

        assert res.status == "COMPLETED"
        assert res.total_marks == 60
        assert len(res.questions) == 25

        # Verify no 16-mark questions exist
        for q in res.questions:
            assert q.marks != 16

        part_a_qs = [q for q in res.questions if q.marks == 1]
        part_b_qs = [q for q in res.questions if q.marks == 4]
        part_c_qs = [q for q in res.questions if q.marks == 7]

        assert len(part_a_qs) == 5
        assert len(part_b_qs) == 10
        assert len(part_c_qs) == 10

        part_b_groups = set(q.choice_group for q in part_b_qs)
        assert len(part_b_groups) == 5

        part_c_groups = set(q.choice_group for q in part_c_qs)
        assert len(part_c_groups) == 5

        # Content grounding check: generated text should relate to English textbook topics
        combined_q_text = " ".join(q.question_text for q in res.questions).lower()
        assert any(term in combined_q_text for term in ["spectacles", "papa", "scooter", "word", "story"])
    finally:
        db.close()


def test_blueprint_denomination_preservation_100_marks():
    """
    TEST 2: Verify that when requested_total_marks = 100 for a reference paper with denominations 1, 4, 7 (total 60),
    the system constructs the 100-mark blueprint using ONLY {1, 4, 7} denominations without inventing 11-mark questions.
    """
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
    from app.schemas.paper import QuestionType

    ref_bp = PaperBlueprint(
        total_marks=60,
        sections=[
            SectionBlueprint(name="Part A", question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=1, total_section_marks=5),
            SectionBlueprint(name="Part B", question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=4, total_section_marks=20, has_internal_choice=True, alternatives_per_question=2),
            SectionBlueprint(name="Part C", question_type=QuestionType.LONG_ANSWER, question_count=5, marks_per_question=7, total_section_marks=35, has_internal_choice=True, alternatives_per_question=2),
        ]
    )

    bp_svc = BlueprintService()
    adapted = bp_svc.adapt_reference_blueprint(ref_bp, target_total_marks=100)

    assert adapted.total_marks == 100
    assert sum(s.total_section_marks for s in adapted.sections) == 100

    # Verify that ONLY reference denominations (1, 4, 7) are present in the adapted blueprint
    denominations = set(s.marks_per_question for s in adapted.sections)
    assert denominations.issubset({1, 4, 7})
    assert 11 not in denominations

    # Verify section internal choices and types are preserved
    for sec in adapted.sections:
        assert sec.question_count * sec.marks_per_question == sec.total_section_marks
        if sec.name in ["Part B", "Part C"]:
            assert sec.has_internal_choice is True
            assert sec.alternatives_per_question == 2


def test_blueprint_custom_denominations_preservation():
    """
    TEST 3: Verify that custom reference paper denominations (e.g. 2, 5, 10) are preserved when constructing
    a requested total (e.g. 50 marks).
    """
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
    from app.schemas.paper import QuestionType

    ref_bp = PaperBlueprint(
        total_marks=34,
        sections=[
            SectionBlueprint(name="Section 1", question_type=QuestionType.MCQ, question_count=2, marks_per_question=2, total_section_marks=4),
            SectionBlueprint(name="Section 2", question_type=QuestionType.SHORT_ANSWER, question_count=2, marks_per_question=5, total_section_marks=10),
            SectionBlueprint(name="Section 3", question_type=QuestionType.LONG_ANSWER, question_count=2, marks_per_question=10, total_section_marks=20),
        ]
    )

    bp_svc = BlueprintService()
    adapted = bp_svc.adapt_reference_blueprint(ref_bp, target_total_marks=50)

    assert adapted.total_marks == 50
    assert sum(s.total_section_marks for s in adapted.sections) == 50

    denominations = set(s.marks_per_question for s in adapted.sections)
    assert denominations.issubset({2, 5, 10})


def test_blueprint_fallback_adaptation():
    """
    TEST 4: Verify controlled fallback to adapted marks when target total (e.g. 13) cannot be constructed
    using exact reference denominations (e.g. 5).
    TEST 5: Verify final blueprint total always equals requested_total_marks.
    """
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
    from app.schemas.paper import QuestionType

    ref_bp = PaperBlueprint(
        total_marks=25,
        sections=[
            SectionBlueprint(name="Section A", question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=5, total_section_marks=25),
        ]
    )

    bp_svc = BlueprintService()
    adapted = bp_svc.adapt_reference_blueprint(ref_bp, target_total_marks=13)

    assert adapted.total_marks == 13
    assert sum(s.total_section_marks for s in adapted.sections) == 13
    for sec in adapted.sections:
        assert sec.question_count * sec.marks_per_question == sec.total_section_marks


def test_reference_analysis_does_not_distort_natural_blueprint_when_requested_total_differs():
    """
    Verify that analyze_reference_paper extracts the natural blueprint of the reference paper
    first and adapts it using adapt_reference_blueprint when requested_total_marks differs.
    """
    from app.services.paper.blueprint_service import BlueprintService

    mock_gemini_analysis_json = """
    {
      "total_marks": 60,
      "sections": [
        {"name": "Part A", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 1, "has_internal_choice": false, "alternatives_per_question": 1, "choice_rule": null},
        {"name": "Part B", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 4, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"},
        {"name": "Part C", "question_type": "LONG_ANSWER", "question_count": 5, "marks_per_question": 7, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"}
      ],
      "sample_questions": []
    }
    """

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=mock_gemini_analysis_json):
        bp_svc = BlueprintService()
        pages_text = ["Page 1 text content...", "Page 2 text content..."]
        blueprint = bp_svc.analyze_reference_paper(pages_text, requested_total_marks=100)

    assert blueprint.total_marks == 100
    section_names = [s.name for s in blueprint.sections]
    assert section_names == ["Part A", "Part B", "Part C"]
    denominations = set(s.marks_per_question for s in blueprint.sections)
    assert denominations.issubset({1, 4, 7})
    assert 11 not in denominations


def test_reference_analysis_infers_missing_part_c_heading_from_question_sequence():
    """
    REGRESSION TEST: Verify that reference analysis infers Part C from question sequence (Q11-Q15)
    even if the explicit "Part C" heading is omitted in OCR text, recovering the full 60-mark blueprint.
    """
    from app.services.paper.blueprint_service import BlueprintService

    # OCR text where Part C header is missing, but Q11-Q15 exist with 7 marks each
    ocr_text_missing_header = """
    Part A (5 Questions x 1 Mark = 5 Marks)
    1. Q1 text
    2. Q2 text
    3. Q3 text
    4. Q4 text
    5. Q5 text
    Part B (5 Questions X 4 Marks = 20 Marks)
    6a. Q6a OR 6b. Q6b
    7a. Q7a OR 7b. Q7b
    8a. Q8a OR 8b. Q8b
    9a. Q9a OR 9b. Q9b
    10a. Q10a OR 10b. Q10b
    11a. Q11a OR 11b. Q11b (7 marks)
    12a. Q12a OR 12b. Q12b (7 marks)
    13a. Q13a OR 13b. Q13b (7 marks)
    14a. Q14a OR 14b. Q14b (7 marks)
    15a. Q15a OR 15b. Q15b (7 marks)
    """

    mock_recovered_json = """
    {
      "total_marks": 60,
      "sections": [
        {"name": "Part A", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 1, "has_internal_choice": false, "alternatives_per_question": 1},
        {"name": "Part B", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 4, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"},
        {"name": "Part C", "question_type": "LONG_ANSWER", "question_count": 5, "marks_per_question": 7, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"}
      ],
      "sample_questions": []
    }
    """

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=mock_recovered_json):
        bp_svc = BlueprintService()
        blueprint = bp_svc.analyze_reference_paper([ocr_text_missing_header], requested_total_marks=100)

    assert blueprint.total_marks == 100
    assert len(blueprint.sections) == 3
    sec_names = [s.name for s in blueprint.sections]
    assert sec_names == ["Part A", "Part B", "Part C"]

    # Verify that Section A question count is NOT 20 (does NOT collapse into Part A = 20x1, Part B = 20x4)
    part_a = next(s for s in blueprint.sections if s.name == "Part A")
    assert part_a.question_count != 20
    assert part_a.question_count < 15

    # Verify denominations {1, 4, 7} are preserved with zero 11-mark questions
    denominations = set(s.marks_per_question for s in blueprint.sections)
    assert denominations.issubset({1, 4, 7})
    assert 11 not in denominations


def test_reference_blueprint_exact_preservation_60_marks_explicit():
    """
    REGRESSION TEST: Given reference blueprint = 5x1 + 5x4 + 5x7 = 60 and requested_total_marks = 60,
    verify exact blueprint preservation without any modification, scaling, or 14-mark sections.
    """
    from app.services.paper.blueprint_service import BlueprintService

    mock_60m_json = """
    {
      "total_marks": 60,
      "sections": [
        {"name": "Part A", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 1, "has_internal_choice": false, "alternatives_per_question": 1},
        {"name": "Part B", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 4, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"},
        {"name": "Part C", "question_type": "LONG_ANSWER", "question_count": 5, "marks_per_question": 7, "has_internal_choice": true, "alternatives_per_question": 2, "choice_rule": "answer_one_of_two"}
      ],
      "sample_questions": []
    }
    """

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=mock_60m_json):
        bp_svc = BlueprintService()
        pages_text = ["Page 1 text content...", "Page 2 text content..."]
        result = bp_svc.analyze_reference_paper(pages_text, requested_total_marks=60)

    assert result.total_marks == 60
    assert len(result.sections) == 3

    part_a = result.sections[0]
    assert part_a.name == "Part A"
    assert part_a.question_count == 5
    assert part_a.marks_per_question == 1
    assert part_a.total_section_marks == 5

    part_b = result.sections[1]
    assert part_b.name == "Part B"
    assert part_b.question_count == 5
    assert part_b.marks_per_question == 4
    assert part_b.total_section_marks == 20
    assert part_b.has_internal_choice is True

    part_c = result.sections[2]
    assert part_c.name == "Part C"
    assert part_c.question_count == 5
    assert part_c.marks_per_question == 7
    assert part_c.total_section_marks == 35
    assert part_c.has_internal_choice is True

    assert set(section.marks_per_question for section in result.sections) == {1, 4, 7}


def test_generated_paper_choice_group_numbering_and_structure_validation():
    """
    REGRESSION TEST: Verify generated paper choice groups and question order for 60-mark reference paper:
    - Part A: 5 records (Q1-Q5), SHORT_ANSWER, 1 mark
    - Part B: 10 records (Q6a/b through Q10a/b), SHORT_ANSWER, 4 marks
    - Part C: 10 records (Q11a/b through Q15a/b), LONG_ANSWER, 7 marks
    Total records = 25.
    """
    from unittest.mock import MagicMock
    from app.services.paper.paper_generator_service import PaperGeneratorService
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
    from app.schemas.paper import QuestionType, GenerationMode, DifficultyLevel

    blueprint = PaperBlueprint(
        total_marks=60,
        sections=[
            SectionBlueprint(name="Part A", question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=1, total_section_marks=5, has_internal_choice=False, alternatives_per_question=1),
            SectionBlueprint(name="Part B", question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=4, total_section_marks=20, has_internal_choice=True, alternatives_per_question=2, choice_rule="answer_one_of_two"),
            SectionBlueprint(name="Part C", question_type=QuestionType.LONG_ANSWER, question_count=5, marks_per_question=7, total_section_marks=35, has_internal_choice=True, alternatives_per_question=2, choice_rule="answer_one_of_two"),
        ],
        sample_questions=[]
    )

    svc = PaperGeneratorService(db=MagicMock())

    def mock_generate_response(prompt, **kwargs):
        qs = [
            {
                "question_text": f"Educational context question text item {i}.",
                "expected_answer": "Answer text.",
                "solution_explanation": "Explanation text.",
                "source_type": "AI_GENERATED",
                "choice_group": f"Q{(i // 2) + 1}",
                "alternative_label": "a" if i % 2 == 0 else "b",
            }
            for i in range(12)
        ]
        return json.dumps({"questions": qs})

    with patch.object(svc.ai_service, "generate_response", side_effect=mock_generate_response), \
         patch.object(svc, "_is_question_grounded", return_value=True), \
         patch.object(svc, "_is_duplicate_question", return_value=False):
        questions = svc._generate_section_questions(
            blueprint=blueprint,
            context_text="Educational source material text context for testing question generation.",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.REFERENCE,
            sample_questions=[],
        )

    # TEST 8: Total generated question records = 25
    assert len(questions) == 25

    part_a_qs = [q for q in questions if q["section_name"] == "Part A"]
    part_b_qs = [q for q in questions if q["section_name"] == "Part B"]
    part_c_qs = [q for q in questions if q["section_name"] == "Part C"]

    assert len(part_a_qs) == 5
    assert len(part_b_qs) == 10
    assert len(part_c_qs) == 10

    # TEST 6 & 7: Question types and marks per question
    for q in part_a_qs:
        assert q["question_type"] == "SHORT_ANSWER"
        assert q["marks"] == 1
        assert q["choice_group"] is None
        assert q["alternative_label"] is None

    # TEST 2 & 4: Part B choice groups are Q6..Q10 with 'a' and 'b'
    part_b_groups = {}
    for q in part_b_qs:
        assert q["question_type"] == "SHORT_ANSWER"
        assert q["marks"] == 4
        grp = q["choice_group"]
        lbl = q["alternative_label"]
        assert grp in ["Q6", "Q7", "Q8", "Q9", "Q10"]
        assert lbl in ["a", "b"]
        part_b_groups.setdefault(grp, set()).add(lbl)

    assert set(part_b_groups.keys()) == {"Q6", "Q7", "Q8", "Q9", "Q10"}
    for grp, labels in part_b_groups.items():
        assert labels == {"a", "b"}

    # No Part B choice groups should be Q1..Q5
    assert not any(q["choice_group"] in ["Q1", "Q2", "Q3", "Q4", "Q5"] for q in part_b_qs)

    # TEST 3 & 5: Part C choice groups are Q11..Q15 with 'a' and 'b'
    part_c_groups = {}
    for q in part_c_qs:
        assert q["question_type"] == "LONG_ANSWER"
        assert q["marks"] == 7
        grp = q["choice_group"]
        lbl = q["alternative_label"]
        assert grp in ["Q11", "Q12", "Q13", "Q14", "Q15"]
        assert lbl in ["a", "b"]
        part_c_groups.setdefault(grp, set()).add(lbl)

    assert set(part_c_groups.keys()) == {"Q11", "Q12", "Q13", "Q14", "Q15"}
    for grp, labels in part_c_groups.items():
        assert labels == {"a", "b"}

    # No Part C choice groups should be Q1..Q10
    assert not any(q["choice_group"] in [f"Q{i}" for i in range(1, 11)] for q in part_c_qs)


def test_custom_mode_alternatives_field_parsing_and_blueprint_construction():
    """
    REGRESSION TEST: Verify that QuestionConfigItem correctly parses 'alternatives' field alias,
    setting has_internal_choice=True, alternatives_per_question=2, and choice_rule='answer_one_of_two'.
    """
    from app.schemas.paper import QuestionConfigItem, QuestionType
    from app.services.paper.blueprint_service import BlueprintService

    cfgs = [
        QuestionConfigItem(question_type=QuestionType.MCQ, question_count=10, marks_per_question=1, alternatives=1),
        QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=2, alternatives=2),
        QuestionConfigItem(question_type=QuestionType.LONG_ANSWER, question_count=4, marks_per_question=5, alternatives=2),
    ]

    bp_svc = BlueprintService()
    bp = bp_svc.build_custom_blueprint(cfgs, total_marks=40)

    assert bp.total_marks == 40
    assert len(bp.sections) == 3

    sec_a = bp.sections[0]
    assert sec_a.name == "Section A"
    assert sec_a.question_count == 10
    assert sec_a.marks_per_question == 1
    assert sec_a.total_section_marks == 10
    assert sec_a.has_internal_choice is False
    assert sec_a.alternatives_per_question == 1
    assert sec_a.choice_rule is None

    sec_b = bp.sections[1]
    assert sec_b.name == "Section B"
    assert sec_b.question_count == 5
    assert sec_b.marks_per_question == 2
    assert sec_b.total_section_marks == 10
    assert sec_b.has_internal_choice is True
    assert sec_b.alternatives_per_question == 2
    assert sec_b.choice_rule == "answer_one_of_two"

    sec_c = bp.sections[2]
    assert sec_c.name == "Section C"
    assert sec_c.question_count == 4
    assert sec_c.marks_per_question == 5
    assert sec_c.total_section_marks == 20
    assert sec_c.has_internal_choice is True
    assert sec_c.alternatives_per_question == 2
    assert sec_c.choice_rule == "answer_one_of_two"


def test_custom_mode_mixed_sections_internal_choices_40_marks():
    """
    REGRESSION TEST: Verify CUSTOM paper generation with alternatives=2 generates 28 question records total:
    - Section A (MCQ): 10 records (Q1..Q10, 1 mark each) -> 10 marks
    - Section B (SHORT_ANSWER): 10 records (Q11a/b..Q15a/b, 2 marks each) -> 10 marks
    - Section C (LONG_ANSWER): 8 records (Q16a/b..Q19a/b, 5 marks each) -> 20 marks
    Total records = 28. Total paper marks = 40.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionConfigItem, QuestionType, GenerationMode, DifficultyLevel
    from app.services.paper.blueprint_service import BlueprintService
    from app.services.paper.paper_generator_service import PaperGeneratorService

    cfgs = [
        QuestionConfigItem(question_type=QuestionType.MCQ, question_count=10, marks_per_question=1, alternatives=1),
        QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=5, marks_per_question=2, alternatives=2),
        QuestionConfigItem(question_type=QuestionType.LONG_ANSWER, question_count=4, marks_per_question=5, alternatives=2),
    ]

    bp_svc = BlueprintService()
    bp = bp_svc.build_custom_blueprint(cfgs, total_marks=40)

    pg_svc = PaperGeneratorService(db=MagicMock())

    counter = [0]
    def mock_generate_response(prompt, **kwargs):
        qs = []
        for i in range(15):
            counter[0] += 1
            qs.append({
                "question_text": f"Unique custom question text item {counter[0]} for source content.",
                "expected_answer": "Comprehensive model expected answer with detailed explanations.",
                "solution_explanation": "Solution explanation criteria.",
                "mcq_options": ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"],
                "correct_answer": "A. Option 1",
            })
        return json.dumps({"questions": qs})

    pg_svc.ai_service.generate_response = mock_generate_response

    with patch.object(pg_svc, "_is_question_grounded", return_value=True), \
         patch.object(pg_svc, "_is_duplicate_question", return_value=False):
        questions = pg_svc._generate_section_questions(
            blueprint=bp,
            context_text="Valid educational source context.",
            topic_focus=None,
            difficulty=DifficultyLevel.MEDIUM,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=[],
        )

    # 10 + 10 + 8 = 28 records total
    assert len(questions) == 28

    sec_a_qs = [q for q in questions if q["section_name"] == "Section A"]
    sec_b_qs = [q for q in questions if q["section_name"] == "Section B"]
    sec_c_qs = [q for q in questions if q["section_name"] == "Section C"]

    assert len(sec_a_qs) == 10
    assert len(sec_b_qs) == 10
    assert len(sec_c_qs) == 8

    # Section A
    for q in sec_a_qs:
        assert q["question_type"] == "MCQ"
        assert q["marks"] == 1
        assert q["choice_group"] is None
        assert q["alternative_label"] is None

    # Section B: Q11..Q15
    b_groups = {}
    for q in sec_b_qs:
        assert q["question_type"] == "SHORT_ANSWER"
        assert q["marks"] == 2
        grp = q["choice_group"]
        lbl = q["alternative_label"]
        assert grp in ["Q11", "Q12", "Q13", "Q14", "Q15"]
        assert lbl in ["a", "b"]
        b_groups.setdefault(grp, set()).add(lbl)

    assert set(b_groups.keys()) == {"Q11", "Q12", "Q13", "Q14", "Q15"}
    for grp, lbls in b_groups.items():
        assert lbls == {"a", "b"}

    # Section C: Q16..Q19
    c_groups = {}
    for q in sec_c_qs:
        assert q["question_type"] == "LONG_ANSWER"
        assert q["marks"] == 5
        grp = q["choice_group"]
        lbl = q["alternative_label"]
        assert grp in ["Q16", "Q17", "Q18", "Q19"]
        assert lbl in ["a", "b"]
        c_groups.setdefault(grp, set()).add(lbl)

    assert set(c_groups.keys()) == {"Q16", "Q17", "Q18", "Q19"}
    for grp, lbls in c_groups.items():
        assert lbls == {"a", "b"}


def test_custom_mode_easy_difficulty_persisted_correctly():
    """
    REGRESSION TEST: Verify CUSTOM generation with difficulty=EASY assigns difficulty='EASY'
    to every generated question database record.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionConfigItem, QuestionType, GenerationMode, DifficultyLevel
    from app.services.paper.blueprint_service import BlueprintService
    from app.services.paper.paper_generator_service import PaperGeneratorService

    cfgs = [QuestionConfigItem(question_type=QuestionType.MCQ, question_count=5, marks_per_question=1, alternatives=1)]
    bp = BlueprintService().build_custom_blueprint(cfgs, total_marks=5)

    pg_svc = PaperGeneratorService(db=MagicMock())
    counter = [0]
    def mock_generate_response(prompt, **kwargs):
        counter[0] += 1
        return json.dumps({
            "questions": [{
                "question_text": f"Direct recall easy fact question item {counter[0]}.",
                "difficulty": "EASY",
                "mcq_options": ["A. Opt 1", "B. Opt 2", "C. Opt 3", "D. Opt 4"],
                "correct_answer": "A. Opt 1",
                "solution_explanation": "Direct recall explanation."
            } for _ in range(5)]
        })

    pg_svc.ai_service.generate_response = mock_generate_response

    with patch.object(pg_svc, "_is_question_grounded", return_value=True), \
         patch.object(pg_svc, "_is_duplicate_question", return_value=False):
        questions = pg_svc._generate_section_questions(
            blueprint=bp,
            context_text="Source material text context.",
            topic_focus=None,
            difficulty=DifficultyLevel.EASY,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=[],
        )

    assert len(questions) == 5
    for q in questions:
        assert q["difficulty"] == "EASY"


def test_custom_mode_hard_difficulty_persisted_correctly():
    """
    REGRESSION TEST: Verify CUSTOM generation with difficulty=HARD assigns difficulty='HARD'
    to every generated question database record.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionConfigItem, QuestionType, GenerationMode, DifficultyLevel
    from app.services.paper.blueprint_service import BlueprintService
    from app.services.paper.paper_generator_service import PaperGeneratorService

    cfgs = [QuestionConfigItem(question_type=QuestionType.SHORT_ANSWER, question_count=4, marks_per_question=5, alternatives=1)]
    bp = BlueprintService().build_custom_blueprint(cfgs, total_marks=20)

    pg_svc = PaperGeneratorService(db=MagicMock())
    counter = [0]
    def mock_generate_response(prompt, **kwargs):
        counter[0] += 1
        return json.dumps({
            "questions": [{
                "question_text": f"Deep analysis hard question requiring multi-step reasoning item {counter[0]}.",
                "difficulty": "HARD",
                "expected_answer": "Comprehensive model answer with synthesis.",
                "solution_explanation": "Detailed analysis step by step."
            } for _ in range(4)]
        })

    pg_svc.ai_service.generate_response = mock_generate_response

    with patch.object(pg_svc, "_is_question_grounded", return_value=True), \
         patch.object(pg_svc, "_is_duplicate_question", return_value=False):
        questions = pg_svc._generate_section_questions(
            blueprint=bp,
            context_text="Source material text context.",
            topic_focus=None,
            difficulty=DifficultyLevel.HARD,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=[],
        )

    assert len(questions) == 4
    for q in questions:
        assert q["difficulty"] == "HARD"


def test_llm_returned_difficulty_cannot_override_backend_target():
    """
    REGRESSION TEST: Verify that if LLM returns 'difficulty': 'MEDIUM' when backend target is HARD,
    the backend target 'HARD' overrides and is authoritatively assigned.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionConfigItem, QuestionType, GenerationMode, DifficultyLevel
    from app.services.paper.blueprint_service import BlueprintService
    from app.services.paper.paper_generator_service import PaperGeneratorService

    cfgs = [QuestionConfigItem(question_type=QuestionType.MCQ, question_count=3, marks_per_question=1, alternatives=1)]
    bp = BlueprintService().build_custom_blueprint(cfgs, total_marks=3)

    pg_svc = PaperGeneratorService(db=MagicMock())
    def mock_generate_response(prompt, **kwargs):
        return json.dumps({
            "questions": [{
                "question_text": f"Target hard question item {i}.",
                "difficulty": "MEDIUM",  # LLM attempts to return MEDIUM
                "mcq_options": ["A. Opt 1", "B. Opt 2", "C. Opt 3", "D. Opt 4"],
                "correct_answer": "A. Opt 1",
                "solution_explanation": "Explanation."
            } for i in range(3)]
        })

    pg_svc.ai_service.generate_response = mock_generate_response

    with patch.object(pg_svc, "_is_question_grounded", return_value=True), \
         patch.object(pg_svc, "_is_duplicate_question", return_value=False):
        questions = pg_svc._generate_section_questions(
            blueprint=bp,
            context_text="Source material text context.",
            topic_focus=None,
            difficulty=DifficultyLevel.HARD,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=[],
        )

    assert len(questions) == 3
    for q in questions:
        # Backend target HARD authoritatively overrides LLM MEDIUM
        assert q["difficulty"] == "HARD"


def test_mixed_difficulty_distribution_persisted_correctly():
    """
    REGRESSION TEST: Verify MIXED difficulty generates a distribution of EASY, MEDIUM, HARD
    matching calculated sub_difficulties.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionConfigItem, QuestionType, GenerationMode, DifficultyLevel
    from app.services.paper.blueprint_service import BlueprintService
    from app.services.paper.paper_generator_service import PaperGeneratorService

    cfgs = [QuestionConfigItem(question_type=QuestionType.MCQ, question_count=10, marks_per_question=1, alternatives=1)]
    bp = BlueprintService().build_custom_blueprint(cfgs, total_marks=10)

    pg_svc = PaperGeneratorService(db=MagicMock())
    counter = [0]
    def mock_generate_response(prompt, **kwargs):
        qs = []
        for i in range(10):
            counter[0] += 1
            qs.append({
                "question_text": f"Mixed difficulty question item {counter[0]}.",
                "difficulty": "MEDIUM",
                "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                "correct_answer": "A. 1",
                "solution_explanation": "Exp."
            })
        return json.dumps({"questions": qs})

    pg_svc.ai_service.generate_response = mock_generate_response

    with patch.object(pg_svc, "_is_question_grounded", return_value=True), \
         patch.object(pg_svc, "_is_duplicate_question", return_value=False):
        questions = pg_svc._generate_section_questions(
            blueprint=bp,
            context_text="Source material text context.",
            topic_focus=None,
            difficulty=DifficultyLevel.MIXED,
            generation_mode=GenerationMode.CUSTOM,
            sample_questions=[],
        )

    assert len(questions) == 10
    diff_set = set(q["difficulty"] for q in questions)
    # MIXED mode should contain EASY, MEDIUM, and HARD questions
    assert "EASY" in diff_set
    assert "MEDIUM" in diff_set
    assert "HARD" in diff_set


def test_generation_prompt_contains_cognitive_taxonomy_and_anti_embellishment_rules():
    """
    REGRESSION TEST: Verify _build_generation_prompt produces prompt text containing:
    1. Explicit Cognitive Taxonomy (EASY/MEDIUM/HARD cognitive definitions).
    2. Anti-embellishment & spelling/vocabulary exercise fidelity instructions.
    3. JSON output contract requiring "difficulty".
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionType, GenerationMode
    from app.services.paper.blueprint_service import SectionBlueprint
    from app.services.paper.paper_generator_service import PaperGeneratorService

    pg_svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=5,
        marks_per_question=1,
        total_section_marks=5,
        has_internal_choice=False,
        alternatives_per_question=1,
    )

    prompt = pg_svc._build_generation_prompt(
        sec=sec,
        sec_start_q_num=1,
        needed_count=5,
        difficulties=["HARD"] * 5,
        context_text="Gopi sat in the veranda reading a book. vegatables / veggetables / vegetables.",
        topic_focus=None,
        generation_mode=GenerationMode.CUSTOM,
        section_ref_questions=[],
    )

    # 1. Cognitive Taxonomy check
    assert "DIFFICULTY DEFINITIONS & COGNITIVE DEMAND:" in prompt
    assert "EASY: Direct recall or recognition" in prompt
    assert "HARD: Analysis, synthesis, multi-step reasoning" in prompt
    assert "Difficulty means COGNITIVE DEMAND, NOT LANGUAGE COMPLEXITY." in prompt

    # 2. Question-Type Specific HARD Directives check
    assert "QUESTION-TYPE SPECIFIC COGNITIVE DIRECTIVES FOR HARD DIFFICULTY:" in prompt
    assert "1. HARD MCQ RULES:" in prompt
    assert "DO NOT ask for a single explicit fact" in prompt
    assert "A HARD MCQ must require connecting at least TWO distinct source details" in prompt
    assert "Use meaningful, plausible distractors" in prompt
    assert "2. HARD SHORT ANSWER RULES:" in prompt
    assert "3. HARD LONG ANSWER RULES:" in prompt

    # 3. Source-Richness Limitation Rule check
    assert "4. SOURCE-RICHNESS LIMITATION RULE:" in prompt
    assert "HARD difficulty depends on the cognitive possibilities of the source material." in prompt

    # 4. Anti-Embellishment & Source Fidelity check
    assert "CONTENT AUTHORITY, SOURCE FIDELITY & ANTI-EMBELLISHMENT RULES:" in prompt
    assert "For spelling exercises: Keep the question direct" in prompt
    assert "Do NOT invent semantic descriptions of the word" in prompt
    assert "DO NOT add decorative or functional descriptions" in prompt

    # 5. JSON Output Schema contract check
    assert '"difficulty": "<EASY | MEDIUM | HARD>"' in prompt


def test_reference_mode_prompt_contains_difficulty_preservation_rule():
    """
    REGRESSION TEST: Verify _build_generation_prompt in REFERENCE mode contains the instruction
    requiring reference question layout preservation while increasing cognitive demand for HARD difficulty.
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import QuestionType, GenerationMode
    from app.services.paper.blueprint_service import SectionBlueprint
    from app.services.paper.paper_generator_service import PaperGeneratorService

    pg_svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="Section A",
        question_type=QuestionType.MCQ,
        question_count=3,
        marks_per_question=1,
        total_section_marks=3,
    )

    sample_ref = [{"section_name": "Section A", "question_type": "MCQ", "question_text": "Sample ref Q"}]
    prompt = pg_svc._build_generation_prompt(
        sec=sec,
        sec_start_q_num=1,
        needed_count=3,
        difficulties=["HARD"] * 3,
        context_text="Sample educational context text.",
        topic_focus=None,
        generation_mode=GenerationMode.REFERENCE,
        section_ref_questions=sample_ref,
    )

    assert "If the requested difficulty is HARD, preserve the reference question format and layout while increasing the cognitive demand appropriately" in prompt













