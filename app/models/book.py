import os
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.storage_utils import get_document_storage_url, is_textbook_document

if TYPE_CHECKING:
    from app.models.subject import Subject
    from app.models.chapter import Chapter
    from app.models.document import Document


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


    subject: Mapped["Subject"] = relationship("Subject", back_populates="books")
    chapters: Mapped[List["Chapter"]] = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="book", cascade="all, delete-orphan")

    @property
    def file_url(self) -> Optional[str]:
        if not self.documents:
            return None

        candidates = [
            doc for doc in self.documents
            if doc.chapter_id is None and is_textbook_document(doc)
        ]
        if not candidates:
            return None

        # Prioritize candidates whose file actually exists on disk
        for doc in candidates:
            if doc.stored_path and os.path.exists(doc.stored_path):
                return get_document_storage_url(doc)

        # Fallback to the first candidate (for mock/unit test environments)
        return get_document_storage_url(candidates[0])


