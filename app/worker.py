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
    Prevents storage waste and ensures queries for book documents return only valid, clean items.
    """
    try:
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
    Celery task for document processing pipeline.
    """
    logger.info(f"Starting process_document pipeline for document_id={document_id_str}")
    db = SessionLocal()
    try:
        doc_repo = DocumentRepository(db)
        doc_id = UUID(document_id_str)

        # 1. Claim processing task atomically
        doc = doc_repo.claim_document_for_processing(doc_id)
        if not doc:
            logger.info(f"Document claim skipped or already processing/processed: document_id={document_id_str}")
            return {"status": "skipped", "reason": "Already claimed or processed"}

        if not doc.stored_path:
            logger.error(f"Document stored_path missing for document_id={document_id_str}")
            cleanup_failed_document(db, document_id_str, "Missing stored_path")
            return {"status": "FAILED", "reason": "Missing stored_path"}

        doc_dir = os.path.dirname(doc.stored_path)
        _, ext = os.path.splitext(doc.original_filename)
        ext_lower = ext.lower()

        # 2. Extract Document Pages
        if ext_lower == ".pdf":
            pages_data = PDFProcessor.process_pdf(doc.stored_path, doc_dir)
        elif ext_lower == ".pptx":
            pages_data = PPTXProcessor.process_pptx(doc.stored_path, doc_dir)
        else:
            cleanup_failed_document(db, document_id_str, f"Unsupported extension {ext_lower}")
            return {"status": "FAILED", "reason": f"Unsupported extension {ext_lower}"}

        # 3. Save DocumentPage records to DB
        doc_repo.save_document_pages(doc_id, pages_data)
        doc_repo.mark_embedding_started(doc_id)

        # 5. Trigger async embedding generation task
        try:
            generate_document_embeddings.delay(document_id_str)
        except Exception as embed_queue_exc:
            logger.error(f"Failed to queue embedding task: {embed_queue_exc}")
            generate_document_embeddings(document_id_str)

        logger.info(f"Successfully processed document_id={document_id_str}, total_pages={len(pages_data)}")
        return {
            "status": "PROCESSED",
            "document_id": document_id_str,
            "pages_count": len(pages_data),
        }

    except PERMANENT_ERRORS as perm_exc:
        logger.error(f"Permanent document processing failure for document_id={document_id_str}: {str(perm_exc)}")
        cleanup_failed_document(db, document_id_str, str(perm_exc))
        return {"status": "FAILED", "document_id": document_id_str, "error": str(perm_exc)}

    except TRANSIENT_ERRORS as trans_exc:
        logger.warning(f"Transient processing failure for document_id={document_id_str}, retry={self.request.retries}: {str(trans_exc)}")
        try:
            countdown = 5 * (2 ** self.request.retries)
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
        cleanup_failed_document(db, document_id_str, str(perm_exc))
        return {"status": "FAILED", "document_id": document_id_str, "error": str(perm_exc)}

    except TRANSIENT_ERRORS as trans_exc:
        logger.warning(f"Transient embedding failure for document_id={document_id_str}, retry={self.request.retries}: {str(trans_exc)}")
        try:
            countdown = 5 * (2 ** self.request.retries)
            raise self.retry(exc=trans_exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max embedding retries exceeded for document_id={document_id_str}")
            cleanup_failed_document(db, document_id_str, str(trans_exc))
            return {"status": "FAILED", "document_id": document_id_str, "error": str(trans_exc)}

    except Exception as general_exc:
        exc_str = str(general_exc)
        if ("429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower()) and self.request.retries < self.max_retries:
            logger.warning(f"Rate limit / quota 429 encountered for document_id={document_id_str}, retrying task in 45s (attempt {self.request.retries + 1}/{self.max_retries})...")
            try:
                raise self.retry(exc=general_exc, countdown=45)
            except MaxRetriesExceededError:
                pass
        logger.exception(f"Unexpected embedding generation error for document_id={document_id_str}: {exc_str}")
        if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower():
            safe_error = "Gemini API rate limit or daily free tier quota exceeded (429 RESOURCE_EXHAUSTED). Please check your Gemini API billing/quota or retry later."
        else:
            safe_error = f"Embedding generation failed: {exc_str[:200]}"
        cleanup_failed_document(db, document_id_str, safe_error)
        return {"status": "FAILED", "document_id": document_id_str, "error": safe_error}

    finally:
        db.close()
