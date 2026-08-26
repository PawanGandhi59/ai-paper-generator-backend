import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


def _validate_name(v: str, entity: str = "Reference paper title") -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{entity} cannot be empty or blank")
    if not re.search(r'[a-zA-Z0-9\u00C0-\u024F\u1E00-\u1EFF]', v):
        raise ValueError(f"{entity} must contain at least one letter or number and cannot consist only of symbols")
    return v


class ReferencePaperCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    year: Optional[int] = Field(None, ge=1900, le=2100, description="Valid calendar year (e.g., 2025)")
    exam_type: Optional[str] = Field(None, max_length=100)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return _validate_name(v, "Reference paper title")

    @field_validator("exam_type")
    @classmethod
    def validate_exam_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
        return v



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
