import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.rate_limiter import RateLimiter
from app.models.generated_visual import GeneratedVisual
from app.models.user import User
from app.schemas.ai import AIQueryRequest, AIQueryResponse, SourceReference, VisualItem
from app.services.ai.rag_chain import RAGOrchestrator
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
    formats structured context via LangChain LCEL RAGOrchestrator, generates visual artifacts,
    and returns textual answer, structured visuals, and source citations.
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

    # 2. Execute RAG via LangChain RAGOrchestrator pipeline
    orchestrator = RAGOrchestrator()
    try:
        gen_result = orchestrator.execute_rag(
            query=payload.query,
            retrieved_chunks=retrieved_chunks,
            user_id=current_user.id,
            workspace_id=payload.workspace_id,
            db=db,
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
        for src in gen_result.get("sources", [])
    ]

    visuals = [
        VisualItem(
            id=v["id"],
            type=v["type"],
            format=v["format"],
            title=v["title"],
            content=v["content"],
            caption=v.get("caption"),
        )
        for v in gen_result.get("visuals", [])
    ]

    return AIQueryResponse(
        answer=gen_result["answer"],
        visuals=visuals,
        model_used=settings.GEMINI_GENERATION_MODEL,
        sources=sources,
    )


@router.get("/visuals/{visual_id}", status_code=status.HTTP_200_OK)
def get_generated_visual(
    visual_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream authenticated generated visual asset file.
    Verifies user ownership to prevent IDOR vulnerability.
    """
    visual = db.query(GeneratedVisual).filter(GeneratedVisual.id == visual_id).first()
    if not visual or visual.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visual asset not found",
        )

    if not os.path.exists(visual.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visual asset file missing",
        )

    return FileResponse(
        path=visual.file_path,
        media_type=visual.mime_type,
        filename=f"{visual.id}.png",
    )

