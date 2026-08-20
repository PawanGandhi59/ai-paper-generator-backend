from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.book import BookCreate, BookDetailResponse, BookResponse, BookUpdate
from app.schemas.document import DocumentResponse
from app.services.workspace_service import WorkspaceService

router = APIRouter(tags=["Books"])


@router.post("/subjects/{subject_id}/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
def create_book(
    subject_id: UUID,
    data: BookCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookResponse:
    """
    Create a new book under a subject.
    """
    service = WorkspaceService(db)
    book = service.create_book(subject_id=subject_id, current_user_id=current_user.id, name=data.name)
    return BookResponse.model_validate(book)


@router.get("/subjects/{subject_id}/books", response_model=List[BookResponse], status_code=status.HTTP_200_OK)
def list_books(
    subject_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[BookResponse]:
    """
    List all books under a subject.
    """
    service = WorkspaceService(db)
    books = service.list_books(subject_id=subject_id, current_user_id=current_user.id)
    return [BookResponse.model_validate(b) for b in books]


@router.get("/books/{book_id}", response_model=BookDetailResponse, status_code=status.HTTP_200_OK)
def get_book(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookDetailResponse:
    """
    Get a book by ID with attached uploaded documents.
    """
    service = WorkspaceService(db)
    book = service.get_book(book_id=book_id, current_user_id=current_user.id)
    return BookDetailResponse.model_validate(book)


@router.get("/books/{book_id}/documents", response_model=List[DocumentResponse], status_code=status.HTTP_200_OK)
def list_book_documents(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DocumentResponse]:
    """
    List all uploaded documents (PDFs/PPTXs) under a book.
    """
    service = WorkspaceService(db)
    book = service.get_book(book_id=book_id, current_user_id=current_user.id)
    return [DocumentResponse.model_validate(doc) for doc in book.documents]


@router.patch("/books/{book_id}", response_model=BookResponse, status_code=status.HTTP_200_OK)
def update_book(
    book_id: UUID,
    data: BookUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookResponse:
    """
    Update a book by ID.
    """
    service = WorkspaceService(db)
    book = service.update_book(book_id=book_id, current_user_id=current_user.id, name=data.name)
    return BookResponse.model_validate(book)


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a book by ID.
    """
    service = WorkspaceService(db)
    service.delete_book(book_id=book_id, current_user_id=current_user.id)
