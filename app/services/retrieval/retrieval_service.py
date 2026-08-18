import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories.document_repository import DocumentRepository
from app.services.embeddings.embedding_service import EmbeddingService
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        db: Session,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.workspace_service = WorkspaceService(db)
        self.embedding_service = embedding_service or GeminiEmbeddingService()

    def retrieve_context(
        self,
        current_user_id: UUID,
        workspace_id: UUID,
        query: str,
        subject_id: Optional[UUID] = None,
        book_id: Optional[UUID] = None,
        chapter_id: Optional[UUID] = None,
        document_id: Optional[UUID] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        # 1. Enforce Workspace Ownership Security
        self.workspace_service.get_workspace(workspace_id, current_user_id)

        # 2. Input validations
        if not query or not query.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query cannot be empty.")

        if len(query) > 2000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query exceeds maximum allowed length of 2000 characters.")

        top_k = max(1, min(top_k, 20))

        # 3. Generate query vector embedding
        try:
            query_vector = self.embedding_service.generate_embedding(query)
        except Exception as exc:
            logger.error(f"Failed to generate query embedding: {exc}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Embedding service unavailable.")

        # 4. Search pgvector
        results = self.doc_repo.search_similar_chunks(
            workspace_id=workspace_id,
            query_vector=query_vector,
            top_k=top_k,
            subject_id=subject_id,
            book_id=book_id,
            chapter_id=chapter_id,
            document_id=document_id,
        )

        retrieved_chunks = []
        for chunk, distance in results:
            retrieved_chunks.append({
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "page_number": chunk.page_number,
                "chapter_id": str(chunk.chapter_id) if chunk.chapter_id else None,
                "book_id": str(chunk.book_id),
                "subject_id": str(chunk.subject_id),
                "workspace_id": str(chunk.workspace_id),
                "content": chunk.content,
                "content_type": chunk.content_type,
                "distance": round(distance, 4),
                "metadata": chunk.metadata_json or {},
            })

        return retrieved_chunks

    def retrieve_as_langchain_documents(
        self,
        current_user_id: UUID,
        workspace_id: UUID,
        query: str,
        subject_id: Optional[UUID] = None,
        book_id: Optional[UUID] = None,
        chapter_id: Optional[UUID] = None,
        document_id: Optional[UUID] = None,
        top_k: int = 5,
    ) -> List[Any]:
        """
        Retrieve chunks with strict multi-tenant authorization and return as LangChain Document instances.
        """
        chunks = self.retrieve_context(
            current_user_id=current_user_id,
            workspace_id=workspace_id,
            query=query,
            subject_id=subject_id,
            book_id=book_id,
            chapter_id=chapter_id,
            document_id=document_id,
            top_k=top_k,
        )
        try:
            from langchain_core.documents import Document as LCDocument

            return [
                LCDocument(
                    page_content=c["content"],
                    metadata={
                        "chunk_id": c["chunk_id"],
                        "document_id": c["document_id"],
                        "page_number": c["page_number"],
                        "chapter_id": c["chapter_id"],
                        "book_id": c["book_id"],
                        "subject_id": c["subject_id"],
                        "workspace_id": c["workspace_id"],
                        "distance": c["distance"],
                    },
                )
                for c in chunks
            ]
        except ImportError:
            return chunks
