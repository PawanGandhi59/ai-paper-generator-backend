import os
import shutil

import zipfile
from typing import Optional
import uuid
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.document_repository import DocumentRepository
from app.services.workspace_service import WorkspaceService
from app.worker import process_document


ALLOWED_EXTENSIONS = {".pdf", ".pptx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/x-pptx",
    "application/octet-stream",
}


def validate_file_signature(header_bytes: bytes, extension: str, file_path: str):
    """
    Validate binary magic signatures to prevent file extension / MIME spoofing.
    """
    ext_lower = extension.lower()
    if ext_lower == ".pdf":
        if not header_bytes.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PDF file format. Missing %PDF header signature.",
            )
    elif ext_lower == ".pptx":
        if not header_bytes.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PPTX file format. Missing PK zip header signature.",
            )
        # Verify valid Zip container structure for PPTX
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                namelist = zf.namelist()
                if not any("ppt/" in name for name in namelist):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid PPTX file structure. Missing PowerPoint presentation contents.",
                    )
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Corrupt or invalid PPTX zip package.",
            )


class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.workspace_service = WorkspaceService(db)

    def upload_document(
        self,
        current_user_id: UUID,
        file: UploadFile,
        book_id: UUID,
        chapter_id: Optional[UUID] = None,
    ):
        # 1. Validate Book & Chapter ownership
        book = self.workspace_service.get_book(book_id, current_user_id)
        if chapter_id:
            chapter = self.workspace_service.get_chapter(chapter_id, current_user_id)
            if chapter.book_id != book.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Chapter does not belong to the specified book.",
                )

        # 2. Validate Extension & Content Type
        original_filename = os.path.basename(file.filename or "file")
        _, ext = os.path.splitext(original_filename)
        ext_lower = ext.lower()

        if ext_lower not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Only .pdf and .pptx files are allowed.",
            )

        content_type = file.content_type or "application/octet-stream"
        if content_type.lower() not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported MIME type '{content_type}'.",
            )

        # 3. Create local storage directory & streaming file write
        doc_id = uuid.uuid4()
        storage_root = settings.LOCAL_STORAGE_PATH
        doc_dir = os.path.join(storage_root, "documents", str(doc_id))
        os.makedirs(doc_dir, exist_ok=True)
        stored_path = os.path.join(doc_dir, f"original{ext_lower}")

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        total_written = 0
        header_bytes = b""

        try:
            with open(stored_path, "wb") as out_file:
                while True:
                    chunk = file.file.read(65536)  # 64KB chunk
                    if not chunk:
                        break

                    if not header_bytes:
                        header_bytes = chunk[:16]

                    total_written += len(chunk)
                    if total_written > max_bytes:
                        out_file.close()
                        shutil.rmtree(doc_dir, ignore_errors=True)
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File size exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB}MB.",
                        )
                    out_file.write(chunk)

            if total_written == 0:
                shutil.rmtree(doc_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty.",
                )

            # 4. Validate Magic File Signature & Structure
            validate_file_signature(header_bytes, ext_lower, stored_path)

        except HTTPException:
            shutil.rmtree(doc_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(doc_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process uploaded file: {str(exc)}",
            )

        # 5. Create database record
        doc = self.doc_repo.create_document(
            document_id=doc_id,
            book_id=book.id,
            chapter_id=chapter_id,
            original_filename=original_filename,
            stored_path=stored_path,
            mime_type=content_type,
            file_size=total_written,
            processing_status="UPLOADED",
        )

        # 6. Queue asynchronous Celery task with failure rollback
        try:
            process_document.delay(str(doc.id))
        except Exception as queue_exc:
            print(f"Error: Celery task enqueue failed: {queue_exc}")
            shutil.rmtree(doc_dir, ignore_errors=True)
            self.doc_repo.delete_document(doc.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue document processing task. Please try again.",
            )

        return doc

    def get_document(self, current_user_id: UUID, document_id: UUID):
        doc = self.doc_repo.get_document_by_id(document_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )

        # Ownership validation
        self.workspace_service.get_book(doc.book_id, current_user_id)
        return doc
