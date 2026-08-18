from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentUploadResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    book_id: UUID = Form(...),
    chapter_id: Optional[UUID] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document (PDF or PPTX) to a book or chapter for asynchronous processing.
    """
    service = DocumentService(db)
    doc = service.upload_document(
        current_user_id=current_user.id,
        file=file,
        book_id=book_id,
        chapter_id=chapter_id,
    )
    return DocumentUploadResponse(id=doc.id, status=doc.processing_status)


@router.get("/{document_id}", response_model=DocumentResponse, status_code=status.HTTP_200_OK)
def get_document_status(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """
    Retrieve document processing status and metadata by document ID.
    """
    service = DocumentService(db)
    doc = service.get_document(current_user_id=current_user.id, document_id=document_id)
    return DocumentResponse.model_validate(doc)
