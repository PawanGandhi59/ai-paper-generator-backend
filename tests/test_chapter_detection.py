import io
import uuid
from unittest.mock import MagicMock, patch

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.chapter import Chapter
from app.models.document import Document, DocumentChunk, DocumentPage
from app.schemas.chapter import ChapterCreate, ChapterUpdate
from app.services.ai.chapter_detection_service import (
    ChapterDetectionItem,
    ChapterDetectionResult,
    ChapterDetectionService,
)
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService

client = TestClient(app)


def create_sample_pdf_bytes(pages_count: int = 5) -> bytes:
    doc = fitz.open()
    for i in range(pages_count):
        page = doc.new_page()
        page.insert_text((50, 50), f"Sample Page Content for Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_chapter_schema_validation():
    # Valid ranges
    c1 = ChapterCreate(chapter_number=1, name="Ch1", start_page=1, end_page=10)
    assert c1.start_page == 1
    assert c1.end_page == 10

    # Nullable ranges allowed
    c2 = ChapterCreate(chapter_number=2, name="Ch2")
    assert c2.start_page is None
    assert c2.end_page is None

    # Invalid range rejected
    with pytest.raises(ValueError):
        ChapterCreate(chapter_number=3, name="Ch3", start_page=20, end_page=10)

    with pytest.raises(ValueError):
        ChapterUpdate(start_page=50, end_page=30)


def test_chapter_detection_toc_stage():
    pages = [
        DocumentPage(
            document_id=uuid.uuid4(),
            page_number=1,
            text_content="Table of Contents\nChapter 1 Introduction ........ Page 1\nChapter 2 Architecture ........ Page 3",
        ),
        DocumentPage(document_id=uuid.uuid4(), page_number=2, text_content="Preface content..."),
        DocumentPage(document_id=uuid.uuid4(), page_number=3, text_content="Architecture text..."),
        DocumentPage(document_id=uuid.uuid4(), page_number=4, text_content="More text..."),
        DocumentPage(document_id=uuid.uuid4(), page_number=5, text_content="Final text..."),
    ]

    mock_gemini = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"chapters": [{"chapter_number": 1, "name": "Introduction", "start_page": 1}, {"chapter_number": 2, "name": "Architecture", "start_page": 3}]}'
    mock_gemini.client.models.generate_content.return_value = mock_response
    mock_gemini.model_name = "gemini-2.5-flash"

    service = ChapterDetectionService(gemini_service=mock_gemini)
    results = service.detect_chapters(pages)

    assert len(results) == 2
    assert results[0].chapter_number == 1
    assert results[0].name == "Introduction"
    assert results[0].start_page == 1
    assert results[1].chapter_number == 2
    assert results[1].name == "Architecture"
    assert results[1].start_page == 3


def test_chapter_detection_toc_after_page_35():
    # TOC located at page 77
    pages = []
    for p in range(1, 100):
        if p == 77:
            txt = "Table of Contents\n1. Papa's Spectacles ... Page 1\n2. Gone with the Scooter ... Page 11\n7. Gilli Danda ... Page 65"
        else:
            txt = f"Page {p} content"
        pages.append(DocumentPage(document_id=uuid.uuid4(), page_number=p, text_content=txt))

    mock_gemini = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"chapters": [{"chapter_number": 1, "name": "Papa\'s Spectacles", "start_page": 1}, {"chapter_number": 2, "name": "Gone with the Scooter", "start_page": 11}, {"chapter_number": 7, "name": "Gilli Danda", "start_page": 65}]}'
    mock_gemini.client.models.generate_content.return_value = mock_response
    mock_gemini.model_name = "gemini-2.5-flash"

    service = ChapterDetectionService(gemini_service=mock_gemini)
    results = service.detect_chapters(pages)

    assert len(results) == 3
    assert results[0].start_page == 1
    assert results[1].start_page == 11
    assert results[2].start_page == 65
    assert results[2].name == "Gilli Danda"


def test_chapter_detection_heading_candidate_stage():
    pages = [
        DocumentPage(document_id=uuid.uuid4(), page_number=1, text_content="Title Page"),
        DocumentPage(document_id=uuid.uuid4(), page_number=5, text_content="CHAPTER 1 Fundamentals\nSome text..."),
        DocumentPage(document_id=uuid.uuid4(), page_number=25, text_content="CHAPTER 2 Advanced Concepts\nMore text..."),
    ]
    for p in range(2, 31):
        if p not in [1, 5, 25]:
            pages.append(DocumentPage(document_id=uuid.uuid4(), page_number=p, text_content=f"Page {p} content"))

    mock_gemini = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"chapters": [{"chapter_number": 1, "name": "Fundamentals", "start_page": 5}, {"chapter_number": 2, "name": "Advanced Concepts", "start_page": 25}]}'
    mock_gemini.client.models.generate_content.return_value = mock_response
    mock_gemini.model_name = "gemini-2.5-flash"

    service = ChapterDetectionService(gemini_service=mock_gemini)
    results = service.detect_chapters(pages)

    assert len(results) == 2
    assert results[0].start_page == 5
    assert results[1].start_page == 25


def test_chapter_detection_gemini_failure_fallback():
    pages = [DocumentPage(document_id=uuid.uuid4(), page_number=1, text_content="Chapter 1 Sample")]

    mock_gemini = MagicMock()
    mock_gemini.client.models.generate_content.side_effect = Exception("API rate limit error")

    service = ChapterDetectionService(gemini_service=mock_gemini)
    results = service.detect_chapters(pages)

    assert results == []


