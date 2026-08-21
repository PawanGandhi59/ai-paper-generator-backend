import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_name(v: str, entity: str = "Workspace name") -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{entity} cannot be empty or blank")
    if not re.search(r'[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF]', v):
        raise ValueError(f"{entity} must contain at least one letter and cannot consist only of numbers, dots, or symbols")
    return v


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, "Workspace name")


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_name(v, "Workspace name")
        return v


class WorkspaceResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
