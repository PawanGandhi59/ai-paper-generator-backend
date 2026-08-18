from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.subject import SubjectCreate, SubjectResponse, SubjectUpdate
from app.services.workspace_service import WorkspaceService

router = APIRouter(tags=["Subjects"])


@router.post("/workspaces/{workspace_id}/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
def create_subject(
    workspace_id: UUID,
    data: SubjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """
    Create a new subject inside a workspace.
    """
    service = WorkspaceService(db)
    subject = service.create_subject(workspace_id=workspace_id, current_user_id=current_user.id, name=data.name)
    return SubjectResponse.model_validate(subject)


@router.get("/workspaces/{workspace_id}/subjects", response_model=List[SubjectResponse], status_code=status.HTTP_200_OK)
def list_subjects(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SubjectResponse]:
    """
    List all subjects inside a workspace.
    """
    service = WorkspaceService(db)
    subjects = service.list_subjects(workspace_id=workspace_id, current_user_id=current_user.id)
    return [SubjectResponse.model_validate(s) for s in subjects]


@router.get("/subjects/{subject_id}", response_model=SubjectResponse, status_code=status.HTTP_200_OK)
def get_subject(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """
    Get a subject by ID.
    """
    service = WorkspaceService(db)
    subject = service.get_subject(subject_id=subject_id, current_user_id=current_user.id)
    return SubjectResponse.model_validate(subject)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse, status_code=status.HTTP_200_OK)
def update_subject(
    subject_id: UUID,
    data: SubjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """
    Update a subject by ID.
    """
    service = WorkspaceService(db)
    subject = service.update_subject(subject_id=subject_id, current_user_id=current_user.id, name=data.name)
    return SubjectResponse.model_validate(subject)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a subject by ID.
    """
    service = WorkspaceService(db)
    service.delete_subject(subject_id=subject_id, current_user_id=current_user.id)
