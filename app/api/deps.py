from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    FastAPI dependency validating JWT Bearer access token and retrieving authenticated User.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    return user


def get_current_user_from_header_or_query(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Deprecated for UK GDPR Article 32 compliance (Finding GDPR-006).
    Passing JWT access tokens via URL query parameters (?token=) is disabled to prevent
    credential leakage in browser history, proxy logs, and referer headers.
    Directly enforces standard Bearer token authentication via Authorization header.
    """
    return current_user


def get_current_unrestricted_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    UK GDPR Article 18: Enforce processing restriction.
    Halts automated processing activities (such as AI exam generation, document OCR)
    when user has invoked Right to Restriction of Processing.
    """
    if getattr(current_user, "is_restricted", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account processing is currently restricted under UK GDPR Article 18. Update privacy preferences in settings or contact support to lift restriction.",
        )
    return current_user

