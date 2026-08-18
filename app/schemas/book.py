from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
