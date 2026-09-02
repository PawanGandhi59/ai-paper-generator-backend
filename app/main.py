import os
import typing
import json
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings


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

# Ensure local storage directory exists and mount static files (matching vigilens-backend pattern)
os.makedirs("storage", exist_ok=True)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

app.include_router(api_router)

