from typing import List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_from_header_or_query
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
    import re
    from datetime import datetime

    clean_title = title.strip() if title else ""
    if not clean_title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title cannot be empty.",
        )
    if len(clean_title) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title must not exceed 255 characters.",
        )
    if not re.search(r'[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF]', clean_title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title must contain at least one letter and cannot consist only of numbers, dots, or symbols.",
        )

    current_year = datetime.now().year
    if year is not None and (year < 1 or year > current_year):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid year: {year}. Year must be between 1 and current year ({current_year}).",
        )
    if exam_type and len(exam_type) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exam type must not exceed 100 characters.",
        )

    service = ReferencePaperService(db)
    paper = service.upload_reference_paper(
        current_user_id=current_user.id,
        subject_id=subject_id,
        file=file,
        title=clean_title,
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
    response_model=Union[ReferencePaperDetailResponse, ReferencePaperResponse],
    status_code=status.HTTP_200_OK,
)
def get_reference_paper(
    paper_id: UUID,
    include_pages: bool = Query(False, description="Set to true to include full extracted page texts"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get metadata for a reference paper by ID. Pass ?include_pages=true to include page texts.
    """
    service = ReferencePaperService(db)
    paper = service.get_reference_paper(current_user_id=current_user.id, paper_id=paper_id)
    if include_pages:
        return ReferencePaperDetailResponse.model_validate(paper)
    return ReferencePaperResponse.model_validate(paper)


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



