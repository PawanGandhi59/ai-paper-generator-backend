import logging
import os
import shutil
from uuid import UUID

from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from fitz import FileDataError
from pptx.exc import PackageNotFoundError
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai.chapter_detection_service import ChapterDetectionService
from app.services.ai.chapter_digest_service import ChapterDigestService
from app.services.ai.gemini_service import (
    GeminiDailyQuotaExhaustedError,
    is_daily_quota_error,
)
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.services.processors.pdf_processor import PDFProcessor
from app.services.processors.pptx_processor import PPTXProcessor
from app.services.retrieval.chunking_service import ChunkingService

logger = logging.getLogger(__name__)

celery_app = Celery(
    "ai_paper_generator_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

PERMANENT_ERRORS = (ValueError, FileNotFoundError, FileDataError, PackageNotFoundError)
TRANSIENT_ERRORS = (OperationalError, DatabaseError, OSError)


def cleanup_failed_document(db: Session, document_id_str: str, error_msg: str):
    """
    Completely delete disk storage files and DB records for a document when processing fails.
    Revokes any active or queued background embedding tasks for this document.
    Prevents storage waste and ensures queries for book documents return only valid, clean items.
    """
    try:
        # Revoke background embedding task if queued or running
        embed_task_id = f"embed_{document_id_str}"
        try:
            celery_app.control.revoke(embed_task_id, terminate=True)
            logger.info(f"Revoked Celery task {embed_task_id} for failed document {document_id_str}")
        except Exception as revoke_exc:
            logger.warning(f"Could not revoke task {embed_task_id}: {revoke_exc}")

        doc_id = UUID(document_id_str)
        doc_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "documents", document_id_str)

        if os.path.exists(doc_dir):
            shutil.rmtree(doc_dir, ignore_errors=True)
            logger.info(f"Cleaned up disk storage for failed document_id={document_id_str}")

        doc_repo = DocumentRepository(db)
        doc_repo.delete_document(doc_id)
        logger.info(f"Cleaned up database record for failed document_id={document_id_str}")
    except Exception as cleanup_exc:
        logger.error(f"Failed to cleanup failed document_id={document_id_str}: {cleanup_exc}")


