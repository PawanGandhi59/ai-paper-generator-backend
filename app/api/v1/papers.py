from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.paper import PaperGenerateRequest, PaperResponse
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


@router.get("/subjects/{subject_id}/papers", response_model=List[PaperResponse], status_code=status.HTTP_200_OK)
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
