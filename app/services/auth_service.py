from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    get_password_hash,
    hash_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import UserLogin, UserRegister, UserResponse, TokenResponse


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)

    def _create_token_pair(self, user: User) -> TokenResponse:
        access_token = create_access_token(data={"sub": str(user.id)})
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        raw_refresh_token = generate_refresh_token()
        token_hash = hash_refresh_token(raw_refresh_token)
        expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        self.user_repo.create_refresh_token(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )

    def register(self, data: UserRegister) -> TokenResponse:
        existing_user = self.user_repo.get_by_email(data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address is already registered.",
            )

        hashed_password = get_password_hash(data.password)
        user = self.user_repo.create_user(
            name=data.name,
            email=data.email,
            password_hash=hashed_password,
            email_verified=False,
        )

        return self._create_token_pair(user)

    def login(self, data: UserLogin) -> TokenResponse:
        user = self.user_repo.get_by_email(data.email)
        if not user or not user.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        return self._create_token_pair(user)

    def authenticate_google(self, id_token: str) -> TokenResponse:
        # Verify token with Google tokeninfo endpoint
        token_info_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(token_info_url)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not reach Google authentication server: {str(exc)}",
            ) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google identity token.",
            )

        data = response.json()
        sub = data.get("sub")
        email = data.get("email")
        aud = data.get("aud")
        iss = data.get("iss")
        exp = data.get("exp")
        email_verified_claim = data.get("email_verified")
        name = data.get("name", email.split("@")[0] if email else "Google User")

        if not sub or not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google token missing essential user identity claims.",
            )

        # 1. Issuer check
        valid_issuers = {"accounts.google.com", "https://accounts.google.com"}
        if iss not in valid_issuers:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google identity token issuer.",
            )

        # 2. Expiration check
        if exp is not None:
            try:
                exp_timestamp = float(exp)
                if exp_timestamp < utc_now().timestamp():
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Google identity token has expired.",
                    )
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Google identity token expiration format.",
                )

        # 3. Audience check against configured client IDs
        accepted_client_ids = {
            client_id.strip()
            for client_id in [
                settings.GOOGLE_WEB_CLIENT_ID,
                settings.GOOGLE_ANDROID_CLIENT_ID,
                settings.GOOGLE_IOS_CLIENT_ID,
            ]
            if client_id and client_id.strip()
        }

        if not accepted_client_ids or aud not in accepted_client_ids:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google identity token audience does not match configured application client IDs.",
            )

        # 4. Email verification check
        is_verified = (
            email_verified_claim is True
            or (isinstance(email_verified_claim, str) and email_verified_claim.lower() == "true")
        )
        if not is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account email is not verified.",
            )

        # Check existing OAuth account
        oauth_acc = self.user_repo.get_oauth_account(provider="google", provider_user_id=sub)
        if oauth_acc:
            user = oauth_acc.user
        else:
            # Check existing user by email
            user = self.user_repo.get_by_email(email)
            if not user:
                user = self.user_repo.create_user(
                    name=name,
                    email=email,
                    password_hash=None,
                    email_verified=True,
                )
            self.user_repo.create_oauth_account(
                user_id=user.id,
                provider="google",
                provider_user_id=sub,
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        return self._create_token_pair(user)

    def refresh_tokens(self, refresh_token_str: str) -> TokenResponse:
        token_hash = hash_refresh_token(refresh_token_str)
        # Use database row-level lock FOR UPDATE to prevent race conditions in concurrent refreshes
        token_obj = self.user_repo.get_refresh_token_by_hash_for_update(token_hash)

        if not token_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )

        if token_obj.revoked_at is not None:
            # Revocation reuse detected! Security measure: revoke all user refresh tokens
            self.user_repo.revoke_all_user_refresh_tokens(token_obj.user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Revoked refresh token reuse detected. All sessions revoked for security.",
            )

        if token_obj.expires_at < utc_now():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired.",
            )

        user = self.user_repo.get_by_id(token_obj.user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive or missing.",
            )

        # Generate new token pair inside same atomic transaction
        access_token = create_access_token(data={"sub": str(user.id)})
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        raw_new_refresh = generate_refresh_token()
        new_token_hash = hash_refresh_token(raw_new_refresh)
        expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        new_token_obj = self.user_repo.create_refresh_token(
            user_id=user.id,
            token_hash=new_token_hash,
            expires_at=expires_at,
        )

        # Mark current token as revoked and replaced within the single locked transaction
        token_obj.revoked_at = utc_now()
        token_obj.replaced_by_token_id = new_token_obj.id

        self.db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_new_refresh,
            token_type="bearer",
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )

    def logout(self, refresh_token_str: str) -> Dict[str, str]:
        token_hash = hash_refresh_token(refresh_token_str)
        token_obj = self.user_repo.get_refresh_token_by_hash(token_hash)
        if token_obj and token_obj.revoked_at is None:
            self.user_repo.revoke_refresh_token(token_obj)
        return {"status": "ok", "message": "Successfully logged out."}
