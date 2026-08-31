import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document, DocumentChunk, DocumentPage
from app.services.embeddings.gemini_embedding_service import (
    GeminiEmbeddingService,
    RedisGeminiRateLimiter,
)


def test_redis_rate_limiter_rpm_capacity_check():
    """
    TEST: Verify RedisGeminiRateLimiter enforces RPM limit (90 RPM).
    """
    mock_redis = MagicMock()
    # Simulate first request allowed, second request throttled for 2.5 seconds, then allowed
    mock_redis.eval.side_effect = [
        [1, "0", 1, 100],  # Allowed
        [0, "2.5", 90, 50000],  # RPM limit reached -> sleep 2.5s
        [1, "0", 89, 49000],  # Retry after window clears -> Allowed
    ]

    limiter = RedisGeminiRateLimiter(max_rpm=90, max_tpm=55000, window_seconds=60.0, redis_client=mock_redis)

    with patch("time.sleep") as mock_sleep:
        limiter.acquire(token_count=100)  # Allowed immediately
        assert not mock_sleep.called

        limiter.acquire(token_count=100)  # Requires sleep
        mock_sleep.assert_called_once_with(2.5)


def test_redis_rate_limiter_tpm_capacity_check():
    """
    TEST: Verify RedisGeminiRateLimiter enforces TPM limit (55,000 TPM).
    """
    mock_redis = MagicMock()
    mock_redis.eval.side_effect = [
        [0, "5.0", 10, 55000],  # TPM limit reached -> sleep 5.0s
        [1, "0", 11, 20000],  # Allowed after window clears
    ]

    limiter = RedisGeminiRateLimiter(max_rpm=90, max_tpm=55000, window_seconds=60.0, redis_client=mock_redis)

    with patch("time.sleep") as mock_sleep:
        limiter.acquire(token_count=10000)
        mock_sleep.assert_called_once_with(5.0)


def test_embedding_service_429_retry_handling():
    """
    TEST: Verify GeminiEmbeddingService handles unexpected 429 with backoff retries instead of immediate failure.
    """
    mock_gemini = GeminiEmbeddingService(api_key="fake_key")
    mock_gemini.lc_embeddings = None
    mock_client = MagicMock()

    # First call raises 429 RESOURCE_EXHAUSTED, second succeeds
    fail_res = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")
    success_emb = MagicMock()
    success_emb.values = [0.1] * 768
    success_res = MagicMock(embeddings=[success_emb])

    mock_client.models.embed_content.side_effect = [fail_res, success_res]
    mock_gemini.client = mock_client

    with patch("time.sleep") as mock_sleep:
        res = mock_gemini.generate_embeddings_batch(["Sample text for embedding"])

    assert len(res) == 1
    assert len(res[0]) == 768
    assert mock_sleep.called


def test_document_preserved_on_rate_limit_failure():
    """
    TEST: Verify that a rate limit / 429 failure in generate_document_embeddings triggers a Celery retry
    and does NOT call cleanup_failed_document, preserving uploaded files and extracted DocumentPages.
    """
    from app.worker import generate_document_embeddings

    doc_id = uuid.uuid4()
    doc_id_str = str(doc_id)

    mock_db = MagicMock()
    mock_doc = MagicMock(id=doc_id, deleted_at=None, chapter_id=None, chapter=None)
    mock_doc.book.deleted_at = None
    mock_doc.book.subject.deleted_at = None

    mock_doc_repo = MagicMock()
    mock_doc_repo.get_document_by_id.return_value = mock_doc
    mock_doc_repo.get_document_pages.return_value = [
        DocumentPage(document_id=doc_id, page_number=1, text_content="Page 1 text")
    ]
    mock_doc_repo.save_document_chunks.return_value = [
        DocumentChunk(id=uuid.uuid4(), document_id=doc_id, content="Chunk 1", embedding=None)
    ]

    with patch("app.worker.SessionLocal", return_value=mock_db), \
         patch("app.worker.DocumentRepository", return_value=mock_doc_repo), \
         patch.object(GeminiEmbeddingService, "generate_embeddings_batch", side_effect=Exception("429 RESOURCE_EXHAUSTED")), \
         patch("app.worker.cleanup_failed_document") as mock_cleanup:

        # Invoking Celery task on 429 raises Celery Retry exception
        with pytest.raises(Exception):
            generate_document_embeddings(doc_id_str)

        # Ensure cleanup_failed_document was NOT called!
        mock_cleanup.assert_not_called()


def test_permanent_error_invokes_cleanup_failed_document():
    """
    TEST: Verify that a genuine PERMANENT failure still invokes cleanup_failed_document.
    """
    from app.worker import PERMANENT_ERRORS, generate_document_embeddings

    doc_id = uuid.uuid4()
    doc_id_str = str(doc_id)

    mock_db = MagicMock()
    mock_doc = MagicMock(id=doc_id, deleted_at=None, chapter_id=None, chapter=None)
    mock_doc.book.deleted_at = None
    mock_doc.book.subject.deleted_at = None

    mock_doc_repo = MagicMock()
    mock_doc_repo.get_document_by_id.return_value = mock_doc
    mock_doc_repo.get_document_pages.return_value = [
        DocumentPage(document_id=doc_id, page_number=1, text_content="Page 1 text")
    ]

    permanent_error = PERMANENT_ERRORS[0]("Corrupted PDF structure")

    with patch("app.worker.SessionLocal", return_value=mock_db), \
         patch("app.worker.DocumentRepository", return_value=mock_doc_repo), \
         patch("app.worker.ChunkingService.chunk_document_pages", side_effect=permanent_error), \
         patch("app.worker.cleanup_failed_document") as mock_cleanup:

        res = generate_document_embeddings(doc_id_str)

        assert res["status"] == "FAILED"
        mock_cleanup.assert_called_once_with(mock_db, doc_id_str, str(permanent_error))


def test_resumable_embedding_skips_already_embedded_chunks():
    """
    TEST: Verify generate_document_embeddings skips already embedded chunks on task retry/resume.
    """
    from app.worker import generate_document_embeddings

    doc_id = uuid.uuid4()
    doc_id_str = str(doc_id)

    mock_db = MagicMock()
    mock_doc = MagicMock(id=doc_id, deleted_at=None, chapter_id=None, chapter=None)
    mock_doc.book.deleted_at = None
    mock_doc.book.subject.deleted_at = None

    c1 = DocumentChunk(id=uuid.uuid4(), document_id=doc_id, content="Chunk 1", embedding=[0.1] * 768)  # Already embedded
    c2 = DocumentChunk(id=uuid.uuid4(), document_id=doc_id, content="Chunk 2", embedding=None)  # Needs embedding

    mock_doc_repo = MagicMock()
    mock_doc_repo.get_document_by_id.return_value = mock_doc
    mock_doc_repo.get_document_pages.return_value = [DocumentPage(document_id=doc_id, page_number=1, text_content="Text")]
    mock_doc_repo.save_document_chunks.return_value = [c1, c2]

    with patch("app.worker.SessionLocal", return_value=mock_db), \
         patch("app.worker.DocumentRepository", return_value=mock_doc_repo), \
         patch.object(GeminiEmbeddingService, "generate_embeddings_batch", return_value=[[0.2] * 768]) as mock_batch_gen:

        res = generate_document_embeddings(doc_id_str)

        assert res["status"] == "READY"
        # Only chunk 2 was passed to generate_embeddings_batch
        mock_batch_gen.assert_called_once_with(["Chunk 2"])
        mock_doc_repo.update_chunk_embedding.assert_called_once_with(c2.id, [0.2] * 768)
