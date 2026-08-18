from typing import Any, Dict, List, Literal, Optional
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


class VisualItem(BaseModel):
    id: str = Field(..., description="Unique visual identifier e.g. visual_1")
    type: Literal["diagram", "chart"] = Field(..., description="Visual classification: diagram or chart")
    format: Literal["svg"] = Field("svg", description="Format identifier: svg")
    title: str = Field(..., description="Short descriptive header for the visual artifact")
    content: str = Field(..., description="Rendered SVG string")
    caption: Optional[str] = Field(None, description="Educational explanation connecting visual to answer")


class AIQueryResponse(BaseModel):
    answer: str = Field(..., description="Textual explanation and step-by-step educational answer")
    visuals: List[VisualItem] = Field(default_factory=list, description="Structured rendered SVG visual artifacts")
    model_used: str = Field(..., description="Gemini model identifier used for generation")
    sources: List[SourceReference] = Field(..., description="Retrieved vector document citations")

