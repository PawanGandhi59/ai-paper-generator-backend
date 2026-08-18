from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.rate_limiter import RateLimiter
from app.models.user import User
from app.schemas.ai import AIQueryRequest, AIQueryResponse, SourceReference
from app.services.ai.gemini_service import GeminiService
from app.services.retrieval.context_builder import ContextBuilder
from app.services.retrieval.retrieval_service import RetrievalService

router = APIRouter()


@router.post("/query", response_model=AIQueryResponse, status_code=status.HTTP_200_OK)
def rag_query(
    payload: AIQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Perform authenticated educational RAG query against workspace course materials.
    Enforces Redis per-user rate limiting, performs pgvector cosine similarity search,
    formats structured context within <retrieved_context> tags, and queries Gemini.
    """
    # 0. Enforce Redis Per-User Rate Limiting
    RateLimiter.check_rag_rate_limit(current_user.id)

    retrieval_service = RetrievalService(db)

    # 1. Retrieve similar chunks with strict workspace security isolation
    retrieved_chunks = retrieval_service.retrieve_context(
        current_user_id=current_user.id,
        workspace_id=payload.workspace_id,
        query=payload.query,
        subject_id=payload.subject_id,
        book_id=payload.book_id,
        chapter_id=payload.chapter_id,
        document_id=payload.document_id,
        top_k=payload.top_k,
    )

    # 2. Build RAG prompt context with source metadata citations
    context_text, source_citations = ContextBuilder.build_context(retrieved_chunks)

    # 3. Generate response using Gemini AI Service
    ai_service = GeminiService()
    try:
        gen_result = ai_service.generate_with_context(
            query=payload.query,
            context=context_text,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI Service provider error: {str(exc)}",
        )

    sources = [
        SourceReference(
            chunk_id=src["chunk_id"],
            document_id=src["document_id"],
            page_number=src["page_number"],
            chapter_id=src.get("chapter_id"),
            distance=src.get("distance", 0.0),
        )
        for src in source_citations
    ]

    return AIQueryResponse(
        answer=gen_result["answer"],
        model_used=gen_result.get("model_used", "gemini-3.6-flash"),
        sources=sources,
    )
