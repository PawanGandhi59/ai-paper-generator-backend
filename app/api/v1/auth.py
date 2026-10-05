from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limiter import RateLimiter
from app.models.user import User
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
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(request: Request, data: UserRegister, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Register a new user with email and password.
    Enforces brute-force rate limiting and records consent metadata.
    """
    client_ip = request.client.host if request.client else "unknown"
    RateLimiter.check_auth_rate_limit(f"register:{client_ip}", max_requests=10, window_seconds=60)
    auth_service = AuthService(db)
    return auth_service.register(data)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate user with email and password.
    Supports both JSON body (Flutter/API) and Form Data (Swagger UI Authorize modal).
    Enforces brute-force rate limiting.
    """
    client_ip = request.client.host if request.client else "unknown"
    RateLimiter.check_auth_rate_limit(f"login:{client_ip}")
    auth_service = AuthService(db)
    content_type = request.headers.get("content-type", "")

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email and password required.",
            )
        login_data = UserLogin(email=str(username), password=str(password))
    else:
        try:
            body = await request.json()
            login_data = UserLogin.model_validate(body)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request body. Email and password required.",
            )

    return auth_service.login(login_data)


@router.post("/google", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def google_auth(data: GoogleLogin, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Authenticate user using Google OAuth ID token.
    """
    auth_service = AuthService(db)
    return auth_service.authenticate_google(data.id_token)


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Rotate refresh token and issue a new access token + refresh token pair.
    """
    auth_service = AuthService(db)
    return auth_service.refresh_tokens(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(data: RefreshTokenRequest, db: Session = Depends(get_db)) -> dict:
    """
    Revoke a refresh token on logout.
    """
    auth_service = AuthService(db)
    return auth_service.logout(data.refresh_token)


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """
    Get profile of currently authenticated user.
    """
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Update profile of currently authenticated user (UK GDPR Art. 16 Right to Rectification).
    """
    auth_service = AuthService(db)
    return auth_service.update_profile(current_user, data)


@router.get("/export-data", status_code=status.HTTP_200_OK)
def export_my_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Export all personal data and user-generated resources in JSON format
    (UK GDPR Art. 20 Right to Data Portability).
    """
    auth_service = AuthService(db)
    return auth_service.export_user_data(current_user)


@router.post("/forgot-password", response_model=ForgotPasswordResponse, status_code=status.HTTP_200_OK)
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    """
    Request a password reset OTP. Always returns a generic 200 response to prevent account enumeration (UK GDPR-008).
    Enforces rate limiting per IP.
    """
    client_ip = request.client.host if request.client else "unknown"
    RateLimiter.check_auth_rate_limit(f"forgot_password:{client_ip}", max_requests=5, window_seconds=60)
    auth_service = AuthService(db)
    return auth_service.forgot_password(data)


@router.post("/verify-reset-otp", response_model=VerifyResetOTPResponse, status_code=status.HTTP_200_OK)
def verify_reset_otp(data: VerifyResetOTPRequest, db: Session = Depends(get_db)) -> VerifyResetOTPResponse:
    """
    Verify 6-digit OTP and receive a short-lived purpose-specific password reset authorization token.
    """
    auth_service = AuthService(db)
    return auth_service.verify_reset_otp(data)


@router.post("/reset-password", response_model=ResetPasswordResponse, status_code=status.HTTP_200_OK)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)) -> ResetPasswordResponse:
    """
    Reset user password using a valid password reset token and update login credentials.
    """
    auth_service = AuthService(db)
    return auth_service.reset_password(data)


@router.delete("/delete-account", response_model=DeleteAccountResponse, status_code=status.HTTP_200_OK)
def delete_account(
    data: Optional[DeleteAccountRequest] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeleteAccountResponse:
    """
    Permanently delete the authenticated user's account and all associated resources.
    Supports optional password confirmation for password-based accounts.
    """
    auth_service = AuthService(db)
    return auth_service.delete_account(current_user, data)
