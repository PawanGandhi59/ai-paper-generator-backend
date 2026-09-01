import os
import shutil
from typing import List, Optional
import uuid
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.reference_paper_repository import ReferencePaperRepository
from app.services.processors.pdf_processor import PDFProcessor
from app.services.workspace_service import WorkspaceService


class ReferencePaperService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ReferencePaperRepository(db)
        self.workspace_service = WorkspaceService(db)

    def upload_reference_paper(
        self,
        current_user_id: UUID,
        subject_id: UUID,
        file: UploadFile,
        title: str,
        year: Optional[int] = None,
        exam_type: Optional[str] = None,
    ):
        # 1. Validate Subject ownership
        subject = self.workspace_service.get_subject(subject_id, current_user_id)
        workspace_id = subject.workspace_id

        # 2. Validate PDF format & MIME type
        original_filename = os.path.basename(file.filename or "reference_paper.pdf")
        _, ext = os.path.splitext(original_filename)
        ext_lower = ext.lower()

        if ext_lower != ".pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Only .pdf files are allowed for reference papers.",
            )

        content_type = file.content_type or "application/pdf"

        # 3. Create storage directory & write file safely
        paper_id = uuid.uuid4()
        storage_root = settings.LOCAL_STORAGE_PATH
        paper_dir = os.path.join(storage_root, "reference_papers", str(paper_id))
        os.makedirs(paper_dir, exist_ok=True)
        stored_path = os.path.join(paper_dir, "original.pdf")

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        total_written = 0
        header_bytes = b""

        try:
            with open(stored_path, "wb") as out_file:
                while True:
                    chunk = file.file.read(65536)
                    if not chunk:
                        break

                    if not header_bytes:
                        header_bytes = chunk[:16]

                    total_written += len(chunk)
                    if total_written > max_bytes:
                        out_file.close()
                        shutil.rmtree(paper_dir, ignore_errors=True)
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File size exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB}MB.",
                        )
                    out_file.write(chunk)

            if total_written == 0:
                shutil.rmtree(paper_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty.",
                )

            # Validate magic PDF header %PDF-
            if not header_bytes.startswith(b"%PDF-"):
                shutil.rmtree(paper_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid PDF file format. Missing %PDF header signature.",
                )

            # 4. Extract PDF text pages using PDFProcessor
            pages_data = PDFProcessor.process_pdf(stored_path, paper_dir)

            # Validate overall text quality across all extracted pages
            has_readable_text = any(
                PDFProcessor.is_meaningful_text(p.get("text_content", ""))
                for p in pages_data
            )
            if not has_readable_text:
                shutil.rmtree(paper_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not extract readable text content from reference paper pages. OCR processing failed or text is unreadable.",
                )

            # 5. Create database records
            paper = self.repo.create_reference_paper(
                paper_id=paper_id,
                workspace_id=workspace_id,
                subject_id=subject.id,
                title=title,
                original_filename=original_filename,
                stored_path=stored_path,
                mime_type=content_type,
                file_size=total_written,
                year=year,
                exam_type=exam_type,
            )

            if pages_data:
                self.repo.save_reference_paper_pages(paper_id, pages_data)

            # Refresh to load pages relationship
            self.db.refresh(paper)
            return paper

        except HTTPException:
            shutil.rmtree(paper_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(paper_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process uploaded reference paper: {str(exc)}",
            )

    def list_reference_papers(self, current_user_id: UUID, subject_id: Optional[UUID] = None):
        if subject_id:
            subject = self.workspace_service.get_subject(subject_id, current_user_id)
            return self.repo.list_reference_papers_by_subject(
                workspace_id=subject.workspace_id,
                subject_id=subject.id,
            )
        return self.repo.list_reference_papers_by_user(current_user_id)

    def get_reference_paper(self, current_user_id: UUID, paper_id: UUID):
        paper = self.repo.get_reference_paper_by_id(paper_id)
        if not paper:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reference paper not found.",
            )
        # Security validation via user Workspace ownership
        self.workspace_service.get_workspace(paper.workspace_id, current_user_id)
        return paper

    def delete_reference_paper(self, current_user_id: UUID, paper_id: UUID) -> None:
        paper = self.get_reference_paper(current_user_id, paper_id)
        stored_path = os.path.abspath(paper.stored_path) if paper.stored_path else None
        paper_dir = os.path.dirname(stored_path) if stored_path else None

        # 1. Delete DB record
        self.repo.delete_reference_paper(paper.id)

        # 2. Delete storage files
        if paper_dir and os.path.exists(paper_dir):
            shutil.rmtree(paper_dir, ignore_errors=True)







