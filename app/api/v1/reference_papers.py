from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.reference_paper import (
    ReferencePaperDetailResponse,
    ReferencePaperResponse,
)
from app.services.reference_paper_service import ReferencePaperService

router = APIRouter(tags=["Reference Papers"])


@router.post(
    "/subjects/{subject_id}/reference-papers",
    response_model=ReferencePaperResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_reference_paper(
    subject_id: UUID,
    title: str = Form(...),
    year: Optional[int] = Form(None),
    exam_type: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReferencePaperResponse:
    """
    Upload a reference or past-year examination paper PDF for a subject.
    """
    service = ReferencePaperService(db)
    paper = service.upload_reference_paper(
        current_user_id=current_user.id,
        subject_id=subject_id,
        file=file,
        title=title,
        year=year,
        exam_type=exam_type,
    )
    return ReferencePaperResponse.model_validate(paper)


@router.get(
    "/subjects/{subject_id}/reference-papers",
    response_model=List[ReferencePaperResponse],
    status_code=status.HTTP_200_OK,
)
def list_reference_papers(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ReferencePaperResponse]:
    """
    List all reference / past-year papers under a subject.
    """
    service = ReferencePaperService(db)
    papers = service.list_reference_papers(current_user_id=current_user.id, subject_id=subject_id)
    return [ReferencePaperResponse.model_validate(p) for p in papers]


@router.get(
    "/reference-papers/{paper_id}",
    response_model=ReferencePaperDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_reference_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReferencePaperDetailResponse:
    """
    Get metadata and extracted page texts for a reference paper by ID.
    """
    service = ReferencePaperService(db)
    paper = service.get_reference_paper(current_user_id=current_user.id, paper_id=paper_id)
    return ReferencePaperDetailResponse.model_validate(paper)


@router.delete(
    "/reference-papers/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reference_paper(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a reference paper and its stored filesystem package.
    """
    service = ReferencePaperService(db)
    service.delete_reference_paper(current_user_id=current_user.id, paper_id=paper_id)


@router.get("/reference-papers/{paper_id}/download")
def download_reference_paper_file(
    paper_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream / download the raw binary reference paper PDF file by paper ID.
    """
    import os
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    service = ReferencePaperService(db)
    paper = service.get_reference_paper(current_user_id=current_user.id, paper_id=paper_id)

    if not paper.stored_path or not os.path.exists(paper.stored_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference paper file not found on disk storage.",
        )

    return FileResponse(
        path=paper.stored_path,
        media_type=paper.mime_type or "application/pdf",
        filename=paper.original_filename or f"{paper.title}.pdf",
    )
