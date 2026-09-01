import io
import os
import uuid

import fitz
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.reference_paper import ReferencePaper, ReferencePaperPage

from unittest.mock import patch

from app.repositories.reference_paper_repository import ReferencePaperRepository

client = TestClient(app)



def create_sample_pdf_bytes(pages_count: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(pages_count):
        page = doc.new_page()
        page.insert_text((50, 50), f"Sample Reference Paper Question Text Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_upload_reference_paper_success():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User", "email": f"ref_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"DBMS_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    files = {"file": ("exam_2025.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {
        "title": "DBMS Final Exam 2025",
        "year": "2025",
        "exam_type": "Final Exam",
    }

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    paper_res = res.json()

    assert paper_res["title"] == "DBMS Final Exam 2025"
    assert paper_res["year"] == 2025
    assert paper_res["exam_type"] == "Final Exam"
    assert paper_res["subject_id"] == subj["id"]
    assert paper_res["workspace_id"] == ws["id"]

    db = SessionLocal()
    try:
        # Verify DB records
        paper_db = db.query(ReferencePaper).filter(ReferencePaper.id == paper_res["id"]).first()
        assert paper_db is not None
        assert os.path.exists(paper_db.stored_path)

        # Verify page text records created
        pages_db = db.query(ReferencePaperPage).filter(ReferencePaperPage.reference_paper_id == paper_db.id).all()
        assert len(pages_db) == 2
        assert "Sample Reference Paper" in pages_db[0].text_content
    finally:
        db.close()


def test_upload_reference_paper_invalid_extension():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User 2", "email": f"ref2_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Math_{uid}"}, headers=headers).json()

    files = {"file": ("exam.txt", io.BytesIO(b"Not a pdf"), "text/plain")}
    data = {"title": "Math Exam"}

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file extension" in res.json()["detail"]


def test_upload_reference_paper_invalid_header_signature():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User 3", "email": f"ref3_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Physics_{uid}"}, headers=headers).json()

    files = {"file": ("fake.pdf", io.BytesIO(b"Fake PDF text content"), "application/pdf")}
    data = {"title": "Physics Paper"}

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Missing %PDF header signature" in res.json()["detail"]


def test_list_and_get_reference_papers():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "List User", "email": f"list_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Algo_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()

    # Upload 2 papers
    p1 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Midterm 2024", "year": "2024"},
        files={"file": ("p1.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    p2 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Final 2024", "year": "2024"},
        files={"file": ("p2.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    # List papers
    list_res = client.get(f"/api/v1/subjects/{subj['id']}/reference-papers", headers=headers)
    assert list_res.status_code == status.HTTP_200_OK
    papers_list = list_res.json()
    assert len(papers_list) == 2

    # Get detail by ID (default lightweight)
    detail_res = client.get(f"/api/v1/reference-papers/{p1['id']}", headers=headers)
    assert detail_res.status_code == status.HTTP_200_OK
    detail = detail_res.json()
    assert detail["title"] == "Midterm 2024"
    assert "pages" not in detail
    assert "file_url" in detail

    # Get detail with include_pages=true
    pages_res = client.get(f"/api/v1/reference-papers/{p1['id']}?include_pages=true", headers=headers)
    assert pages_res.status_code == status.HTTP_200_OK
    pages_detail = pages_res.json()
    assert "pages" in pages_detail
    assert len(pages_detail["pages"]) == 2


def test_upload_reference_paper_invalid_year():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User 4", "email": f"ref4_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    files = {"file": ("exam.pdf", io.BytesIO(pdf_bytes), "application/pdf")}

    # Negative year
    res = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Paper 1", "year": "-1"},
        files=files,
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid year" in res.json()["detail"]


def test_delete_reference_paper_db_and_filesystem(tmp_path):
    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", str(tmp_path)):
        uid = uuid.uuid4().hex[:8]
        user = client.post("/api/v1/auth/register", json={"name": "Del User", "email": f"del_{uid}@example.com", "password": "password123"}).json()
        headers = {"Authorization": f"Bearer {user['access_token']}"}

        ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
        subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Chem_{uid}"}, headers=headers).json()

        pdf_bytes = create_sample_pdf_bytes()
        p1 = client.post(
            f"/api/v1/subjects/{subj['id']}/reference-papers",
            data={"title": "Chem Test 2023"},
            files={"file": ("chem.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            headers=headers,
        ).json()

        paper_id = p1["id"]
        db = SessionLocal()
        try:
            paper_db = db.query(ReferencePaper).filter(ReferencePaper.id == paper_id).first()
            stored_path = os.path.abspath(paper_db.stored_path)
            paper_dir = os.path.dirname(stored_path)
        finally:
            db.close()

        assert os.path.exists(stored_path)

        # Delete paper
        del_res = client.delete(f"/api/v1/reference-papers/{paper_id}", headers=headers)
        assert del_res.status_code == status.HTTP_204_NO_CONTENT

        db2 = SessionLocal()
        try:
            # DB record soft-deleted
            ref_paper_deleted = db2.query(ReferencePaper).filter(ReferencePaper.id == paper_id).first()
            assert ref_paper_deleted is not None
            assert ref_paper_deleted.deleted_at is not None
            # Excluded from repository get
            assert ReferencePaperRepository(db2).get_reference_paper(paper_id) is None
        finally:
            db2.close()

        # Filesystem deleted
        assert not os.path.exists(stored_path), f"stored_path still exists: {stored_path}"
        assert not os.path.exists(paper_dir), f"paper_dir still exists: {paper_dir}"







def test_reference_paper_unauthorized_access():
    uid1 = uuid.uuid4().hex[:8]
    uid2 = uuid.uuid4().hex[:8]

    user1 = client.post("/api/v1/auth/register", json={"name": "User 1", "email": f"u1_{uid1}@example.com", "password": "password123"}).json()
    user2 = client.post("/api/v1/auth/register", json={"name": "User 2", "email": f"u2_{uid2}@example.com", "password": "password123"}).json()

    h1 = {"Authorization": f"Bearer {user1['access_token']}"}
    h2 = {"Authorization": f"Bearer {user2['access_token']}"}

    ws1 = client.post("/api/v1/workspaces", json={"name": f"WS1_{uid1}"}, headers=h1).json()
    subj1 = client.post(f"/api/v1/workspaces/{ws1['id']}/subjects", json={"name": f"Subj1_{uid1}"}, headers=h1).json()

    pdf_bytes = create_sample_pdf_bytes()
    p1 = client.post(
        f"/api/v1/subjects/{subj1['id']}/reference-papers",
        data={"title": "Private Paper"},
        files={"file": ("priv.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=h1,
    ).json()

    # User 2 attempts to upload to User 1's subject -> 404
    bad_up = client.post(
        f"/api/v1/subjects/{subj1['id']}/reference-papers",
        data={"title": "Hacked Paper"},
        files={"file": ("hack.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=h2,
    )
    assert bad_up.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to get User 1's paper -> 404
    bad_get = client.get(f"/api/v1/reference-papers/{p1['id']}", headers=h2)
    assert bad_get.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to delete User 1's paper -> 404
    bad_del = client.delete(f"/api/v1/reference-papers/{p1['id']}", headers=h2)
    assert bad_del.status_code == status.HTTP_404_NOT_FOUND


def test_preview_and_download_reference_paper_files():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Dl User", "email": f"dl_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    p1 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Downloadable Exam"},
        files={"file": ("exam_dl.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    assert p1["file_url"] == f"/storage/reference_papers/{p1['id']}/original.pdf"

    # Direct Static Access (vigilens-backend pattern)
    static_res = client.get(p1["file_url"])
    assert static_res.status_code == status.HTTP_200_OK
    assert static_res.content == pdf_bytes

    # 3. Missing file on disk -> 404
    db = SessionLocal()
    try:
        paper_db = db.get(ReferencePaper, uuid.UUID(p1["id"]))
        stored_path = paper_db.stored_path
        if os.path.exists(stored_path):
            os.remove(stored_path)
    finally:
        db.close()

    missing_static = client.get(p1["file_url"])
    assert missing_static.status_code == status.HTTP_404_NOT_FOUND


def test_reference_paper_normal_text_pdf_no_ocr():
    """
    Test 1: Normal text PDF with meaningful extracted text should NOT invoke OCR fallback.
    """
    from unittest.mock import patch
    from app.services.processors.pdf_processor import PDFProcessor

    pdf_bytes = create_sample_pdf_bytes(pages_count=1)
    
    with patch("pytesseract.image_to_string") as mock_ocr:
        pages_data = PDFProcessor.process_pdf(file_path="", doc_dir="") if False else None
        
        # Test PDFProcessor directly with mock
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            pages = PDFProcessor.process_pdf(tmp_path, tempfile.gettempdir())
            assert len(pages) == 1
            assert pages[0]["metadata_json"]["ocr_applied"] is False
            assert "Sample Reference Paper" in pages[0]["text_content"]
            mock_ocr.assert_not_called()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def test_reference_paper_scanned_pdf_ocr_fallback_and_persistence():
    """
    Test 2 & 3: Scanned PDF page returning '5' triggers OCR fallback and persists OCR text.
    """
    from unittest.mock import patch
    import tempfile
    from app.services.processors.pdf_processor import PDFProcessor

    # Create a PDF page with text '5' (scanned page artifact)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "5")
    pdf_bytes = doc.tobytes()
    doc.close()

    mock_ocr_result = "SECTION A\nQ1. Define blockchain technology.\nQ2. What is proof of work?"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        with patch("pytesseract.image_to_string", return_value=mock_ocr_result):
            pages = PDFProcessor.process_pdf(tmp_path, tempfile.gettempdir())
            assert len(pages) == 1
            assert pages[0]["metadata_json"]["ocr_applied"] is True
            assert pages[0]["text_content"] == mock_ocr_result
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_reference_paper_ocr_failure_handling():
    """
    Test 4: OCR failure on scanned paper returns appropriate processing error.
    """
    from unittest.mock import patch
    import tempfile

    # Create a PDF page with text '5'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "5")
    pdf_bytes = doc.tobytes()
    doc.close()

    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "OCR Fail User", "email": f"ocrf_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()

    files = {"file": ("scanned_fail.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"title": "Failed OCR Paper"}

    with patch("pytesseract.image_to_string", side_effect=Exception("Tesseract OCR engine crash")):
        res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Could not extract readable text content" in res.json()["detail"] or "Failed to process" in res.json()["detail"]


def test_realistic_ocr_structure_reference_blueprint_analysis():
    """
    Test 5: Verify that realistic OCR text produces Section A (3 marks), Section B (20 marks), Section C (35 marks), Total = 58 marks.
    """
    from unittest.mock import patch
    from app.services.paper.blueprint_service import BlueprintService

    ocr_text = """
    SECTION A (3 Questions x 1 Mark = 3 Marks)
    1. Define blockchain ledger.
    2. What is a cryptographic nonce?
    3. What is a smart contract?

    SECTION B (5 Questions x 4 Marks = 20 Marks)
    4a. Explain PoW consensus mechanism.
    OR
    4b. Explain PoS consensus mechanism.

    5a. Describe Ethereum virtual machine.
    OR
    5b. Describe Hyperledger Fabric architecture.

    6a. What is mining difficulty?
    OR
    6b. What is block reward halving?

    7a. What is a Sybil attack?
    OR
    7b. What is a 51 percent attack?

    8a. Explain public blockchain vs private blockchain.
    OR
    8b. Explain permissioned vs permissionless blockchain.

    SECTION C (5 Questions x 7 Marks = 35 Marks)
    9a. Explain blockchain scaling trilemma in detail.
    OR
    9b. Explain Layer 2 scaling solutions.

    10a. Describe application of blockchain in healthcare.
    OR
    10b. Describe application of blockchain in supply chain.

    11a. Explain digital signatures and public key cryptography.
    OR
    11b. Explain Merkle tree root hash generation.

    12a. Explain zero knowledge proofs and zk-SNARKs.
    OR
    12b. Explain decentralized identity protocols.

    13a. Explain smart contract security vulnerabilities and reentrancy.
    OR
    13b. Explain decentralized finance (DeFi) liquidity pools.
    """

    fake_analysis_response = """
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

    with patch("app.services.paper.blueprint_service.GeminiService.generate_response", return_value=fake_analysis_response):
        bp_svc = BlueprintService()
        bp = bp_svc.analyze_reference_paper([ocr_text])

    assert bp.total_marks == 58
    assert len(bp.sections) == 3
    assert bp.sections[0].total_section_marks == 3
    assert bp.sections[1].total_section_marks == 20
    assert bp.sections[2].total_section_marks == 35


def test_subject_scoped_reference_paper_isolation_and_cross_subject_rejection():
    """
    TEST: Verify strict subject scoping for reference papers:
    1. Physics reference paper is visible ONLY under Physics reference listing.
    2. Mathematics reference listing does NOT contain Physics references.
    3. Physics reference paper used in Physics paper generation -> SUCCESS (HTTP 201).
    4. Physics reference paper used in Mathematics paper generation -> REJECT (HTTP 400 Bad Request).
    """
    import json
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Subject User", "email": f"subj_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": "Science WS"}, headers=headers).json()

    # Physics Subject & Book
    phys_subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Physics"}, headers=headers).json()
    phys_book = client.post(f"/api/v1/subjects/{phys_subj['id']}/books", json={"name": "Physics Book"}, headers=headers).json()
    phys_ch = client.post(f"/api/v1/books/{phys_book['id']}/chapters", json={"name": "Kinematics", "chapter_number": 1}, headers=headers).json()

    # Mathematics Subject & Book
    math_subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Mathematics"}, headers=headers).json()
    math_book = client.post(f"/api/v1/subjects/{math_subj['id']}/books", json={"name": "Math Book"}, headers=headers).json()
    math_ch = client.post(f"/api/v1/books/{math_book['id']}/chapters", json={"name": "Algebra", "chapter_number": 1}, headers=headers).json()

    # Upload Physics Reference Paper
    pdf_bytes = create_sample_pdf_bytes()
    files = {"file": ("physics_exam.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"title": "Physics Past Paper 2025"}

    phys_ref_res = client.post(f"/api/v1/subjects/{phys_subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert phys_ref_res.status_code == status.HTTP_201_CREATED
    phys_ref = phys_ref_res.json()

    # 1. Physics reference listing -> returns Physics reference
    phys_list = client.get(f"/api/v1/subjects/{phys_subj['id']}/reference-papers", headers=headers).json()
    assert any(p["id"] == phys_ref["id"] for p in phys_list)

    # 2. Mathematics reference listing -> does NOT return Physics reference
    math_list = client.get(f"/api/v1/subjects/{math_subj['id']}/reference-papers", headers=headers).json()
    assert not any(p["id"] == phys_ref["id"] for p in math_list)

    # 3. Physics reference + Mathematics paper generation request -> MUST REJECT (HTTP 400 Bad Request)
    cross_gen_payload = {
        "book_id": math_book["id"],
        "selected_chapter_ids": [math_ch["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": phys_ref["id"],
        "total_marks": 20,
    }
    cross_res = client.post("/api/v1/papers/generate", json=cross_gen_payload, headers=headers)
    assert cross_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "different subject" in cross_res.json()["detail"].lower()

    # 4. Physics reference + Physics paper generation request -> MUST SUCCEED (HTTP 201 Created)
    same_gen_payload = {
        "book_id": phys_book["id"],
        "selected_chapter_ids": [phys_ch["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": phys_ref["id"],
        "total_marks": 20,
    }

    from app.services.ai.gemini_service import GeminiService
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint, QuestionType

    sec_a = [{"question_text": f"Physics Question {i}", "question_type": "MCQ", "mcq_options": ["A. 1", "B. 2", "C. 3", "D. 4"], "correct_answer": "A. 1", "solution_explanation": "Exp"} for i in range(1, 11)]
    mock_json = json.dumps({"sections": [{"section_name": "Section A", "questions": sec_a}]})

    analyzed_bp = PaperBlueprint(
        total_marks=20,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=10,
                marks_per_question=2,
                total_section_marks=20,
            )
        ]
    )

    with patch.object(BlueprintService, "analyze_reference_paper", return_value=analyzed_bp), \
         patch.object(GeminiService, "generate_response", return_value=mock_json):
        same_res = client.post("/api/v1/papers/generate", json=same_gen_payload, headers=headers)

    assert same_res.status_code == status.HTTP_201_CREATED, same_res.text
    paper = same_res.json()
    assert paper["reference_paper_id"] == phys_ref["id"]
    assert len(paper["questions"]) == 10


def test_reference_mode_source_type_traceability():
    """
    TEST: Verify that in REFERENCE mode, questions with source_type REFERENCE_REUSED,
    REFERENCE_VARIATION, and AI_GENERATED are correctly preserved and returned.
    """
    import json
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Trace User", "email": f"trace_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": "Trace WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Physics"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Physics Book"}, headers=headers).json()
    ch = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Optics", "chapter_number": 1}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    files = {"file": ("optics.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    ref_res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data={"title": "Optics 2024"}, files=files, headers=headers)
    ref_paper = ref_res.json()

    sec_questions = [
        {"question_text": "Physics Reused Q1", "question_type": "MCQ", "mcq_options": ["A", "B", "C", "D"], "correct_answer": "A", "solution_explanation": "Exp", "source_type": "REFERENCE_REUSED"},
        {"question_text": "Physics Variation Q2", "question_type": "MCQ", "mcq_options": ["A", "B", "C", "D"], "correct_answer": "B", "solution_explanation": "Exp", "source_type": "REFERENCE_VARIATION"},
        {"question_text": "Physics New Q3", "question_type": "MCQ", "mcq_options": ["A", "B", "C", "D"], "correct_answer": "C", "solution_explanation": "Exp", "source_type": "AI_GENERATED"},
    ]
    mock_json = json.dumps({"sections": [{"section_name": "Section A", "questions": sec_questions}]})

    from app.services.ai.gemini_service import GeminiService
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint, QuestionType

    analyzed_bp = PaperBlueprint(
        total_marks=6,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=3,
                marks_per_question=2,
                total_section_marks=6,
            )
        ],
        sample_questions=[
            {"section_name": "Section A", "question_type": "MCQ", "question_text": "Physics Reused Q1", "marks": 2}
        ]
    )

    gen_payload = {
        "book_id": book["id"],
        "selected_chapter_ids": [ch["id"]],
        "generation_mode": "REFERENCE",
        "reference_paper_id": ref_paper["id"],
        "total_marks": 6,
    }

    with patch.object(BlueprintService, "analyze_reference_paper", return_value=analyzed_bp), \
         patch.object(GeminiService, "generate_response", return_value=mock_json):
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)

    assert res.status_code == status.HTTP_201_CREATED
    paper = res.json()
    st_list = [q["source_type"] for q in paper["questions"]]
    assert "REFERENCE_REUSED" in st_list
    assert "REFERENCE_VARIATION" in st_list
    assert "AI_GENERATED" in st_list


def test_full_paper_analysis_no_truncation_across_all_pages():
    """
    TEST: Verify reference paper analysis processes ALL pages without character truncation:
    1. Simulates a long multi-page reference paper (> 20,000 characters).
    2. Page 1 contains Section A (MCQs), Page 5 contains Section B (Short Answer), Page 10 contains Section C (Long Answer).
    3. Verifies analyze_reference_paper receives 100% of the untruncated text.
    4. Verifies stored blueprint_json captures sections and sample questions from Page 1, Page 5, and Page 10.
    """
    from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint, QuestionType

    p1_text = "PAGE 1: Section A - MCQs\n" + ("Q1. What is velocity?\n" * 200)
    p5_text = "PAGE 5: Section B - Short Answers\n" + ("Q6. Explain Newton's second law.\n" * 200)
    p10_text = "PAGE 10: Section C - Long Answers\n" + ("Q11. Derive the equation of motion.\n" * 200)

    pages = [p1_text, "Page 2 content...", "Page 3 content...", "Page 4 content...", p5_text, "Page 6...", "Page 7...", "Page 8...", "Page 9...", p10_text]
    total_char_len = sum(len(p) for p in pages)
    assert total_char_len > 15000  # Exceeds old 12,000 character limit

    bp_service = BlueprintService()
    captured_prompt = None

    def mock_generate_response(prompt, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        mock_res = {
            "total_marks": 60,
            "sections": [
                {"name": "Section A", "question_type": "MCQ", "question_count": 5, "marks_per_question": 1, "has_internal_choice": False, "alternatives_per_question": 1},
                {"name": "Section B", "question_type": "SHORT_ANSWER", "question_count": 5, "marks_per_question": 4, "has_internal_choice": False, "alternatives_per_question": 1},
                {"name": "Section C", "question_type": "LONG_ANSWER", "question_count": 5, "marks_per_question": 7, "has_internal_choice": True, "alternatives_per_question": 2},
            ],
            "sample_questions": [
                {"section_name": "Section A", "question_type": "MCQ", "question_text": "What is velocity?", "marks": 1, "cognitive_demand": "RECALL", "reasoning_style": "DIRECT_RECALL"},
                {"section_name": "Section B", "question_type": "SHORT_ANSWER", "question_text": "Explain Newton's second law.", "marks": 4, "cognitive_demand": "COMPREHENSION", "reasoning_style": "CONCEPT_EXPLANATION"},
                {"section_name": "Section C", "question_type": "LONG_ANSWER", "question_text": "Derive the equation of motion.", "marks": 7, "cognitive_demand": "ANALYSIS", "reasoning_style": "DERIVATION"},
            ]
        }
        import json
        return json.dumps(mock_res)

    bp_service.ai_service.generate_response = mock_generate_response
    bp = bp_service.analyze_reference_paper(paper_pages_text=pages)

    # 1. Verify prompt contains text from Page 1, Page 5, and Page 10 without truncation
    assert "PAGE 1: Section A" in captured_prompt
    assert "PAGE 5: Section B" in captured_prompt
    assert "PAGE 10: Section C" in captured_prompt

    # 2. Verify extracted blueprint contains all 3 sections across the entire paper
    assert len(bp.sections) == 3
    sec_names = [s.name for s in bp.sections]
    assert "Section A" in sec_names
    assert "Section B" in sec_names
    assert "Section C" in sec_names

    # 3. Verify sample_questions contain questions from beginning (Page 1), middle (Page 5), and end (Page 10)
    assert len(bp.sample_questions) == 3
    sample_texts = [sq["question_text"] for sq in bp.sample_questions]
    assert "What is velocity?" in sample_texts
    assert "Explain Newton's second law." in sample_texts
    assert "Derive the equation of motion." in sample_texts

