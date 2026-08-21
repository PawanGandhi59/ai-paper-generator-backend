from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class DocumentUploadResponse(BaseModel):
    id: UUID
    status: str

    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    chapter_number: Optional[int] = None
    original_filename: str
    mime_type: str
    file_size: int
    processing_status: str
    processing_error: Optional[str] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def file_url(self) -> str:
        return f"/storage/documents/{self.id}/original.pdf"

    model_config = ConfigDict(from_attributes=True)


class DocumentPageResponse(BaseModel):
    id: UUID
    document_id: UUID
    page_number: int
    content_type: str
    text_content: str
    image_path: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
