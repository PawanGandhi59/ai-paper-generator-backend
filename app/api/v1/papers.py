from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.paper import AnswerKeyUpdateRequest, PaperGenerateRequest, PaperResponse
from app.services.paper.paper_generator_service import PaperGeneratorService

router = APIRouter(tags=["Paper Generation"])



@router.post("/papers/generate", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
def generate_paper(
    data: PaperGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaperResponse:
    """
    Generate a new examination paper using CUSTOM or REFERENCE generation mode.
    Enforces authorization, blueprint validation, chapter-bounded RAG, business rule verification, and deduplication.
    """
    service = PaperGeneratorService(db)
    return service.generate_paper(current_user_id=current_user.id, request_data=data)


@router.get("/papers/{paper_id}", response_model=PaperResponse, status_code=status.HTTP_200_OK)
def get_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaperResponse:
    """
    Retrieve generated paper details by ID.
    If include_answers is False, answer keys and explanations are automatically stripped from the response.
    """
    service = PaperGeneratorService(db)
    return service.get_paper(current_user_id=current_user.id, paper_id=paper_id)


@router.get("/subjects/{subject_id}/papers", response_model=List[PaperResponse], status_code=status.HTTP_200_OK, summary="AI Generated Papers")
def list_papers_by_subject(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[PaperResponse]:
    """
    List all generated papers under a subject for the authenticated user.
    """
    service = PaperGeneratorService(db)
    return service.list_papers(current_user_id=current_user.id, subject_id=subject_id)



@router.post("/papers/{paper_id}/save-pdf", response_model=PaperResponse, status_code=status.HTTP_200_OK)
def save_paper_pdf(
    paper_id: UUID,
    file: UploadFile = File(...),
    answer_key: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaperResponse:
    """
    Upload and save the final edited PDF for a generated paper.
    Validates PDF format (%PDF-), stores file locally, links document record, updates answer_key if provided,
    and triggers async PDF text extraction, chunking, and embeddings.
    Rejects subsequent saves on the same paper with HTTP 409 Conflict.
    """
    service = PaperGeneratorService(db)
    return service.save_pdf(paper_id=paper_id, current_user_id=current_user.id, file=file, answer_key=answer_key)


@router.put("/papers/{paper_id}/answer-key", response_model=PaperResponse, status_code=status.HTTP_200_OK)
def update_paper_answer_key(
    paper_id: UUID,
    data: AnswerKeyUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaperResponse:
    """
    Update the stored answer key for a generated paper with teacher/user edits from the frontend.
    """
    service = PaperGeneratorService(db)
    return service.update_answer_key(paper_id=paper_id, current_user_id=current_user.id, answer_key=data.answer_key)


@router.post("/papers/{paper_id}/regenerate-answer-key", response_model=PaperResponse, status_code=status.HTTP_200_OK)
def regenerate_paper_answer_key(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaperResponse:
    """
    Regenerate the answer key for an existing generated paper on demand using syllabus context.
    """
    service = PaperGeneratorService(db)
    return service.regenerate_answer_key(paper_id=paper_id, current_user_id=current_user.id)


@router.get("/papers/{paper_id}/pdf")
def get_paper_pdf(
    paper_id: UUID,
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Securely stream stored PDF file for inline preview or attachment download.
    Enforces authentication and workspace ownership.
    Works transparently with both AWS S3 and Local storage.
    """
    service = PaperGeneratorService(db)
    stream, length, media_type, title = service.get_paper_pdf_stream(paper_id=paper_id, current_user_id=current_user.id)
    safe_filename = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip() or "paper"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{safe_filename}.pdf"'
    }
    if length > 0:
        headers["Content-Length"] = str(length)

    def iter_stream():
        try:
            if hasattr(stream, "iter_chunks"):
                for chunk in stream.iter_chunks(chunk_size=65536):
                    yield chunk
            elif hasattr(stream, "read"):
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    yield chunk
            else:
                for chunk in stream:
                    yield chunk
        finally:
            if hasattr(stream, "close"):
                stream.close()

    return StreamingResponse(
        iter_stream(),
        media_type=media_type or "application/pdf",
        headers=headers,
    )


@router.delete("/papers/{paper_id}", status_code=status.HTTP_200_OK)
def delete_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Soft-delete GeneratedPaper record in DB and hard-delete stored PDF file on disk
    and associated Document, DocumentPage, DocumentChunk, and pgvector embeddings.
    """
    service = PaperGeneratorService(db)
    return service.delete_paper(paper_id=paper_id, current_user_id=current_user.id)

