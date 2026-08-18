from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Create a new workspace owned by the authenticated user.
    """
    service = WorkspaceService(db)
    workspace = service.create_workspace(owner_id=current_user.id, name=data.name)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=List[WorkspaceResponse], status_code=status.HTTP_200_OK)
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[WorkspaceResponse]:
    """
    List all workspaces owned by the authenticated user.
    """
    service = WorkspaceService(db)
    workspaces = service.list_workspaces(current_user_id=current_user.id)
    return [WorkspaceResponse.model_validate(w) for w in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse, status_code=status.HTTP_200_OK)
def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Get workspace details by ID if owned by the authenticated user.
    """
    service = WorkspaceService(db)
    workspace = service.get_workspace(workspace_id=workspace_id, current_user_id=current_user.id)
    return WorkspaceResponse.model_validate(workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse, status_code=status.HTTP_200_OK)
def update_workspace(
    workspace_id: UUID,
    data: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """
    Update workspace name if owned by the authenticated user.
    """
    service = WorkspaceService(db)
    workspace = service.update_workspace(workspace_id=workspace_id, current_user_id=current_user.id, name=data.name)
    return WorkspaceResponse.model_validate(workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a workspace if owned by the authenticated user.
    """
    service = WorkspaceService(db)
    service.delete_workspace(workspace_id=workspace_id, current_user_id=current_user.id)
