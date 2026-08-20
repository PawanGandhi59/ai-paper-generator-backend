from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.chapter import ChapterCreate, ChapterResponse, ChapterUpdate
from app.services.workspace_service import WorkspaceService

router = APIRouter(tags=["Chapters"])


@router.post("/books/{book_id}/chapters", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
def create_chapter(
    book_id: UUID,
    data: ChapterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChapterResponse:
    """
    Create a new chapter under a book.
    If chapter_number is omitted, it automatically increments based on existing chapters.
    """
    service = WorkspaceService(db)
    chapter = service.create_chapter(
        book_id=book_id,
        current_user_id=current_user.id,
        chapter_number=data.chapter_number,
        name=data.name,
        start_page=data.start_page,
        end_page=data.end_page,
    )
    return ChapterResponse.model_validate(chapter)


@router.get("/books/{book_id}/chapters", response_model=List[ChapterResponse], status_code=status.HTTP_200_OK)
def list_chapters(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ChapterResponse]:
    """
    List all chapters under a book.
    """
    service = WorkspaceService(db)
    chapters = service.list_chapters(book_id=book_id, current_user_id=current_user.id)
    return [ChapterResponse.model_validate(c) for c in chapters]


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse, status_code=status.HTTP_200_OK)
def get_chapter(
    chapter_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChapterResponse:
    """
    Get a chapter by ID.
    """
    service = WorkspaceService(db)
    chapter = service.get_chapter(chapter_id=chapter_id, current_user_id=current_user.id)
    return ChapterResponse.model_validate(chapter)


@router.patch("/chapters/{chapter_id}", response_model=ChapterResponse, status_code=status.HTTP_200_OK)
def update_chapter(
    chapter_id: UUID,
    data: ChapterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChapterResponse:
    """
    Update a chapter by ID.
    """
    service = WorkspaceService(db)
    chapter = service.update_chapter(
        chapter_id=chapter_id,
        current_user_id=current_user.id,
        chapter_number=data.chapter_number,
        name=data.name,
        start_page=data.start_page,
        end_page=data.end_page,
    )
    return ChapterResponse.model_validate(chapter)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(
    chapter_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a chapter by ID.
    """
    service = WorkspaceService(db)
    service.delete_chapter(chapter_id=chapter_id, current_user_id=current_user.id)
