from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", status_code=status.HTTP_200_OK)
def check_health() -> dict[str, str]:
    """
    Basic application health check endpoint.
    """
    return {"status": "ok"}


@router.get("/db", status_code=status.HTTP_200_OK)
def check_db_health(db: Session = Depends(get_db)) -> dict[str, str]:
    """
    Database connectivity health check endpoint.
    """
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "database": "connected",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "error",
                "database": "disconnected",
                "error": str(exc),
            },
        ) from exc
