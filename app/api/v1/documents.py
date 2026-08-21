from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_from_header_or_query
from app.core.database import get_db
from app.models.user import User
from app.schemas.document import DocumentPageResponse, DocumentResponse, DocumentUploadResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    book_id: UUID = Form(...),
    chapter_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document (PDF or PPTX) to a book or chapter for asynchronous processing.
    """
    parsed_chapter_id: Optional[UUID] = None
    if chapter_id:
        clean_val = chapter_id.strip()
        if clean_val and clean_val.lower() not in ("string", "null", "undefined", "none"):
            try:
                parsed_chapter_id = UUID(clean_val)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chapter_id format. Must be a valid UUID.",
                )

    service = DocumentService(db)
    doc = service.upload_document(
        current_user_id=current_user.id,
        file=file,
        book_id=book_id,
        chapter_id=parsed_chapter_id,
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


@router.get("/{document_id}/pages", response_model=List[DocumentPageResponse], status_code=status.HTTP_200_OK)
def get_document_pages(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DocumentPageResponse]:
    """
    Get extracted page-by-page text content for document previewing.
    """
    service = DocumentService(db)
    doc = service.get_document(current_user_id=current_user.id, document_id=document_id)
    pages = service.doc_repo.get_document_pages(doc.id)
    return [DocumentPageResponse.model_validate(p) for p in pages]
