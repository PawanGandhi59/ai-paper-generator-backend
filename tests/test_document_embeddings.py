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
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.worker import generate_document_embeddings, process_document

client = TestClient(app)


def create_sample_pdf_bytes(pages_count: int = 3) -> bytes:
    doc = fitz.open()
    for i in range(pages_count):
        page = doc.new_page()
        page.insert_text((50, 50), f"Sample Embedding Test Content on Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def setup_test_hierarchy():
    uid = uuid.uuid4().hex[:8]
    user_res = client.post(
        "/api/v1/auth/register",
        json={"name": "Embedding User", "email": f"embed_{uid}@example.com", "password": "password123"},
    ).json()
    token = user_res["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Embeddings Book"}, headers=headers).json()

    return headers, book


def test_document_embedding_endpoints_and_lifecycle():
    """
    TEST: Verify decoupled embedding endpoints and status progression:
    - Main document flow sets READY and embedding_status PROCESSING
    - GET /documents/{id}/embeddings reports status
    - POST /documents/{id}/embeddings triggers/re-triggers embedding
    - Completed task updates embedding_status to COMPLETED
    """
    headers, book = setup_test_hierarchy()

    pdf_bytes = create_sample_pdf_bytes(pages_count=3)
    files = {"file": ("test_doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"book_id": book["id"]}

    # Upload document with mocked async dispatch
    with patch("app.services.document_service.process_document.delay"):
        up_res = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers)
        assert up_res.status_code == 202
        doc_data = up_res.json()
        doc_id = doc_data["id"]
        assert doc_data["status"] == "UPLOADED"

    mock_vectors = [[0.1] * 768 for _ in range(10)]

    # 1. Run main process_document pipeline (with embedding task isolated)
    with patch("app.worker.generate_document_embeddings.delay") as mock_embed_delay:
        proc_res = process_document(doc_id)
        assert proc_res["status"] == "PROCESSED"
        # Verify background embedding task was dispatched
        mock_embed_delay.assert_called_once_with(doc_id)

    # 2. Check document status via GET /documents/{doc_id}
    doc_res = client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert doc_res.status_code == 200
    doc_info = doc_res.json()
    assert doc_info["processing_status"] == "READY"
    assert doc_info["embedding_status"] == "PROCESSING"

    # 3. Check status via dedicated GET /documents/{doc_id}/embeddings
    embed_stat_res = client.get(f"/api/v1/documents/{doc_id}/embeddings", headers=headers)
    assert embed_stat_res.status_code == 200
    embed_stat = embed_stat_res.json()
    assert embed_stat["embedding_status"] == "PROCESSING"
    assert embed_stat["total_chunks"] == 3
    assert embed_stat["embedded_chunks"] == 0

    # 4. Execute decoupled generate_document_embeddings task
    with patch.object(GeminiEmbeddingService, "generate_embeddings_batch", return_value=mock_vectors):
        embed_res = generate_document_embeddings(doc_id)
        assert embed_res["status"] == "COMPLETED"
        assert embed_res["chunks_embedded"] == 3

    # 5. Verify COMPLETED embedding status and timestamp
    embed_stat_completed = client.get(f"/api/v1/documents/{doc_id}/embeddings", headers=headers).json()
    assert embed_stat_completed["embedding_status"] == "COMPLETED"
    assert embed_stat_completed["total_chunks"] == 3
    assert embed_stat_completed["embedded_chunks"] == 3
    assert embed_stat_completed["embedding_completed_at"] is not None

    # 6. Test POST /documents/{doc_id}/embeddings re-trigger endpoint
    with patch("app.services.document_service.generate_document_embeddings.delay") as mock_retrigger:
        trigger_res = client.post(f"/api/v1/documents/{doc_id}/embeddings", headers=headers)
        assert trigger_res.status_code == 202
        assert trigger_res.json()["embedding_status"] == "PROCESSING"
        mock_retrigger.assert_called_once_with(doc_id)


def test_embedding_failure_preserves_document_and_chunks():
    """
    TEST: Verify that if embedding task fails permanently or runs out of retries:
    - Document status remains READY
    - Chunks, pages, and physical files are NEVER deleted
    - embedding_status is marked FAILED with error message
    """
    headers, book = setup_test_hierarchy()

    pdf_bytes = create_sample_pdf_bytes(pages_count=2)
    files = {"file": ("preserve_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"book_id": book["id"]}

    with patch("app.services.document_service.process_document.delay"):
        doc_id = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers).json()["id"]

    with patch("app.worker.generate_document_embeddings.delay"):
        process_document(doc_id)

    # Simulate unrecoverable embedding error
    with patch.object(
        GeminiEmbeddingService,
        "generate_embeddings_batch",
        side_effect=RuntimeError("Google Gemini API Quota Exceeded"),
    ), patch("app.worker.cleanup_failed_document") as mock_cleanup:
        embed_res = generate_document_embeddings(doc_id)
        assert embed_res["status"] == "FAILED"
        mock_cleanup.assert_not_called()

    # Verify document and chunks still exist in DB
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc is not None
        assert doc.processing_status == "READY"
        assert doc.embedding_status == "FAILED"
        assert "Google Gemini API Quota Exceeded" in doc.embedding_error

        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.embedding is None
    finally:
        db.close()


def test_immediate_abort_and_cleanup_on_rpd_daily_quota():
    """
    TEST: Verify that when Google Gemini returns a 429 Daily Quota (RPD) error:
    - Worker immediately halts without wasting retries/sleeping.
    - Any partial embeddings already written are wiped (cleared to None).
    - Document remains intact in READY state.
    - Status is marked FAILED with a clear daily quota explanation.
    """
    from app.services.ai.gemini_service import GeminiDailyQuotaExhaustedError, is_daily_quota_error

    headers, book = setup_test_hierarchy()
    pdf_bytes = create_sample_pdf_bytes(pages_count=2)
    files = {"file": ("rpd_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"book_id": book["id"]}

    with patch("app.services.document_service.process_document.delay"):
        doc_id = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers).json()["id"]

    with patch("app.worker.generate_document_embeddings.delay"):
        process_document(doc_id)

    db = SessionLocal()
    try:
        # Pre-assign an embedding to chunk 1 to simulate a partial embedding run
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        assert len(chunks) == 2
        chunks[0].embedding = [0.42] * 768
        db.commit()

        # Verify partial embedding is present
        db.refresh(chunks[0])
        assert chunks[0].embedding is not None

        # Simulate Google's exact RPD error payload
        raw_google_rpd_error = (
            "Error embedding content (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. "
            "{'error': {'code': 429, 'message': 'Quota exceeded for metric: "
            "generativelanguage.googleapis.com/embed_content_free_tier_requests, limit: 1000, model: gemini-embedding-2', "
            "'status': 'RESOURCE_EXHAUSTED', 'details': [{'violations': [{'quotaId': 'EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier'}]}]}}"
        )

        assert is_daily_quota_error(raw_google_rpd_error) is True

        with patch.object(
            GeminiEmbeddingService,
            "generate_embeddings_batch",
            side_effect=GeminiDailyQuotaExhaustedError(f"Daily quota reached: {raw_google_rpd_error}"),
        ), patch("app.worker.cleanup_failed_document") as mock_cleanup:
            res = generate_document_embeddings(doc_id)
            assert res["status"] == "FAILED"
            assert res.get("reason") == "DAILY_QUOTA_EXHAUSTED"
            mock_cleanup.assert_not_called()

        # Verify document preserved, embedding_status FAILED, and partial embeddings wiped
        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc.processing_status == "READY"
        assert doc.embedding_status == "FAILED"
        assert "daily" in doc.embedding_error.lower() or "rpd" in doc.embedding_error.lower()

        # Expire session identity map to fetch fresh values committed by worker
        db.expire_all()
        refreshed_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        for ch in refreshed_chunks:
            assert ch.embedding is None

    finally:
        db.close()


def test_is_daily_quota_error_detection():
    """
    TEST: Verify is_daily_quota_error distinguishes RPD (daily) from RPM (minute) errors.
    """
    from app.services.ai.gemini_service import is_daily_quota_error

    # True RPD cases
    assert is_daily_quota_error("EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier") is True
    assert is_daily_quota_error("generativelanguage.googleapis.com/embed_content_free_tier_requests") is True
    assert is_daily_quota_error("Quota exceeded for metric 'generate_content_requests_per_day'") is True
    assert is_daily_quota_error("Daily quota exceeded for user") is True

    # False RPM / TPM cases
    assert is_daily_quota_error("generate_content_requests_per_minute") is False
    assert is_daily_quota_error("Tokens per minute exceeded") is False
    assert is_daily_quota_error("429 RESOURCE_EXHAUSTED: Rate limit reached. Please retry in 15s") is False

