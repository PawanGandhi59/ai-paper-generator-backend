from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.chapter import Chapter
from app.models.subject import Subject
from app.models.workspace import Workspace
from app.repositories.workspace_repository import WorkspaceRepository


class WorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WorkspaceRepository(db)

    # Workspace operations
    def create_workspace(self, owner_id: UUID, name: str) -> Workspace:
        return self.repo.create_workspace(owner_id=owner_id, name=name)

    def get_workspace(self, workspace_id: UUID, current_user_id: UUID) -> Workspace:
        workspace = self.repo.get_workspace_by_id(workspace_id)
        if not workspace or workspace.owner_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )
        return workspace

    def list_workspaces(self, current_user_id: UUID) -> List[Workspace]:
        return self.repo.get_workspaces_by_owner(current_user_id)

    def update_workspace(self, workspace_id: UUID, current_user_id: UUID, name: Optional[str] = None) -> Workspace:
        workspace = self.get_workspace(workspace_id, current_user_id)
        return self.repo.update_workspace(workspace, name=name)

    def delete_workspace(self, workspace_id: UUID, current_user_id: UUID) -> None:
        workspace = self.get_workspace(workspace_id, current_user_id)
        self.repo.delete_workspace(workspace)

    # Subject operations
    def create_subject(self, workspace_id: UUID, current_user_id: UUID, name: str) -> Subject:
        workspace = self.get_workspace(workspace_id, current_user_id)
        existing = self.repo.get_subject_by_workspace_and_name(workspace.id, name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Subject '{name.strip()}' already exists in this workspace.",
            )
        return self.repo.create_subject(workspace_id=workspace.id, name=name)

    def list_subjects(self, workspace_id: UUID, current_user_id: UUID) -> List[Subject]:
        workspace = self.get_workspace(workspace_id, current_user_id)
        return self.repo.get_subjects_by_workspace(workspace.id)

    def get_subject(self, subject_id: UUID, current_user_id: UUID) -> Subject:
        subject = self.repo.get_subject_by_id(subject_id)
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subject not found.",
            )
        # Verify workspace ownership
        self.get_workspace(subject.workspace_id, current_user_id)
        return subject

    def update_subject(self, subject_id: UUID, current_user_id: UUID, name: Optional[str] = None) -> Subject:
        subject = self.get_subject(subject_id, current_user_id)
        if name is not None and name.strip() != subject.name:
            existing = self.repo.get_subject_by_workspace_and_name(subject.workspace_id, name)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Subject '{name.strip()}' already exists in this workspace.",
                )
        return self.repo.update_subject(subject, name=name)

    def delete_subject(self, subject_id: UUID, current_user_id: UUID) -> None:
        subject = self.get_subject(subject_id, current_user_id)
        self.repo.delete_subject(subject)

    # Book operations
    def create_book(self, subject_id: UUID, current_user_id: UUID, name: str) -> Book:
        subject = self.get_subject(subject_id, current_user_id)
        return self.repo.create_book(subject_id=subject.id, name=name)

    def list_books(self, subject_id: UUID, current_user_id: UUID) -> List[Book]:
        subject = self.get_subject(subject_id, current_user_id)
        return self.repo.get_books_by_subject(subject.id)

    def get_book(self, book_id: UUID, current_user_id: UUID) -> Book:
        book = self.repo.get_book_by_id(book_id)
        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found.",
            )
        # Verify subject/workspace ownership
        self.get_subject(book.subject_id, current_user_id)
        return book

    def update_book(self, book_id: UUID, current_user_id: UUID, name: Optional[str] = None) -> Book:
        book = self.get_book(book_id, current_user_id)
        return self.repo.update_book(book, name=name)

    def delete_book(self, book_id: UUID, current_user_id: UUID) -> None:
        book = self.get_book(book_id, current_user_id)
        self.repo.delete_book(book)

    # Chapter operations
    def create_chapter(self, book_id: UUID, current_user_id: UUID, chapter_number: int, name: str) -> Chapter:
        book = self.get_book(book_id, current_user_id)
        return self.repo.create_chapter(book_id=book.id, chapter_number=chapter_number, name=name)

    def list_chapters(self, book_id: UUID, current_user_id: UUID) -> List[Chapter]:
        book = self.get_book(book_id, current_user_id)
        return self.repo.get_chapters_by_book(book.id)

    def get_chapter(self, chapter_id: UUID, current_user_id: UUID) -> Chapter:
        chapter = self.repo.get_chapter_id(chapter_id) if hasattr(self.repo, 'get_chapter_id') else self.repo.get_chapter_by_id(chapter_id)
        if not chapter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chapter not found.",
            )
        # Verify book/subject/workspace ownership
        self.get_book(chapter.book_id, current_user_id)
        return chapter

    def update_chapter(
        self,
        chapter_id: UUID,
        current_user_id: UUID,
        chapter_number: Optional[int] = None,
        name: Optional[str] = None,
    ) -> Chapter:
        chapter = self.get_chapter(chapter_id, current_user_id)
        return self.repo.update_chapter(chapter, chapter_number=chapter_number, name=name)

    def delete_chapter(self, chapter_id: UUID, current_user_id: UUID) -> None:
        chapter = self.get_chapter(chapter_id, current_user_id)
        self.repo.delete_chapter(chapter)
