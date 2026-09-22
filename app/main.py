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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage file serving route (supports both AWS S3 and Local storage transparently with inline preview)
@app.api_route("/storage/{file_path:path}", methods=["GET", "HEAD"])
def serve_storage_file(file_path: str, request: Request):
    if not storage_service.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found in storage.")

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

