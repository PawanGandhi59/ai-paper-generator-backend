from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import secrets
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_password_reset_token,
    generate_refresh_token,
    get_password_hash,
    hash_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    DeleteAccountRequest,
    DeleteAccountResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleLogin,
    RefreshTokenRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    UserUpdate,
    VerifyResetOTPRequest,
    VerifyResetOTPResponse,
)
from app.services.email_service import EmailService
from app.core.audit_logger import log_security_event


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
        now = utc_now()
        terms_accepted_at = now

        user = self.user_repo.create_user(
            name=data.name,
            email=data.email,
            password_hash=hashed_password,
            email_verified=False,
            terms_accepted_at=terms_accepted_at,
            is_restricted=False,
        )

        log_security_event(
            event_type="AUTH_REGISTER",
            status="SUCCESS",
            user_id=str(user.id),
            details={"email": data.email},
        )

        return self._create_token_pair(user)

    def login(self, data: UserLogin) -> TokenResponse:
        user = self.user_repo.get_by_email(data.email)
        if not user or not user.password_hash:
            log_security_event(
                event_type="AUTH_LOGIN",
                status="FAILURE",
                details={"reason": "User not found or no password", "email": data.email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not verify_password(data.password, user.password_hash):
            log_security_event(
                event_type="AUTH_LOGIN",
                status="FAILURE",
                user_id=str(user.id),
                details={"reason": "Invalid password", "email": data.email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not user.is_active:
            log_security_event(
                event_type="AUTH_LOGIN",
                status="BLOCKED",
                user_id=str(user.id),
                details={"reason": "Inactive user account"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        log_security_event(
            event_type="AUTH_LOGIN",
            status="SUCCESS",
            user_id=str(user.id),
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
                now = utc_now()
                user = self.user_repo.create_user(
                    name=name,
                    email=email,
                    password_hash=None,
                    email_verified=True,
                    terms_accepted_at=now,
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

    def forgot_password(self, data: ForgotPasswordRequest) -> ForgotPasswordResponse:
        normalized_email = data.email.strip().lower()
        success_message = "If that email address is registered, a password reset OTP has been sent."
        user = self.user_repo.get_by_email(normalized_email)
        if not user or not user.is_active:
            return ForgotPasswordResponse(message=success_message)

        # Resend cooldown check
        latest_otp = self.user_repo.get_latest_otp_by_user_id(user.id)
        if latest_otp and (utc_now() - latest_otp.created_at).total_seconds() < settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
            return ForgotPasswordResponse(message=success_message)

        # Invalidate previous OTPs
        self.user_repo.invalidate_user_otps(user.id)

        # Generate secure 6-digit numeric OTP
        plain_otp = f"{secrets.randbelow(1_000_000):06d}"
        otp_hash = get_password_hash(plain_otp)
        expires_at = utc_now() + timedelta(minutes=settings.PASSWORD_RESET_OTP_EXPIRE_MINUTES)

        # Save OTP record
        self.user_repo.create_password_reset_otp(
            user_id=user.id,
            otp_hash=otp_hash,
            expires_at=expires_at,
            max_attempts=settings.PASSWORD_RESET_MAX_ATTEMPTS,
        )
        self.db.commit()

        # Send OTP email
        email_service = EmailService()
        try:
            email_service.send_password_reset_otp(
                recipient_email=user.email,
                otp=plain_otp,
                expires_in_minutes=settings.PASSWORD_RESET_OTP_EXPIRE_MINUTES,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"Password reset email delivery failed for user {user.id}: {exc}")

        return ForgotPasswordResponse(message=success_message)

    def verify_reset_otp(self, data: VerifyResetOTPRequest) -> VerifyResetOTPResponse:
        normalized_email = data.email.strip().lower()
        user = self.user_repo.get_by_email(normalized_email)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP or request expired.",
            )

        otp = self.user_repo.get_latest_otp_by_user_id(user.id)
        if not otp or otp.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP or request expired.",
            )

        if otp.verified_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP has already been verified.",
            )

        if otp.expires_at <= utc_now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP has expired.",
            )

        if otp.attempts >= otp.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum verification attempts exceeded. Please request a new OTP.",
            )

        if not verify_password(data.otp, otp.otp_hash):
            otp.attempts += 1
            self.db.commit()
            if otp.attempts >= otp.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Maximum verification attempts exceeded. Please request a new OTP.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP.",
            )

        # Mark OTP as verified
        otp.verified_at = utc_now()
        self.db.commit()

        # Generate purpose-specific reset JWT
        reset_token = create_password_reset_token(
            data={"sub": str(user.id), "otp_id": str(otp.id)}
        )

        return VerifyResetOTPResponse(
            message="OTP verified successfully.",
            reset_token=reset_token,
        )

    def reset_password(self, data: ResetPasswordRequest) -> ResetPasswordResponse:
        try:
            payload = decode_password_reset_token(data.reset_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        user_id_str = payload.get("sub")
        otp_id_str = payload.get("otp_id")
        if not user_id_str or not otp_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        try:
            user_id = UUID(user_id_str)
            otp_id = UUID(otp_id_str)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        user = self.user_repo.get_by_id(user_id)
        otp = self.user_repo.get_otp_by_id(otp_id)
        if not user or not user.is_active or not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        if otp.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        if otp.verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP has not been verified.",
            )

        if otp.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset token has already been used.",
            )

        if otp.expires_at <= utc_now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset token has expired.",
            )

        # Hash new password using existing bcrypt implementation
        new_password_hash = get_password_hash(data.new_password)

        # Execute transactional update & refresh token revocation
        self.user_repo.update_user_password(user, new_password_hash)
        otp.used_at = utc_now()
        self.user_repo.revoke_all_user_refresh_tokens(user.id)
        self.db.commit()

        return ResetPasswordResponse(message="Password reset successfully.")

    def delete_account(
        self,
        current_user: User,
        data: Optional[DeleteAccountRequest] = None,
    ) -> DeleteAccountResponse:
        """
        Permanently delete a user account and all descendant resources.
        - Verifies user is active.
        - Verifies password if provided (for password-based accounts).
        - Deletes all user workspaces, cascading down through subjects, books, documents,
          reference papers, and generated papers, including physical files on disk/S3.
        - Deletes any generated visual files.
        - Deletes user entity from DB, cascading all OAuth accounts, refresh tokens, OTPs.
        """
        if not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        if data and data.password:
            if current_user.password_hash and not verify_password(data.password, current_user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Incorrect password.",
                )

        import os
        from sqlalchemy import select
        from app.models.generated_visual import GeneratedVisual
        from app.models.workspace import Workspace
        from app.services.storage import storage_service
        from app.services.workspace_service import WorkspaceService

        # 1. Clean up user workspaces and their associated descendant files (docs, ref papers, generated papers)
        workspace_service = WorkspaceService(self.db)
        user_workspaces = self.db.execute(
            select(Workspace).where(Workspace.owner_id == current_user.id)
        ).scalars().all()

        import logging
        logger = logging.getLogger(__name__)

        for ws in user_workspaces:
            try:
                workspace_service.delete_workspace(ws.id, current_user.id)
            except Exception as exc:
                logger.warning(f"Error cleaning up workspace {ws.id} for user {current_user.id}: {exc}")

        # 2. Clean up any remaining visual files for this user
        try:
            visuals = self.db.execute(
                select(GeneratedVisual).where(GeneratedVisual.user_id == current_user.id)
            ).scalars().all()
            for visual in visuals:
                if visual.file_path:
                    if os.path.exists(visual.file_path):
                        try:
                            os.remove(visual.file_path)
                        except OSError:
                            pass
                    storage_service.delete_prefix(visual.file_path)
        except Exception:
            pass

        # 3. Delete user record from database (cascading deletes OAuth accounts, refresh tokens, OTPs, etc.)
        user = self.user_repo.get_by_id(current_user.id)
        if user:
            self.user_repo.delete_user(user)

        log_security_event(
            event_type="AUTH_ACCOUNT_DELETED",
            status="SUCCESS",
            user_id=str(current_user.id),
            details={"email": current_user.email},
        )

        return DeleteAccountResponse(message="Account successfully deleted.")

    def update_profile(self, user: User, data: UserUpdate) -> UserResponse:
        """
        Right to Rectification (UK GDPR Art. 16) & Account Freeze (Art. 18): Update user profile details.
        """
        updated_user = self.user_repo.update_user_profile(
            user=user,
            name=data.name,
            is_restricted=data.is_restricted,
        )

        log_security_event(
            event_type="AUTH_PROFILE_UPDATED",
            status="SUCCESS",
            user_id=str(user.id),
            details={
                "name_updated": data.name is not None,
                "is_restricted": updated_user.is_restricted,
            },
        )

        return UserResponse.model_validate(updated_user)

    def export_user_data(self, user: User) -> Dict[str, Any]:
        """
        Right to Data Portability (UK GDPR Art. 20): Export structured, machine-readable user data package.
        """
        from app.models.workspace import Workspace
        from app.models.generated_paper import GeneratedPaper
        from sqlalchemy import select

        workspaces_data = []
        user_workspaces = self.db.execute(
            select(Workspace).where(Workspace.owner_id == user.id)
        ).scalars().all()

        for ws in user_workspaces:
            subjects_data = []
            for sub in (ws.subjects or []):
                books_data = []
                for b in (sub.books or []):
                    chapters_data = [
                        {
                            "id": str(c.id),
                            "chapter_number": c.chapter_number,
                            "name": c.name,
                            "start_page": c.start_page,
                            "end_page": c.end_page,
                        }
                        for c in (b.chapters or []) if c.deleted_at is None
                    ]
                    books_data.append({
                        "id": str(b.id),
                        "name": b.name,
                        "chapters": chapters_data,
                    })
                subjects_data.append({
                    "id": str(sub.id),
                    "name": sub.name,
                    "books": books_data,
                })
            workspaces_data.append({
                "id": str(ws.id),
                "name": ws.name,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "subjects": subjects_data,
            })

        papers_data = []
        user_papers = self.db.execute(
            select(GeneratedPaper).where(GeneratedPaper.user_id == user.id, GeneratedPaper.deleted_at.is_(None))
        ).scalars().all()

        for p in user_papers:
            papers_data.append({
                "id": str(p.id),
                "title": p.title,
                "total_marks": p.total_marks,
                "difficulty": p.difficulty,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "question_count": len(p.questions or []),
            })

        log_security_event(
            event_type="AUTH_DATA_EXPORTED",
            status="SUCCESS",
            user_id=str(user.id),
            details={"workspaces_count": len(workspaces_data), "papers_count": len(papers_data)},
        )

        return {
            "export_version": "1.0",
            "exported_at": utc_now().isoformat(),
            "user_profile": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "terms_accepted_at": user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
                "is_restricted": user.is_restricted,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "workspaces": workspaces_data,
            "generated_papers": papers_data,
        }

    def accept_terms(self, user: User) -> UserResponse:
        now = utc_now()
        updated_user = self.user_repo.update_terms_acceptance(
            user=user,
            terms_accepted_at=now,
        )
        log_security_event(
            event_type="AUTH_TERMS_UPDATE",
            status="SUCCESS",
            user_id=str(user.id),
            details={
                "terms_accepted_at": now.isoformat(),
            },
        )
        return UserResponse.model_validate(updated_user)
