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
        stmt = select(Subject).where(Subject.id == subject_id, Subject.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_subjects_by_workspace(self, workspace_id: UUID) -> List[Subject]:
        stmt = (
            select(Subject)
            .where(Subject.workspace_id == workspace_id, Subject.deleted_at.is_(None))
            .order_by(Subject.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_subject_by_workspace_and_name(self, workspace_id: UUID, name: str) -> Optional[Subject]:
        stmt = select(Subject).where(
            Subject.workspace_id == workspace_id,
            Subject.name == name.strip(),
            Subject.deleted_at.is_(None),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def update_subject(self, subject: Subject, name: Optional[str] = None) -> Subject:
        if name is not None:
            subject.name = name.strip()
        self.db.commit()
        self.db.refresh(subject)
        return subject

    def delete_subject(self, subject: Subject) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import update
        from app.models.book import Book
        from app.models.chapter import Chapter
        from app.models.topic import Topic
        from app.models.document import Document, DocumentPage, DocumentChunk
        from app.models.reference_paper import ReferencePaper, ReferencePaperPage
        from app.models.generated_paper import GeneratedPaper

        now = datetime.now(timezone.utc)
        subject.deleted_at = now

        # 1. Soft delete Books
        self.db.execute(
            update(Book).where(Book.subject_id == subject.id, Book.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 2. Soft delete Chapters & Topics
        book_ids_stmt = select(Book.id).where(Book.subject_id == subject.id)
        chapter_ids_stmt = select(Chapter.id).where(Chapter.book_id.in_(book_ids_stmt))
        self.db.execute(
            update(Chapter).where(Chapter.book_id.in_(book_ids_stmt), Chapter.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(Topic).where(Topic.chapter_id.in_(chapter_ids_stmt), Topic.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 3. Soft delete Documents, Pages, Chunks
        doc_ids_stmt = select(Document.id).where(Document.book_id.in_(book_ids_stmt))
        self.db.execute(
            update(Document).where(Document.book_id.in_(book_ids_stmt), Document.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentPage).where(DocumentPage.document_id.in_(doc_ids_stmt), DocumentPage.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentChunk).where(DocumentChunk.subject_id == subject.id, DocumentChunk.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 4. Soft delete ReferencePapers & Pages
        ref_ids_stmt = select(ReferencePaper.id).where(ReferencePaper.subject_id == subject.id)
        self.db.execute(
            update(ReferencePaper).where(ReferencePaper.subject_id == subject.id, ReferencePaper.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(ReferencePaperPage).where(ReferencePaperPage.reference_paper_id.in_(ref_ids_stmt), ReferencePaperPage.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 5. Soft delete GeneratedPapers
        self.db.execute(
            update(GeneratedPaper).where(GeneratedPaper.subject_id == subject.id, GeneratedPaper.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.commit()

    # Book operations
    def create_book(self, subject_id: UUID, name: str) -> Book:
        book = Book(subject_id=subject_id, name=name.strip())
        self.db.add(book)
        self.db.commit()
        self.db.refresh(book)
        return book

    def get_book_by_id(self, book_id: UUID) -> Optional[Book]:
        stmt = select(Book).where(Book.id == book_id, Book.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_books_by_subject(self, subject_id: UUID) -> List[Book]:
        stmt = select(Book).where(Book.subject_id == subject_id, Book.deleted_at.is_(None)).order_by(Book.created_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    def update_book(self, book: Book, name: Optional[str] = None) -> Book:
        if name is not None:
            book.name = name.strip()
        self.db.commit()
        self.db.refresh(book)
        return book

    def delete_book(self, book: Book) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import update
        from app.models.chapter import Chapter
        from app.models.topic import Topic
        from app.models.document import Document, DocumentPage, DocumentChunk
        from app.models.generated_paper import GeneratedPaper

        now = datetime.now(timezone.utc)
        book.deleted_at = now

        # 1. Soft delete Chapters & Topics
        chapter_ids_stmt = select(Chapter.id).where(Chapter.book_id == book.id)
        self.db.execute(
            update(Chapter).where(Chapter.book_id == book.id, Chapter.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(Topic).where(Topic.chapter_id.in_(chapter_ids_stmt), Topic.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 2. Soft delete Documents, Pages, Chunks
        doc_ids_stmt = select(Document.id).where(Document.book_id == book.id)
        self.db.execute(
            update(Document).where(Document.book_id == book.id, Document.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentPage).where(DocumentPage.document_id.in_(doc_ids_stmt), DocumentPage.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentChunk).where(DocumentChunk.book_id == book.id, DocumentChunk.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 3. Soft delete GeneratedPapers
        self.db.execute(
            update(GeneratedPaper).where(GeneratedPaper.book_id == book.id, GeneratedPaper.deleted_at.is_(None)).values(deleted_at=now)
        )
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
        stmt = select(Chapter).where(Chapter.id == chapter_id, Chapter.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_chapter_by_book_and_number(self, book_id: UUID, chapter_number: int) -> Optional[Chapter]:
        stmt = select(Chapter).where(
            Chapter.book_id == book_id,
            Chapter.chapter_number == chapter_number,
            Chapter.deleted_at.is_(None),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_chapters_by_book(self, book_id: UUID) -> List[Chapter]:
        stmt = (
            select(Chapter)
            .where(Chapter.book_id == book_id, Chapter.deleted_at.is_(None))
            .order_by(Chapter.chapter_number.asc())
        )
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
                DocumentChunk.deleted_at.is_(None),
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
                DocumentChunk.deleted_at.is_(None),
                DocumentChunk.page_number >= start_page,
                DocumentChunk.page_number <= end_page,
            )
            .values(chapter_id=chapter_id)
        )
        res = self.db.execute(assign_stmt)
        self.db.commit()
        return res.rowcount

    def delete_chapter(self, chapter: Chapter) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import update
        from app.models.topic import Topic
        from app.models.document import Document, DocumentPage, DocumentChunk

        now = datetime.now(timezone.utc)
        chapter.deleted_at = now

        # 1. Soft delete Topics
        self.db.execute(
            update(Topic).where(Topic.chapter_id == chapter.id, Topic.deleted_at.is_(None)).values(deleted_at=now)
        )
        # 2. Soft delete Documents, Pages, Chunks specifically associated with Chapter
        doc_ids_stmt = select(Document.id).where(Document.chapter_id == chapter.id)
        self.db.execute(
            update(Document).where(Document.chapter_id == chapter.id, Document.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentPage).where(DocumentPage.document_id.in_(doc_ids_stmt), DocumentPage.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.execute(
            update(DocumentChunk).where(DocumentChunk.chapter_id == chapter.id, DocumentChunk.deleted_at.is_(None)).values(deleted_at=now)
        )
        self.db.commit()

