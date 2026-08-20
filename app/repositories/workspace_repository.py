from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.models.chapter import Chapter
from app.models.subject import Subject
from app.models.workspace import Workspace


class WorkspaceRepository:
    def __init__(self, db: Session):
        self.db = db

    # Workspace operations
    def create_workspace(self, owner_id: UUID, name: str) -> Workspace:
        workspace = Workspace(owner_id=owner_id, name=name.strip())
        self.db.add(workspace)
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def get_workspace_by_id(self, workspace_id: UUID) -> Optional[Workspace]:
        return self.db.get(Workspace, workspace_id)

    def get_workspaces_by_owner(self, owner_id: UUID) -> List[Workspace]:
        stmt = select(Workspace).where(Workspace.owner_id == owner_id).order_by(Workspace.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def update_workspace(self, workspace: Workspace, name: Optional[str] = None) -> Workspace:
        if name is not None:
            workspace.name = name.strip()
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def delete_workspace(self, workspace: Workspace) -> None:
        self.db.delete(workspace)
        self.db.commit()

    # Subject operations
    def create_subject(self, workspace_id: UUID, name: str) -> Subject:
        subject = Subject(workspace_id=workspace_id, name=name.strip())
        self.db.add(subject)
        self.db.commit()
        self.db.refresh(subject)
        return subject

    def get_subject_by_id(self, subject_id: UUID) -> Optional[Subject]:
        return self.db.get(Subject, subject_id)

    def get_subjects_by_workspace(self, workspace_id: UUID) -> List[Subject]:
        stmt = select(Subject).where(Subject.workspace_id == workspace_id).order_by(Subject.created_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_subject_by_workspace_and_name(self, workspace_id: UUID, name: str) -> Optional[Subject]:
        stmt = select(Subject).where(Subject.workspace_id == workspace_id, Subject.name == name.strip())
        return self.db.execute(stmt).scalar_one_or_none()

    def update_subject(self, subject: Subject, name: Optional[str] = None) -> Subject:
        if name is not None:
            subject.name = name.strip()
        self.db.commit()
        self.db.refresh(subject)
        return subject

    def delete_subject(self, subject: Subject) -> None:
        self.db.delete(subject)
        self.db.commit()

    # Book operations
    def create_book(self, subject_id: UUID, name: str) -> Book:
        book = Book(subject_id=subject_id, name=name.strip())
        self.db.add(book)
        self.db.commit()
        self.db.refresh(book)
        return book

    def get_book_by_id(self, book_id: UUID) -> Optional[Book]:
        return self.db.get(Book, book_id)

    def get_books_by_subject(self, subject_id: UUID) -> List[Book]:
        stmt = select(Book).where(Book.subject_id == subject_id).order_by(Book.created_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    def update_book(self, book: Book, name: Optional[str] = None) -> Book:
        if name is not None:
            book.name = name.strip()
        self.db.commit()
        self.db.refresh(book)
        return book

    def delete_book(self, book: Book) -> None:
        self.db.delete(book)
        self.db.commit()

    # Chapter operations
    def create_chapter(
        self,
        book_id: UUID,
        chapter_number: int,
        name: str,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> Chapter:
        chapter = Chapter(
            book_id=book_id,
            chapter_number=chapter_number,
            name=name.strip(),
            start_page=start_page,
            end_page=end_page,
        )
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def get_chapter_by_id(self, chapter_id: UUID) -> Optional[Chapter]:
        return self.db.get(Chapter, chapter_id)

    def get_chapter_by_book_and_number(self, book_id: UUID, chapter_number: int) -> Optional[Chapter]:
        stmt = select(Chapter).where(Chapter.book_id == book_id, Chapter.chapter_number == chapter_number)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_chapters_by_book(self, book_id: UUID) -> List[Chapter]:
        stmt = select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.chapter_number.asc())
        return list(self.db.execute(stmt).scalars().all())

    def update_chapter(
        self,
        chapter: Chapter,
        chapter_number: Optional[int] = None,
        name: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> Chapter:
        if chapter_number is not None:
            chapter.chapter_number = chapter_number
        if name is not None:
            chapter.name = name.strip()
        if start_page is not None:
            chapter.start_page = start_page
        if end_page is not None:
            chapter.end_page = end_page
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def reassign_chunks_for_page_range(
        self,
        book_id: UUID,
        chapter_id: UUID,
        start_page: int,
        end_page: int,
    ) -> int:
        from app.models.document import DocumentChunk
        from sqlalchemy import update

        # Clear any chunks previously assigned to this chapter outside new page range
        clear_stmt = (
            update(DocumentChunk)
            .where(
                DocumentChunk.book_id == book_id,
                DocumentChunk.chapter_id == chapter_id,
                (DocumentChunk.page_number < start_page) | (DocumentChunk.page_number > end_page),
            )
            .values(chapter_id=None)
        )
        self.db.execute(clear_stmt)

        # Set chapter_id for all DocumentChunks in this book within [start_page, end_page]
        assign_stmt = (
            update(DocumentChunk)
            .where(
                DocumentChunk.book_id == book_id,
                DocumentChunk.page_number >= start_page,
                DocumentChunk.page_number <= end_page,
            )
            .values(chapter_id=chapter_id)
        )
        res = self.db.execute(assign_stmt)
        self.db.commit()
        return res.rowcount

    def delete_chapter(self, chapter: Chapter) -> None:
        self.db.delete(chapter)
        self.db.commit()
