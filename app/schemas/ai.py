from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AIQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Question or prompt text")
    workspace_id: UUID = Field(..., description="Target workspace ID for RAG search scope")
    subject_id: Optional[UUID] = Field(None, description="Optional subject ID filter")
    book_id: Optional[UUID] = Field(None, description="Optional book ID filter")
    chapter_id: Optional[UUID] = Field(None, description="Optional chapter ID filter")
    document_id: Optional[UUID] = Field(None, description="Optional document ID filter")
    top_k: int = Field(5, ge=1, le=20, description="Number of top context chunks to retrieve")


class SourceReference(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int
    chapter_id: Optional[str] = None
    distance: float


class AIQueryResponse(BaseModel):
    answer: str
    model_used: str
    sources: List[SourceReference]
