from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReferencePaperCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    exam_type: Optional[str] = Field(None, max_length=100)


class ReferencePaperPageResponse(BaseModel):
    id: UUID
    reference_paper_id: UUID
    page_number: int
    content_type: str
    text_content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReferencePaperResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    subject_id: UUID
    title: str
    year: Optional[int] = None
    exam_type: Optional[str] = None
    original_filename: str
    mime_type: str
    file_size: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReferencePaperDetailResponse(ReferencePaperResponse):
    pages: List[ReferencePaperPageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
