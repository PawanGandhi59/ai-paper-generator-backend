import os
from typing import Any, Optional


def get_document_storage_url(doc: Any) -> Optional[str]:
    """
    Derives the accessible static URL for a Document object.
    FastAPI mounts `/storage` to serve files from the local storage root.
    """
    if not doc:
        return None

    stored_path = getattr(doc, "stored_path", None)
    if stored_path:
        norm = stored_path.replace("\\", "/")
        if "/storage/" in norm:
            return norm[norm.find("/storage/"):]
        if norm.startswith("storage/"):
            return "/" + norm

    doc_id = getattr(doc, "id", None)
    if doc_id:
        return f"/storage/documents/{doc_id}/original.pdf"

    return None


def is_textbook_document(doc: Any) -> bool:
    """
    Returns True if the document represents an uploaded textbook / study material,
    and NOT an output artifact like a generated paper PDF ('final.pdf' in 'generated_papers').
    """
    if not doc:
        return False
    if getattr(doc, "deleted_at", None) is not None:
        return False

    orig_name = getattr(doc, "original_filename", "") or ""
    stored_path = (getattr(doc, "stored_path", "") or "").replace("\\", "/")

    if orig_name == "final.pdf" or "generated_papers" in stored_path:
        return False

    return True
