from typing import Any, Dict, List, Optional
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reference_paper import ReferencePaper, ReferencePaperPage


class ReferencePaperRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_reference_paper(
        self,
        workspace_id: UUID,
        subject_id: UUID,
        title: str,
        original_filename: str,
        stored_path: str,
        mime_type: str,
        file_size: int,
        year: Optional[int] = None,
        exam_type: Optional[str] = None,
        paper_id: Optional[UUID] = None,
    ) -> ReferencePaper:
        paper = ReferencePaper(
            id=paper_id or uuid.uuid4(),
            workspace_id=workspace_id,
            subject_id=subject_id,
            title=title.strip(),
            year=year,
            exam_type=exam_type.strip() if exam_type else None,
            original_filename=original_filename,
            stored_path=stored_path,
            mime_type=mime_type,
            file_size=file_size,
        )
        self.db.add(paper)
        self.db.commit()
        self.db.refresh(paper)
        return paper

    def save_reference_paper_pages(
        self,
        paper_id: UUID,
        pages_data: List[Dict[str, Any]],
    ) -> List[ReferencePaperPage]:
        # Delete existing pages if any
        self.db.expire_all()
        self.db.query(ReferencePaperPage).filter(
            ReferencePaperPage.reference_paper_id == paper_id
        ).delete(synchronize_session=False)
        self.db.commit()

        created_pages = []
        for p_info in pages_data:
            page = ReferencePaperPage(
                reference_paper_id=paper_id,
                page_number=p_info["page_number"],
                content_type=p_info.get("content_type", "PAGE"),
                text_content=p_info.get("text_content", ""),
            )
            self.db.add(page)
            created_pages.append(page)

        self.db.commit()
        return created_pages

    def get_reference_paper(self, paper_id: UUID) -> Optional[ReferencePaper]:
        stmt = select(ReferencePaper).where(ReferencePaper.id == paper_id, ReferencePaper.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_reference_paper_by_id(self, paper_id: UUID) -> Optional[ReferencePaper]:
        return self.get_reference_paper(paper_id)

    def get_reference_paper_pages(self, paper_id: UUID) -> List[ReferencePaperPage]:
        stmt = (
            select(ReferencePaperPage)
            .where(
                ReferencePaperPage.reference_paper_id == paper_id,
                ReferencePaperPage.deleted_at.is_(None),
            )
            .order_by(ReferencePaperPage.page_number.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_reference_papers_by_subject(
        self, workspace_id: UUID, subject_id: UUID
    ) -> List[ReferencePaper]:
        stmt = (
            select(ReferencePaper)
            .where(
                ReferencePaper.workspace_id == workspace_id,
                ReferencePaper.subject_id == subject_id,
                ReferencePaper.deleted_at.is_(None),
            )
            .order_by(ReferencePaper.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def save_blueprint_json(
        self, paper_id: UUID, blueprint_json: Dict[str, Any]
    ) -> Optional[ReferencePaper]:
        paper = self.get_reference_paper(paper_id)
        if paper:
            paper.blueprint_json = blueprint_json
            self.db.commit()
            self.db.refresh(paper)
            return paper
        return None

    def delete_reference_paper(self, paper_id: UUID) -> bool:
        from datetime import datetime, timezone
        from sqlalchemy import update

        paper = self.get_reference_paper(paper_id)
        if paper and paper.deleted_at is None:
            now = datetime.now(timezone.utc)
            paper.deleted_at = now
            self.db.execute(
                update(ReferencePaperPage)
                .where(ReferencePaperPage.reference_paper_id == paper_id, ReferencePaperPage.deleted_at.is_(None))
                .values(deleted_at=now)
            )
            self.db.commit()
            return True
        return False


