from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.password_reset_otp import PasswordResetOTP
from app.models.user import OAuthAccount, RefreshToken, User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def create_user(self, name: str, email: str, password_hash: Optional[str] = None, email_verified: bool = False) -> User:
        user = User(
            name=name.strip(),
            email=email.strip().lower(),
            password_hash=password_hash,
            email_verified=email_verified,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_oauth_account(self, provider: str, provider_user_id: str) -> Optional[OAuthAccount]:
        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_oauth_account(self, user_id: UUID, provider: str, provider_user_id: str) -> OAuthAccount:
        oauth_acc = OAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
        )
        self.db.add(oauth_acc)
        self.db.commit()
        self.db.refresh(oauth_acc)
        return oauth_acc

    def create_refresh_token(self, user_id: UUID, token_hash: str, expires_at: datetime) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(token)
        self.db.flush()
        return token

    def get_refresh_token_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_refresh_token_by_hash_for_update(self, token_hash: str) -> Optional[RefreshToken]:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def revoke_refresh_token(self, token: RefreshToken, replaced_by_id: Optional[UUID] = None) -> None:
        token.revoked_at = datetime.now(timezone.utc)
        if replaced_by_id:
            token.replaced_by_token_id = replaced_by_id
        self.db.commit()

    def revoke_all_user_refresh_tokens(self, user_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        tokens = self.db.execute(stmt).scalars().all()
        for token in tokens:
            token.revoked_at = now
        self.db.commit()

    def create_password_reset_otp(self, user_id: UUID, otp_hash: str, expires_at: datetime, max_attempts: int = 5) -> PasswordResetOTP:
        otp = PasswordResetOTP(
            user_id=user_id,
            otp_hash=otp_hash,
            expires_at=expires_at,
            max_attempts=max_attempts,
        )
        self.db.add(otp)
        self.db.flush()
        return otp

    def get_latest_otp_by_user_id(self, user_id: UUID) -> Optional[PasswordResetOTP]:
        stmt = (
            select(PasswordResetOTP)
            .where(PasswordResetOTP.user_id == user_id)
            .order_by(PasswordResetOTP.created_at.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def get_otp_by_id(self, otp_id: UUID) -> Optional[PasswordResetOTP]:
        return self.db.get(PasswordResetOTP, otp_id)

    def invalidate_user_otps(self, user_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        stmt = select(PasswordResetOTP).where(
            PasswordResetOTP.user_id == user_id,
            PasswordResetOTP.used_at.is_(None),
            PasswordResetOTP.expires_at > now,
        )
        otps = self.db.execute(stmt).scalars().all()
        for otp in otps:
            otp.expires_at = now
        self.db.flush()

    def update_user_password(self, user: User, new_password_hash: str) -> None:
        user.password_hash = new_password_hash
        user.updated_at = datetime.now(timezone.utc)
        self.db.flush()
