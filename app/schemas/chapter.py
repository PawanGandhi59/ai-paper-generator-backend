from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChapterCreate(BaseModel):
    chapter_number: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    start_page: Optional[int] = Field(None, ge=1)
    end_page: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_page_range(self) -> "ChapterCreate":
        if self.start_page is not None and self.end_page is not None:
            if self.start_page > self.end_page:
                raise ValueError("start_page must be less than or equal to end_page")
        return self


class ChapterUpdate(BaseModel):
    chapter_number: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    start_page: Optional[int] = Field(None, ge=1)
    end_page: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_page_range(self) -> "ChapterUpdate":
        if self.start_page is not None and self.end_page is not None:
            if self.start_page > self.end_page:
                raise ValueError("start_page must be less than or equal to end_page")
        return self


class ChapterResponse(BaseModel):
    id: UUID
    book_id: UUID
    chapter_number: int
    name: str
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
