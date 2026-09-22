import logging
import os
import sys
import typing
import json
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

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

# Ensure local storage directory exists and mount static files (matching vigilens-backend pattern)
os.makedirs("storage", exist_ok=True)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

app.include_router(api_router)

