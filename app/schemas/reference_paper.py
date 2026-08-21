from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ReferencePaperCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    year: Optional[int] = Field(None, ge=1, le=2100, description="Valid calendar year (e.g., 2025)")
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

    @computed_field
    @property
    def file_url(self) -> str:
        return f"/storage/reference_papers/{self.id}/original.pdf"

    model_config = ConfigDict(from_attributes=True)


class ReferencePaperDetailResponse(ReferencePaperResponse):
    pages: List[ReferencePaperPageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
