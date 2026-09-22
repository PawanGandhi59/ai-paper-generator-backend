import os
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.storage_utils import get_document_storage_url, is_textbook_document

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.topic import Topic
    from app.models.document import Document


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exam_digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


    book: Mapped["Book"] = relationship("Book", back_populates="chapters")
    topics: Mapped[List["Topic"]] = relationship("Topic", back_populates="chapter", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="chapter")

    @property
    def file_url(self) -> Optional[str]:
        if not self.documents:
            return None

        candidates = [
            doc for doc in self.documents
            if doc.chapter_id == self.id and is_textbook_document(doc)
        ]
        if not candidates:
            return None

        # Prioritize candidates whose file actually exists on disk
        for doc in candidates:
            if doc.stored_path and os.path.exists(doc.stored_path):
                return get_document_storage_url(doc)

        # Fallback to first candidate
        return get_document_storage_url(candidates[0])