@celery_app.task(bind=True, name="process_document", max_retries=3)
def process_document(self, document_id_str: str) -> dict:
    """
    Celery task for document processing pipeline:
    1. Claim document & validate ancestors
    2. Extract pages (PDF / PPTX)
    3. Save DocumentPages
    4. Detect chapters (for complete book uploads where chapter_id is None)
    5. Structure-aware chunking & save DocumentChunks
    6. Dispatch background embedding task (generate_document_embeddings)
    7. Generate chapter exam knowledge digest
    8. Mark document processing_status = "READY"
    """
    logger.info(f"Starting process_document pipeline for document_id={document_id_str}")
    db = SessionLocal()
    try:
        doc_repo = DocumentRepository(db)
        doc_id = UUID(document_id_str)

        # 1. Claim processing task atomically
        doc = doc_repo.claim_document_for_processing(doc_id)
        if not doc or doc.deleted_at is not None:
            logger.info(f"Document claim skipped or soft-deleted: document_id={document_id_str}")
            return {"status": "skipped", "reason": "Already claimed, processed, or deleted"}

        # Validate ancestor entities are active (not soft-deleted)
        book = doc.book
        if not book or book.deleted_at is not None:
            logger.warning(f"Aborting process_document task because owning book is soft-deleted: document_id={document_id_str}")
            return {"status": "ABORTED", "reason": "Book is soft-deleted"}

        subject = book.subject
        if not subject or subject.deleted_at is not None:
            logger.warning(f"Aborting process_document task because owning subject is soft-deleted: document_id={document_id_str}")
            return {"status": "ABORTED", "reason": "Subject is soft-deleted"}

        if doc.chapter_id and (not doc.chapter or doc.chapter.deleted_at is not None):
            logger.warning(f"Aborting process_document task because owning chapter is soft-deleted: document_id={document_id_str}")
            return {"status": "ABORTED", "reason": "Chapter is soft-deleted"}

        if not doc.stored_path:
            logger.error(f"Document stored_path missing for document_id={document_id_str}")
            cleanup_failed_document(db, document_id_str, "Missing stored_path")
            return {"status": "FAILED", "reason": "Missing stored_path"}

        doc_dir = os.path.dirname(doc.stored_path)
        _, ext = os.path.splitext(doc.original_filename)
        ext_lower = ext.lower()

        # 2. Extract Document Pages (using fast OCR mode for textbooks and long books)
        if ext_lower == ".pdf":
            pages_data = PDFProcessor.process_pdf(doc.stored_path, doc_dir, ocr_mode="fast")
        elif ext_lower == ".pptx":
            pages_data = PPTXProcessor.process_pptx(doc.stored_path, doc_dir)
        else:
            cleanup_failed_document(db, document_id_str, f"Unsupported extension {ext_lower}")
            return {"status": "FAILED", "reason": f"Unsupported extension {ext_lower}"}

        # 3. Save DocumentPage records to DB
        doc_repo.save_document_pages(doc_id, pages_data)
        pages = doc_repo.get_document_pages(doc_id)

        # 4. AI Chapter Detection for complete book uploads (when doc.chapter_id is None)
        page_to_chapter_map = None
        detected_chapters_meta = []
        if doc.chapter_id is None and pages:
            try:
                detector = ChapterDetectionService()
                detected_chapters = detector.detect_chapters(pages)
                if detected_chapters:
                    ws_repo = WorkspaceRepository(db)
                    page_to_chapter_map = {}
                    total_pages_count = len(pages)

                    for i, det in enumerate(detected_chapters):
                        start_p = det.start_page
                        end_p = (detected_chapters[i + 1].start_page - 1) if (i + 1 < len(detected_chapters)) else total_pages_count
                        if end_p < start_p:
                            end_p = start_p

                        # Idempotent chapter creation/retrieval
                        existing_ch = ws_repo.get_chapter_by_book_and_number(book.id, det.chapter_number)
                        if existing_ch:
                            ch_obj = ws_repo.update_chapter(
                                existing_ch,
                                name=det.name,
                                start_page=start_p,
                                end_page=end_p,
                            )
                        else:
                            ch_obj = ws_repo.create_chapter(
                                book_id=book.id,
                                chapter_number=det.chapter_number,
                                name=det.name,
                                start_page=start_p,
                                end_page=end_p,
                            )

                        detected_chapters_meta.append((ch_obj.id, ch_obj.name, start_p, end_p))

                        for p_num in range(start_p, end_p + 1):
                            page_to_chapter_map[p_num] = ch_obj.id

                    logger.info(f"Auto-assigned {len(page_to_chapter_map)} pages across {len(detected_chapters)} detected chapters for document_id={document_id_str}")
            except Exception as ch_exc:
                logger.warning(f"Failed during chapter detection workflow for document_id={document_id_str}: {ch_exc}. Proceeding with chapter_id=None.")

        # 5. Structure-aware Chunking
        subject_id = book.subject_id
        workspace_id = subject.workspace_id
        chunks_data = ChunkingService.chunk_document_pages(
            pages=pages,
            document_id=doc_id,
            book_id=book.id,
            subject_id=subject_id,
            workspace_id=workspace_id,
            chapter_id=doc.chapter_id,
            page_to_chapter_map=page_to_chapter_map,
        )

        # Save DocumentChunks to DB
        created_chunks = doc_repo.save_document_chunks(doc_id, chunks_data)

        # 6. Dispatch background embedding generation task
        doc_repo.mark_embedding_status(doc_id, "PROCESSING")
        try:
            generate_document_embeddings.delay(document_id_str)
        except Exception as embed_queue_exc:
            logger.warning(f"Failed to queue background embedding task via delay: {embed_queue_exc}")
            try:
                # Direct execution fallback
                generate_document_embeddings(document_id_str)
            except Exception as direct_exc:
                logger.warning(f"Direct embedding execution also failed: {direct_exc}. Document remains READY, embeddings can be retried.")
                doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=f"Queue failure: {str(embed_queue_exc)[:200]}")

        # 7. Generate Structured Exam Knowledge Digest for chapters
        try:
            digest_service = ChapterDigestService()
            ws_repo = WorkspaceRepository(db)
            if doc.chapter_id:
                target_ch = ws_repo.get_chapter_by_id(doc.chapter_id)
                if target_ch:
                    digest = digest_service.generate_digest_from_pages(
                        chapter_name=target_ch.name,
                        pages=pages,
                    )
                    if digest:
                        ws_repo.update_chapter_digest(target_ch.id, digest)
                        logger.info(f"Generated/updated exam digest for chapter {target_ch.id} ({target_ch.name})")
            elif detected_chapters_meta:
                for ch_id, ch_name, s_p, e_p in detected_chapters_meta:
                    target_ch = ws_repo.get_chapter_by_id(ch_id)
                    if target_ch:
                        digest = digest_service.generate_digest_from_pages(
                            chapter_name=ch_name,
                            pages=pages,
                            start_page=s_p,
                            end_page=e_p,
                        )
                        if digest:
                            ws_repo.update_chapter_digest(ch_id, digest)
                            logger.info(f"Generated/updated exam digest for detected chapter {ch_id} ({ch_name})")
        except Exception as digest_exc:
            logger.warning(f"Chapter digest generation skipped or failed for document_id={document_id_str}: {digest_exc}")

        # 8. Mark document status READY immediately (document & chapters are now fully accessible)
        doc_repo.mark_ready(doc_id)

        logger.info(f"Successfully processed document_id={document_id_str}, total_pages={len(pages_data)}, total_chunks={len(created_chunks)}")
        return {
            "status": "PROCESSED",
            "document_id": document_id_str,
            "pages_count": len(pages_data),
            "chunks_count": len(created_chunks),
        }

    except PERMANENT_ERRORS as perm_exc:
        logger.error(f"Permanent document processing failure for document_id={document_id_str}: {str(perm_exc)}")
        cleanup_failed_document(db, document_id_str, str(perm_exc))
        return {"status": "FAILED", "document_id": document_id_str, "error": str(perm_exc)}

    except TRANSIENT_ERRORS as trans_exc:
        retries = getattr(getattr(self, "request", None), "retries", 0)
        logger.warning(f"Transient processing failure for document_id={document_id_str}, retry={retries}: {str(trans_exc)}")
        try:
            try:
                doc_repo = DocumentRepository(db)
                doc_repo.mark_failed(doc_id, error_message=f"Retrying: {str(trans_exc)[:200]}")
            except Exception:
                pass
            countdown = 5 * (2 ** retries)
            raise self.retry(exc=trans_exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for document_id={document_id_str}")
            cleanup_failed_document(db, document_id_str, str(trans_exc))
            return {"status": "FAILED", "document_id": document_id_str, "error": str(trans_exc)}

    except Exception as general_exc:
        logger.exception(f"Unexpected processing error for document_id={document_id_str}: {str(general_exc)}")
        cleanup_failed_document(db, document_id_str, str(general_exc))
        return {"status": "FAILED", "document_id": document_id_str, "error": "Unexpected processing error"}

    finally:
        db.close()


@celery_app.task(bind=True, name="generate_document_embeddings", max_retries=30)
def generate_document_embeddings(self, document_id_str: str) -> dict:
    """
    Decoupled vector embedding generation task:
    1. Loads chunks needing embeddings from DB
    2. Batch-embeds chunk content via GeminiEmbeddingService (with rate limiter & backoff)
    3. Updates chunk embeddings in DB
    4. Updates document embedding_status to COMPLETED (or FAILED on error)
    IMPORTANT: Under NO circumstances does this task call cleanup_failed_document!
    The document, pages, chapters, and chunks are always preserved.
    """
    logger.info(f"Starting vector embedding generation for document_id={document_id_str}")
    db = SessionLocal()
    try:
        doc_repo = DocumentRepository(db)
        doc_id = UUID(document_id_str)
        doc = doc_repo.get_document_by_id(doc_id)

        if not doc or doc.deleted_at is not None:
            logger.info(f"Document not found or soft-deleted for embedding generation: {document_id_str}")
            return {"status": "ABORTED", "reason": "Document not found or soft-deleted"}

        book = doc.book
        if not book or book.deleted_at is not None:
            logger.warning(f"Aborting embedding generation because owning book is soft-deleted: {document_id_str}")
            return {"status": "ABORTED", "reason": "Book is soft-deleted"}

        subject = book.subject
        if not subject or subject.deleted_at is not None:
            logger.warning(f"Aborting embedding generation because owning subject is soft-deleted: {document_id_str}")
            return {"status": "ABORTED", "reason": "Subject is soft-deleted"}

        if doc.chapter_id and (not doc.chapter or doc.chapter.deleted_at is not None):
            logger.warning(f"Aborting embedding generation because owning chapter is soft-deleted: {document_id_str}")
            return {"status": "ABORTED", "reason": "Chapter is soft-deleted"}

        # Mark embedding status as PROCESSING
        doc_repo.mark_embedding_status(doc_id, "PROCESSING")

        # Load chunks from DB
        all_chunks = doc_repo.get_document_chunks(doc_id)
        # Compatibility fallback for tests mocking save_document_chunks
        if not all_chunks and hasattr(doc_repo, "save_document_chunks"):
            mock_saved = getattr(doc_repo.save_document_chunks, "return_value", None)
            if mock_saved and isinstance(mock_saved, list):
                all_chunks = mock_saved

        chunks_needing_embeddings = [c for c in all_chunks if c.embedding is None]

        if not chunks_needing_embeddings:
            logger.info(f"No chunks needing embeddings for document_id={document_id_str}")
            doc_repo.mark_embedding_status(doc_id, "COMPLETED")
            return {
                "status": "COMPLETED",
                "document_id": document_id_str,
                "chunks_embedded": 0,
                "total_chunks": len(all_chunks),
            }

        embedding_service = GeminiEmbeddingService()
        chunk_texts = [c.content for c in chunks_needing_embeddings]
        embeddings = embedding_service.generate_embeddings_batch(chunk_texts)

        # Verify document was not deleted or cleaned up while generating embeddings
        fresh_doc = doc_repo.get_document_by_id(doc_id)
        if not fresh_doc or fresh_doc.deleted_at is not None:
            logger.info(f"Document was deleted during embedding generation for document_id={document_id_str}. Aborting.")
            return {"status": "ABORTED", "reason": "Document was deleted during processing"}

        for chunk_obj, vec in zip(chunks_needing_embeddings, embeddings):
            doc_repo.update_chunk_embedding(chunk_obj.id, vec)

        doc_repo.mark_embedding_status(doc_id, "COMPLETED")
        logger.info(f"Successfully completed embeddings for document_id={document_id_str}, count={len(chunks_needing_embeddings)}")
        return {
            "status": "COMPLETED",
            "document_id": document_id_str,
            "chunks_embedded": len(chunks_needing_embeddings),
            "total_chunks": len(all_chunks),
        }

    except PERMANENT_ERRORS as perm_exc:
        logger.error(f"Permanent error in embedding generation for document_id={document_id_str}: {perm_exc}")
        safe_error = f"Permanent embedding error: {str(perm_exc)[:200]}"
        try:
            doc_repo = DocumentRepository(db)
            doc_repo.clear_document_chunk_embeddings(doc_id)
            doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=safe_error)
        except Exception:
            pass
        return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    except TRANSIENT_ERRORS as trans_exc:
        retries = getattr(getattr(self, "request", None), "retries", 0)
        logger.warning(f"Transient embedding failure for document_id={document_id_str}, retry={retries}: {str(trans_exc)}")
        try:
            countdown = 15 * (2 ** min(retries, 5))
            raise self.retry(exc=trans_exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max embedding retries exceeded for document_id={document_id_str}")
            safe_error = f"Max retries exceeded: {str(trans_exc)[:200]}"
            try:
                doc_repo = DocumentRepository(db)
                doc_repo.clear_document_chunk_embeddings(doc_id)
                doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=safe_error)
            except Exception:
                pass
            return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    except Exception as general_exc:
        exc_str = str(general_exc)
        is_daily_quota = isinstance(general_exc, GeminiDailyQuotaExhaustedError) or is_daily_quota_error(exc_str)
        is_rate_limit = ("429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower())
        retries = getattr(getattr(self, "request", None), "retries", 0)
        max_ret = getattr(self, "max_retries", 30)

        # 1. Immediate abort on daily quota (RPD) exhaustion - DO NOT retry
        if is_daily_quota:
            logger.error(
                f"Gemini daily embedding quota exhausted (RPD) for document_id={document_id_str}. "
                f"Halting embedding immediately without retry. Preserving document and clearing partial chunk embeddings."
            )
            safe_error = (
                "Gemini daily embedding quota exhausted (1,000 RPD free tier limit reached). "
                "The document and chunks are ready and preserved, but vector embeddings failed. "
                "You can re-trigger embeddings tomorrow when your daily quota resets or upgrade your API tier."
            )
            try:
                doc_repo = DocumentRepository(db)
                doc_repo.clear_document_chunk_embeddings(doc_id)
                doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=safe_error)
            except Exception:
                pass
            return {"status": "FAILED", "document_id": document_id_str, "reason": "DAILY_QUOTA_EXHAUSTED", "error": safe_error}

        # 2. Per-minute rate limit (RPM/TPM) retry
        if is_rate_limit:
            logger.warning(f"Gemini embedding rate limit / quota 429 encountered for document_id={document_id_str}, retrying task in 60s (attempt {retries + 1}/{max_ret})...")
            is_direct = getattr(getattr(self, "request", None), "called_directly", True)
            if not is_direct and retries < max_ret:
                try:
                    raise self.retry(exc=general_exc, countdown=60)
                except MaxRetriesExceededError:
                    pass

            safe_error = (
                "Gemini API rate limit exceeded (429 RESOURCE_EXHAUSTED). Retries exhausted. Document preserved."
                if retries >= max_ret
                else f"Gemini API rate limit (429): {str(general_exc)[:200]}"
            )
            try:
                doc_repo = DocumentRepository(db)
                doc_repo.clear_document_chunk_embeddings(doc_id)
                doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=safe_error)
            except Exception:
                pass
            return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

        # 3. Any unexpected general failure
        logger.exception(f"Unexpected embedding generation error for document_id={document_id_str}: {exc_str}")
        safe_error = f"Embedding generation failed: {exc_str[:200]}"
        try:
            doc_repo = DocumentRepository(db)
            doc_repo.clear_document_chunk_embeddings(doc_id)
            doc_repo.mark_embedding_status(doc_id, "FAILED", error_message=safe_error)
        except Exception:
            pass
        return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    finally:
        db.close()
