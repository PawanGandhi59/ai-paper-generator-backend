from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChapterCreate(BaseModel):
    chapter_number: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)


class ChapterUpdate(BaseModel):
    chapter_number: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, min_length=1, max_length=255)


class ChapterResponse(BaseModel):
    id: UUID
    book_id: UUID
    chapter_number: int
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
