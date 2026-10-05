import logging
import os
import sys
import typing
import json
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.storage import storage_service

# Ensure application logs at INFO level to console stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("app").setLevel(logging.INFO)


class UnicodeJSONResponse(JSONResponse):
    """
    Custom JSONResponse subclass that forces ensure_ascii=False so that
    Unicode characters (e.g. 27°C, Ω, µ, π, ×, °, ⁻³) are rendered directly
    in API JSON responses rather than escaped as \\uXXXX.
    """
    def render(self, content: typing.Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    default_response_class=UnicodeJSONResponse,
)

cors_origins_raw = getattr(settings, "CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
if not cors_origins or cors_origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

from uuid import UUID
from fastapi import Depends, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User


def verify_storage_file_access(db: Session, current_user: User, file_path: str) -> None:
    """
    UK GDPR Art. 5(1)(f) & Art. 32 Access Control Enforcement:
    Validates that the authenticated user owns or has access to the workspace
    associated with the requested stored asset.
    """
    norm = file_path.replace("\\", "/").strip("/")
    parts = [p for p in norm.split("/") if p and p != "storage"]
    if not parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")

    category = parts[0].lower()
    if len(parts) >= 2:
        resource_id_str = parts[1]
        try:
            resource_uuid = UUID(resource_id_str)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid resource identifier in path.")

        if category == "documents":
            from app.models.document import Document
            from app.models.book import Book
            from app.models.subject import Subject
            from app.models.workspace import Workspace
            from sqlalchemy import select

            stmt = (
                select(Workspace.owner_id)
                .select_from(Document)
                .join(Book, Document.book_id == Book.id)
                .join(Subject, Book.subject_id == Subject.id)
                .join(Workspace, Subject.workspace_id == Workspace.id)
                .where(Document.id == resource_uuid, Document.deleted_at.is_(None))
            )
            owner_id = db.execute(stmt).scalar_one_or_none()
            if not owner_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
            if owner_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this document.")

        elif category == "reference_papers":
            from app.models.reference_paper import ReferencePaper
            from app.models.workspace import Workspace
            from sqlalchemy import select

            stmt = (
                select(Workspace.owner_id)
                .select_from(ReferencePaper)
                .join(Workspace, ReferencePaper.workspace_id == Workspace.id)
                .where(ReferencePaper.id == resource_uuid, ReferencePaper.deleted_at.is_(None))
            )
            owner_id = db.execute(stmt).scalar_one_or_none()
            if not owner_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference paper not found.")
            if owner_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this reference paper.")

        elif category == "generated_papers":
            from app.models.generated_paper import GeneratedPaper
            from sqlalchemy import select

            stmt = select(GeneratedPaper.user_id).where(
                GeneratedPaper.id == resource_uuid,
                GeneratedPaper.deleted_at.is_(None)
            )
            owner_id = db.execute(stmt).scalar_one_or_none()
            if not owner_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated paper not found.")
            if owner_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this generated paper.")


# Storage file serving route (supports both AWS S3 and Local storage transparently with inline preview)
@app.api_route("/storage/{file_path:path}", methods=["GET", "HEAD"])
def serve_storage_file(
    file_path: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Enforce directory traversal security
    path_segments = file_path.replace("\\", "/").split("/")
    if ".." in path_segments:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    # Enforce UK GDPR Art. 5(1)(f) & Art. 32 tenant authorization
    verify_storage_file_access(db, current_user, file_path)

    try:
        if not storage_service.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found in storage.")
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=400, detail="Invalid file path.")

    byte_range = request.headers.get("range")
    stream, length, media_type, content_range, status_code = storage_service.get_range_stream(file_path, byte_range)
    resolved_media_type = storage_service.resolve_content_type(file_path, media_type)
    safe_filename = os.path.basename(file_path) or "document.pdf"

    headers = {
        "Content-Disposition": f'inline; filename="{safe_filename}"',
        "Accept-Ranges": "bytes",
    }
    if length > 0:
        headers["Content-Length"] = str(length)
    if content_range:
        headers["Content-Range"] = content_range

    if request.method == "HEAD":
        if hasattr(stream, "close"):
            stream.close()
        return Response(
            status_code=status_code,
            headers=headers,
            media_type=resolved_media_type,
        )

    def iter_stream():
        try:
            if hasattr(stream, "iter_chunks"):
                for chunk in stream.iter_chunks(chunk_size=65536):
                    yield chunk
            elif hasattr(stream, "read"):
                bytes_left = length if (content_range and length > 0) else None
                while True:
                    to_read = min(65536, bytes_left) if bytes_left is not None else 65536
                    chunk = stream.read(to_read)
                    if not chunk:
                        break
                    yield chunk
                    if bytes_left is not None:
                        bytes_left -= len(chunk)
                        if bytes_left <= 0:
                            break
            else:
                for chunk in stream:
                    yield chunk
        finally:
            if hasattr(stream, "close"):
                stream.close()

    return StreamingResponse(
        iter_stream(),
        status_code=status_code,
        media_type=resolved_media_type,
        headers=headers,
    )

app.include_router(api_router)