def test_worker_complete_book_chunk_chapter_assignment():
    uid = uuid.uuid4().hex[:8]
    user_res = client.post("/api/v1/auth/register", json={"name": "Book User", "email": f"book_{uid}@example.com", "password": "password123"}).json()
    token = user_res["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"DBMS_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Complete Book"}, headers=headers).json()

    pdf_data = create_sample_pdf_bytes(pages_count=5)
    files = {"file": ("complete_book.pdf", io.BytesIO(pdf_data), "application/pdf")}
    data = {"book_id": book["id"]}

    mock_items = [
        ChapterDetectionItem(chapter_number=1, name="Intro", start_page=1),
        ChapterDetectionItem(chapter_number=2, name="Data Models", start_page=3),
    ]

    with patch("app.services.document_service.process_document.delay"):
        up_res = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers).json()
        doc_id = up_res["id"]

    mock_vectors = [[0.1] * 768 for _ in range(50)]
    with patch.object(ChapterDetectionService, "detect_chapters", return_value=mock_items), \
         patch.object(GeminiEmbeddingService, "generate_embeddings_batch", return_value=mock_vectors), \
         patch("app.worker.generate_document_embeddings.delay", side_effect=Exception("Async fallback")):
        from app.worker import process_document
        res = process_document(doc_id)

    assert res["status"] == "PROCESSED"

    db = SessionLocal()
    try:
        pages = db.query(DocumentPage).filter(DocumentPage.document_id == doc_id).all()
        assert len(pages) == 5

        chapters = db.query(Chapter).filter(Chapter.book_id == book["id"]).all()
        assert len(chapters) == 2
        ch1 = next(c for c in chapters if c.chapter_number == 1)
        ch2 = next(c for c in chapters if c.chapter_number == 2)
        assert ch1.name == "Intro"
        assert ch1.start_page == 1
        assert ch1.end_page == 2
        assert ch2.name == "Data Models"
        assert ch2.start_page == 3
        assert ch2.end_page == 5

        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        assert len(chunks) > 0
        for chk in chunks:
            assert chk.chapter_id in [ch1.id, ch2.id]
    finally:
        db.close()


def test_explicit_chapter_upload_bypasses_detection():
    uid = uuid.uuid4().hex[:8]
    user_res = client.post("/api/v1/auth/register", json={"name": "Explicit User", "email": f"exp_{uid}@example.com", "password": "password123"}).json()
    token = user_res["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Explicit Book"}, headers=headers).json()
    ch = client.post(f"/api/v1/books/{book['id']}/chapters", json={"chapter_number": 1, "name": "Chapter 1"}, headers=headers).json()

    pdf_data = create_sample_pdf_bytes(pages_count=2)
    files = {"file": ("ch1.pdf", io.BytesIO(pdf_data), "application/pdf")}
    data = {"book_id": book["id"], "chapter_id": ch["id"]}

    with patch("app.services.document_service.process_document.delay"):
        up_res = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers).json()
        doc_id = up_res["id"]

    mock_detector = MagicMock()
    mock_vectors = [[0.1] * 768 for _ in range(50)]
    with patch("app.worker.ChapterDetectionService", return_value=mock_detector), \
         patch.object(GeminiEmbeddingService, "generate_embeddings_batch", return_value=mock_vectors), \
         patch("app.worker.generate_document_embeddings.delay", side_effect=Exception("Async fallback")):
        from app.worker import process_document
        res = process_document(doc_id)

    assert res["status"] == "PROCESSED"
    # Ensure chapter detector was NOT called
    mock_detector.detect_chapters.assert_not_called()

    db = SessionLocal()
    try:
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        assert len(chunks) > 0
        for chk in chunks:
            assert str(chk.chapter_id) == ch["id"]
    finally:
        db.close()


def test_worker_retry_idempotency():
    uid = uuid.uuid4().hex[:8]
    user_res = client.post("/api/v1/auth/register", json={"name": "Retry User", "email": f"retry_{uid}@example.com", "password": "password123"}).json()
    token = user_res["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"OS_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "OS Book"}, headers=headers).json()

    pdf_data = create_sample_pdf_bytes(pages_count=3)
    files = {"file": ("os_book.pdf", io.BytesIO(pdf_data), "application/pdf")}
    data = {"book_id": book["id"]}

    mock_items = [
        ChapterDetectionItem(chapter_number=1, name="Processes", start_page=1),
    ]
    mock_vectors = [[0.1] * 768 for _ in range(50)]

    with patch("app.services.document_service.process_document.delay"):
        up_res = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers).json()
        doc_id = up_res["id"]

    with patch.object(ChapterDetectionService, "detect_chapters", return_value=mock_items), \
         patch.object(GeminiEmbeddingService, "generate_embeddings_batch", return_value=mock_vectors), \
         patch("app.worker.generate_document_embeddings.delay", side_effect=Exception("Async fallback")):
        from app.worker import process_document, generate_document_embeddings
        process_document(doc_id)

        # Re-run embedding task (simulating worker retry)
        generate_document_embeddings(doc_id)

    db = SessionLocal()
    try:
        chapters = db.query(Chapter).filter(Chapter.book_id == book["id"]).all()
        assert len(chapters) == 1
        assert chapters[0].chapter_number == 1
    finally:
        db.close()


def test_gemini_embedding_no_mock():
    # Verify generate_deterministic_mock_vector is removed
    import app.services.embeddings.gemini_embedding_service as gem_module
    assert not hasattr(gem_module, "generate_deterministic_mock_vector")

    # Missing API key raises ValueError
    with pytest.raises(ValueError):
        GeminiEmbeddingService(api_key="")

    # API failure raises RuntimeError
    mock_service = GeminiEmbeddingService(api_key="fake_key")
    with patch.object(mock_service, "client") as mock_client:
        mock_client.models.embed_content.side_effect = Exception("API quota exceeded")

        with pytest.raises(RuntimeError):
            mock_service.generate_embeddings_batch(["test text"])
