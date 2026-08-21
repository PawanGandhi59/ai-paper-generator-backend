import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import DocumentResponse


def _validate_name(v: str, entity: str = "Book name") -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{entity} cannot be empty or blank")
    if not re.search(r'[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF]', v):
        raise ValueError(f"{entity} must contain at least one letter and cannot consist only of numbers, dots, or symbols")
    return v


class BookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, "Book name")


class BookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_name(v, "Book name")
        return v


class BookResponse(BaseModel):
    id: UUID
    subject_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookDetailResponse(BookResponse):
    file_url: Optional[str] = None


