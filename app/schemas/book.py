from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import DocumentResponse


class BookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class BookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)


class BookResponse(BaseModel):
    id: UUID
    subject_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookDetailResponse(BookResponse):
    documents: List[DocumentResponse] = Field(default_factory=list)
