import logging
import os
from uuid import UUID

from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from fitz import FileDataError
from pptx.exc import PackageNotFoundError
from sqlalchemy.exc import DatabaseError, OperationalError

from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai.chapter_detection_service import ChapterDetectionService
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


@celery_app.task(bind=True, name="process_document", max_retries=3)
def process_document(self, document_id_str: str) -> dict:
    logger.info(f"Starting async processing for document_id={document_id_str}")
    db = SessionLocal()
    try:
        doc_repo = DocumentRepository(db)
        doc_id = UUID(document_id_str)

        # 1. Atomic claim check
        doc = doc_repo.claim_document_for_processing(doc_id)
        if not doc:
            logger.info(f"Document claim skipped or already processing/processed: document_id={document_id_str}")
            return {"status": "skipped", "reason": "Already claimed or processed"}

        doc_dir = os.path.dirname(doc.stored_path)
        filename_lower = doc.original_filename.lower()
        mime_lower = doc.mime_type.lower()

        # 2. Document format processing
        if mime_lower == "application/pdf" or filename_lower.endswith(".pdf"):
            pages_data = PDFProcessor.process_pdf(doc.stored_path, doc_dir)
        elif (
            "presentation" in mime_lower
            or mime_lower == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            or filename_lower.endswith(".pptx")
        ):
            pages_data = PPTXProcessor.process_pptx(doc.stored_path, doc_dir)
        else:
            raise ValueError(f"Unsupported file format: mime={doc.mime_type}, name={doc.original_filename}")

        if not pages_data:
            raise ValueError("No pages or slides could be extracted from the document.")

        # 3. Save extracted pages & trigger embedding generation task
        doc_repo.save_document_pages(doc_id, pages_data)
        doc_repo.mark_embedding_started(doc_id)

        # Queue embedding task
        try:
            generate_document_embeddings.delay(document_id_str)
        except Exception as embed_queue_exc:
            logger.error(f"Failed to queue embedding task: {embed_queue_exc}")
            # Fallback to direct synchronous execution if async queue fails in test environments
            generate_document_embeddings(document_id_str)

        logger.info(f"Successfully processed document_id={document_id_str}, total_pages={len(pages_data)}")
        return {
            "status": "PROCESSED",
            "document_id": document_id_str,
            "pages_count": len(pages_data),
        }

    except PERMANENT_ERRORS as perm_exc:
        logger.error(f"Permanent document processing failure for document_id={document_id_str}: {str(perm_exc)}")
        try:
            doc_repo = DocumentRepository(db)
            safe_error = f"Permanent processing error: {type(perm_exc).__name__}"
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
        except Exception as save_exc:
            logger.error(f"Failed to record permanent error state for document_id={document_id_str}: {save_exc}")
        return {"status": "FAILED", "document_id": document_id_str, "error": str(perm_exc)}

    except TRANSIENT_ERRORS as trans_exc:
        logger.warning(f"Transient processing failure for document_id={document_id_str}, retry={self.request.retries}: {str(trans_exc)}")
        try:
            countdown = 5 * (2 ** self.request.retries)
            raise self.retry(exc=trans_exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for document_id={document_id_str}")
            doc_repo = DocumentRepository(db)
            safe_error = f"Processing failed after max retries: {type(trans_exc).__name__}"
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
            return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    except Exception as general_exc:
        logger.exception(f"Unexpected processing error for document_id={document_id_str}: {str(general_exc)}")
        try:
            doc_repo = DocumentRepository(db)
            safe_error = "An unexpected error occurred during processing."
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
        except Exception as save_exc:
            logger.error(f"Failed to record unexpected error state for document_id={document_id_str}: {save_exc}")
        return {"status": "FAILED", "document_id": document_id_str, "error": "Unexpected processing error"}

    finally:
        db.close()


@celery_app.task(bind=True, name="generate_document_embeddings", max_retries=3)
def generate_document_embeddings(self, document_id_str: str) -> dict:
    logger.info(f"Starting chunking & embedding generation for document_id={document_id_str}")
    db = SessionLocal()
    try:
        doc_repo = DocumentRepository(db)
        doc_id = UUID(document_id_str)
        doc = doc_repo.get_document_by_id(doc_id)

        if not doc:
            logger.error(f"Document not found for embedding generation: {document_id_str}")
            return {"status": "FAILED", "reason": "Document not found"}

        pages = doc_repo.get_document_pages(doc_id)
        if not pages:
            logger.warning(f"No pages found to embed for document_id={document_id_str}")
            doc_repo.mark_ready(doc_id)
            return {"status": "READY", "chunks_count": 0}

        # Resolve subject_id and workspace_id from book hierarchy
        book = doc.book
        subject_id = book.subject_id
        subject = book.subject
        workspace_id = subject.workspace_id

        # AI Chapter Detection for complete book uploads (when doc.chapter_id is None)
        page_to_chapter_map = None
        if doc.chapter_id is None:
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

                        for p_num in range(start_p, end_p + 1):
                            page_to_chapter_map[p_num] = ch_obj.id

                    logger.info(f"Auto-assigned {len(page_to_chapter_map)} pages across {len(detected_chapters)} detected chapters for document_id={document_id_str}")
            except Exception as ch_exc:
                logger.warning(f"Failed during chapter detection workflow for document_id={document_id_str}: {ch_exc}. Proceeding with chapter_id=None.")

        # 1. Structure-aware Chunking
        chunks_data = ChunkingService.chunk_document_pages(
            pages=pages,
            document_id=doc_id,
            book_id=book.id,
            subject_id=subject_id,
            workspace_id=workspace_id,
            chapter_id=doc.chapter_id,
            page_to_chapter_map=page_to_chapter_map,
        )

        # 2. Save DocumentChunks to DB
        created_chunks = doc_repo.save_document_chunks(doc_id, chunks_data)

        # 3. Generate Vector Embeddings
        embedding_service = GeminiEmbeddingService()
        chunk_texts = [c.content for c in created_chunks]
        embeddings = embedding_service.generate_embeddings_batch(chunk_texts)

        for chunk_obj, vec in zip(created_chunks, embeddings):
            doc_repo.update_chunk_embedding(chunk_obj.id, vec)

        # 4. Mark Document status READY
        doc_repo.mark_ready(doc_id)
        logger.info(f"Successfully generated embeddings for document_id={document_id_str}, total_chunks={len(created_chunks)}")
        return {
            "status": "READY",
            "document_id": document_id_str,
            "chunks_count": len(created_chunks),
        }

    except PERMANENT_ERRORS as perm_exc:
        logger.error(f"Permanent embedding generation failure for document_id={document_id_str}: {str(perm_exc)}")
        try:
            doc_repo = DocumentRepository(db)
            safe_error = f"Permanent embedding error: {type(perm_exc).__name__}"
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
        except Exception as save_exc:
            logger.error(f"Failed to record error state for document_id={document_id_str}: {save_exc}")
        return {"status": "FAILED", "document_id": document_id_str, "error": str(perm_exc)}

    except TRANSIENT_ERRORS as trans_exc:
        logger.warning(f"Transient embedding failure for document_id={document_id_str}, retry={self.request.retries}: {str(trans_exc)}")
        try:
            countdown = 5 * (2 ** self.request.retries)
            raise self.retry(exc=trans_exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max embedding retries exceeded for document_id={document_id_str}")
            doc_repo = DocumentRepository(db)
            safe_error = f"Embedding generation failed after max retries: {type(trans_exc).__name__}"
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
            return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    except Exception as general_exc:
        exc_str = str(general_exc)
        if ("429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower()) and self.request.retries < self.max_retries:
            logger.warning(f"Rate limit / quota 429 encountered for document_id={document_id_str}, retrying task in 45s (attempt {self.request.retries + 1}/{self.max_retries})...")
            try:
                raise self.retry(exc=general_exc, countdown=45)
            except MaxRetriesExceededError:
                pass
        logger.exception(f"Unexpected embedding generation error for document_id={document_id_str}: {exc_str}")
        try:
            doc_repo = DocumentRepository(db)
            safe_error = "An unexpected error occurred during embedding generation."
            doc_repo.mark_processing_failed(UUID(document_id_str), error_message=safe_error)
        except Exception as save_exc:
            logger.error(f"Failed to record unexpected embedding error for document_id={document_id_str}: {save_exc}")
        return {"status": "FAILED", "document_id": document_id_str, "error": "Unexpected embedding error"}

    finally:
        db.close()
