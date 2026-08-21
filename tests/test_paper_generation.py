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

    # Verify answers stripped in API response
    for q in paper_data["questions"]:
        assert q["correct_answer"] is None
        assert q["expected_answer"] is None
        assert q["solution_explanation"] is None
        assert q["mcq_options"] is None

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
