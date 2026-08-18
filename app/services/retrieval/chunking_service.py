import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.models.document import DocumentPage


class ChunkingService:
    @staticmethod
    def chunk_document_pages(
        pages: List[DocumentPage],
        document_id: UUID,
        book_id: UUID,
        subject_id: UUID,
        workspace_id: UUID,
        chapter_id: Optional[UUID] = None,
        max_chunk_chars: int = 800,
        overlap_chars: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Structure-aware chunking preserving document pages, chapters, visual references, and metadata.
        """
        chunks_data = []
        global_chunk_index = 0

        for page in pages:
            text = (page.text_content or "").strip()
            page_meta = page.metadata_json or {}
            content_type = page.content_type or "PAGE"

            # If page text is short or empty, keep page as a single chunk (e.g., visual/image page)
            if not text or len(text) <= max_chunk_chars:
                chunks_data.append({
                    "chunk_index": global_chunk_index,
                    "document_id": document_id,
                    "document_page_id": page.id,
                    "chapter_id": chapter_id,
                    "book_id": book_id,
                    "subject_id": subject_id,
                    "workspace_id": workspace_id,
                    "page_number": page.page_number,
                    "content": text if text else f"[Page {page.page_number} Visual/Image Asset]",
                    "content_type": content_type,
                    "metadata_json": {
                        "page_number": page.page_number,
                        "image_path": page.image_path,
                        "image_count": page_meta.get("image_count", 0),
                        "ocr_applied": page_meta.get("ocr_applied", False),
                    },
                })
                global_chunk_index += 1
                continue

            # Structure-aware splitting by double-newlines (paragraphs) or sentences
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            current_chunk_text = ""

            for p in paragraphs:
                if len(current_chunk_text) + len(p) + 1 <= max_chunk_chars:
                    current_chunk_text = f"{current_chunk_text}\n\n{p}".strip()
                else:
                    if current_chunk_text:
                        chunks_data.append({
                            "chunk_index": global_chunk_index,
                            "document_id": document_id,
                            "document_page_id": page.id,
                            "chapter_id": chapter_id,
                            "book_id": book_id,
                            "subject_id": subject_id,
                            "workspace_id": workspace_id,
                            "page_number": page.page_number,
                            "content": current_chunk_text,
                            "content_type": content_type,
                            "metadata_json": {
                                "page_number": page.page_number,
                                "image_path": page.image_path,
                                "image_count": page_meta.get("image_count", 0),
                            },
                        })
                        global_chunk_index += 1
                        # Maintain overlap
                        overlap = current_chunk_text[-overlap_chars:] if len(current_chunk_text) > overlap_chars else ""
                        current_chunk_text = f"{overlap}\n\n{p}".strip()
                    else:
                        current_chunk_text = p

            if current_chunk_text:
                chunks_data.append({
                    "chunk_index": global_chunk_index,
                    "document_id": document_id,
                    "document_page_id": page.id,
                    "chapter_id": chapter_id,
                    "book_id": book_id,
                    "subject_id": subject_id,
                    "workspace_id": workspace_id,
                    "page_number": page.page_number,
                    "content": current_chunk_text,
                    "content_type": content_type,
                    "metadata_json": {
                        "page_number": page.page_number,
                        "image_path": page.image_path,
                        "image_count": page_meta.get("image_count", 0),
                    },
                })
                global_chunk_index += 1

        return chunks_data
