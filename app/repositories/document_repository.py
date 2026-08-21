from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chapter import Chapter
from app.models.document import Document, DocumentChunk, DocumentPage


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_document(
        self,
        book_id: UUID,
        original_filename: str,
        stored_path: str,
        mime_type: str,
        file_size: int,
        document_id: Optional[UUID] = None,
        chapter_id: Optional[UUID] = None,
        processing_status: str = "UPLOADED",
    ) -> Document:
        doc = Document(
            id=document_id or uuid.uuid4(),
            book_id=book_id,
            chapter_id=chapter_id,
            original_filename=original_filename,
            stored_path=stored_path,
            mime_type=mime_type,
            file_size=file_size,
            processing_status=processing_status,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def delete_document(self, document_id: UUID) -> bool:
        doc = self.db.get(Document, document_id)
        if doc:
            self.db.delete(doc)
            self.db.commit()
            return True
        return False

    def get_document_by_id(self, document_id: UUID) -> Optional[Document]:
        return self.db.get(Document, document_id)

    def claim_document_for_processing(self, document_id: UUID) -> Optional[Document]:
        """
        Atomically claim document for processing.
        Transitions status from 'UPLOADED' or 'FAILED' to 'PROCESSING'.
        Also reclaims stale 'PROCESSING' documents whose processing_started_at is older
        than settings.DOCUMENT_PROCESSING_STALE_MINUTES.
        Returns Document if claim succeeds, None if already claimed or processed.
        """
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(minutes=settings.DOCUMENT_PROCESSING_STALE_MINUTES)

        stmt = (
            update(Document)
            .where(
                Document.id == document_id,
                or_(
                    Document.processing_status.in_(["UPLOADED", "FAILED"]),
                    and_(
                        Document.processing_status == "PROCESSING",
                        Document.processing_started_at < stale_cutoff,
                    ),
                ),
            )
            .values(
                processing_status="PROCESSING",
                processing_started_at=now,
                processing_error=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        result = self.db.execute(stmt)
        self.db.commit()

        if result.rowcount > 0:
            return self.db.get(Document, document_id)
        return None

    def mark_processing_completed(self, document_id: UUID) -> Optional[Document]:
        doc = self.db.get(Document, document_id)
        if doc and doc.processing_status == "PROCESSING":
            doc.processing_status = "PROCESSED"
            doc.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def mark_embedding_started(self, document_id: UUID) -> Optional[Document]:
        doc = self.db.get(Document, document_id)
        if doc:
            doc.processing_status = "EMBEDDING"
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def mark_ready(self, document_id: UUID) -> Optional[Document]:
        doc = self.db.get(Document, document_id)
        if doc:
            doc.processing_status = "READY"
            doc.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def mark_processing_failed(self, document_id: UUID, error_message: str) -> Optional[Document]:
        doc = self.db.get(Document, document_id)
        if doc:
            doc.processing_status = "FAILED"
            doc.processing_error = str(error_message)[:1024]
            doc.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def save_document_pages(
        self,
        document_id: UUID,
        pages_data: List[Dict[str, Any]],
    ) -> List[DocumentPage]:
        self.db.expire_all()
        self.db.query(DocumentPage).filter(DocumentPage.document_id == document_id).delete(synchronize_session=False)
        self.db.commit()

        created_pages = []
        for page_info in pages_data:
            page = DocumentPage(
                document_id=document_id,
                page_number=page_info["page_number"],
                content_type=page_info.get("content_type", "PAGE"),
                text_content=page_info.get("text_content", ""),
                image_path=page_info.get("image_path"),
                metadata_json=page_info.get("metadata_json"),
            )
            self.db.add(page)
            created_pages.append(page)

        self.db.commit()
        return created_pages

    def get_document_pages(self, document_id: UUID) -> List[DocumentPage]:
        stmt = select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number.asc())
        return list(self.db.execute(stmt).scalars().all())

    def save_document_chunks(
        self,
        document_id: UUID,
        chunks_data: List[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        # Idempotent cleanup: Delete existing chunks before inserting new ones
        self.db.expire_all()
        self.db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete(synchronize_session=False)
        self.db.commit()

        created_chunks = []
        for c_info in chunks_data:
            chunk = DocumentChunk(
                document_id=document_id,
                document_page_id=c_info.get("document_page_id"),
                chapter_id=c_info.get("chapter_id"),
                book_id=c_info["book_id"],
                subject_id=c_info["subject_id"],
                workspace_id=c_info["workspace_id"],
                chunk_index=c_info["chunk_index"],
                page_number=c_info.get("page_number", 1),
                content=c_info["content"],
                content_type=c_info.get("content_type", "TEXT"),
                metadata_json=c_info.get("metadata_json"),
                embedding=c_info.get("embedding"),
            )
            self.db.add(chunk)
            created_chunks.append(chunk)

        self.db.commit()
        return created_chunks

    def get_document_chunks(self, document_id: UUID) -> List[DocumentChunk]:
        stmt = select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index.asc())
        return list(self.db.execute(stmt).scalars().all())

    def update_chunk_embedding(self, chunk_id: UUID, embedding: List[float]):
        stmt = update(DocumentChunk).where(DocumentChunk.id == chunk_id).values(embedding=embedding)
        self.db.execute(stmt)
        self.db.commit()

    def search_similar_chunks(
        self,
        workspace_id: UUID,
        query_vector: List[float],
        top_k: int = 5,
        subject_id: Optional[UUID] = None,
        book_id: Optional[UUID] = None,
        chapter_id: Optional[UUID] = None,
        chapter_ids: Optional[List[UUID]] = None,
        document_id: Optional[UUID] = None,
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Perform pgvector cosine similarity search filtered strictly by workspace_id
        and optional subject/book/chapter/chapter_ids/document parameters.
        Returns list of (DocumentChunk, cosine_distance) tuples.
        """
        distance_col = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
        stmt = select(DocumentChunk, distance_col).where(
            DocumentChunk.workspace_id == workspace_id,
            DocumentChunk.embedding.is_not(None)
        )

        if subject_id:
            stmt = stmt.where(DocumentChunk.subject_id == subject_id)
        if book_id:
            stmt = stmt.where(DocumentChunk.book_id == book_id)
        if chapter_id:
            stmt = stmt.where(DocumentChunk.chapter_id == chapter_id)
        if chapter_ids and len(chapter_ids) > 0:
            chapters = self.db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()
            conditions = [DocumentChunk.chapter_id.in_(chapter_ids)]
            for ch in chapters:
                if ch.start_page is not None and ch.end_page is not None:
                    conditions.append(
                        (DocumentChunk.book_id == ch.book_id) &
                        (DocumentChunk.page_number >= ch.start_page) &
                        (DocumentChunk.page_number <= ch.end_page)
                    )
            stmt = stmt.where(or_(*conditions))

        if document_id:
            stmt = stmt.where(DocumentChunk.document_id == document_id)

        stmt = stmt.order_by(distance_col.asc()).limit(top_k)
        results = self.db.execute(stmt).all()
        return [(row[0], float(row[1])) for row in results]
