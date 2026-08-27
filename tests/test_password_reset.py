from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import patch

from fastapi import status
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.password_reset_otp import PasswordResetOTP
from app.models.user import User
from app.services.email_service import EmailService

client = TestClient(app)


def test_forgot_password_account_validation():
    """
    TEST: Verify forgot-password returns 200 for registered email and 404 for non-existent email.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"user_{uid}@example.com"

    # 1. Existing user registration
    reg_res = client.post("/api/v1/auth/register", json={"name": "Test User", "email": email, "password": "Password123!"})
    assert reg_res.status_code == status.HTTP_201_CREATED

    # 2. Forgot password for existing user -> HTTP 200 OK
    with patch.object(EmailService, "send_password_reset_otp", return_value=True) as mock_email:
        res1 = client.post("/api/v1/auth/forgot-password", json={"email": email})

    assert res1.status_code == status.HTTP_200_OK
    data1 = res1.json()
    assert data1["message"] == "Password reset OTP has been sent to your email address."
    assert mock_email.called

    # 3. Forgot password for non-existent user -> HTTP 404 NOT FOUND
    non_existent_email = f"unknown_{uid}@example.com"
    with patch.object(EmailService, "send_password_reset_otp", return_value=True) as mock_email_unknown:
        res2 = client.post("/api/v1/auth/forgot-password", json={"email": non_existent_email})

    assert res2.status_code == status.HTTP_404_NOT_FOUND
    assert res2.json()["detail"] == "No account found with this email address."
    assert not mock_email_unknown.called


def test_complete_forgot_password_otp_verify_and_reset_flow():
    """
    TEST: Full end-to-end Password Reset flow:
    forgot-password -> email OTP -> verify-reset-otp -> reset-password -> login with new password.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"reset_{uid}@example.com"
    old_password = "OldPassword123!"
    new_password = "NewPassword123!"

    # 1. Register user
    reg_res = client.post("/api/v1/auth/register", json={"name": "Reset User", "email": email, "password": old_password})
    assert reg_res.status_code == status.HTTP_201_CREATED

    # 2. Request forgot-password and capture generated OTP from mocked EmailService
    captured_otp = None

    def fake_send_email(*args, **kwargs):
        nonlocal captured_otp
        captured_otp = kwargs.get("otp") or (args[1] if len(args) > 1 else None)
        return True

    with patch.object(EmailService, "send_password_reset_otp", side_effect=fake_send_email):
        forgot_res = client.post("/api/v1/auth/forgot-password", json={"email": email})

    assert forgot_res.status_code == status.HTTP_200_OK
    assert captured_otp is not None
    assert len(captured_otp) == 6
    assert captured_otp.isdigit()

    # 3. Verify OTP with correct 6-digit code
    verify_res = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": captured_otp})
    assert verify_res.status_code == status.HTTP_200_OK
    verify_data = verify_res.json()
    assert "reset_token" in verify_data
    reset_token = verify_data["reset_token"]

    # 4. Attempt login with old password (should still work until reset is completed)
    login_old_before = client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert login_old_before.status_code == status.HTTP_200_OK
    old_refresh_token = login_old_before.json()["refresh_token"]

    # 5. Reset password using valid reset_token
    reset_res = client.post("/api/v1/auth/reset-password", json={"reset_token": reset_token, "new_password": new_password})
    assert reset_res.status_code == status.HTTP_200_OK
    assert reset_res.json()["message"] == "Password reset successfully."

    # 6. Old password login must fail
    login_old_after = client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert login_old_after.status_code == status.HTTP_401_UNAUTHORIZED

    # 7. Old refresh token must be revoked
    refresh_res = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert refresh_res.status_code == status.HTTP_401_UNAUTHORIZED

    # 8. New password login must succeed
    login_new = client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert login_new.status_code == status.HTTP_200_OK
    assert "access_token" in login_new.json()


def test_otp_attempt_limit_and_invalidation():
    """
    TEST: Verify that entering incorrect OTPs increments attempt counter and invalidates OTP upon 5th failure.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"attempts_{uid}@example.com"
    password = "Password123!"

    client.post("/api/v1/auth/register", json={"name": "Attempts User", "email": email, "password": password})

    captured_otp = None

    def fake_send_email(*args, **kwargs):
        nonlocal captured_otp
        captured_otp = kwargs.get("otp") or (args[1] if len(args) > 1 else None)
        return True

    with patch.object(EmailService, "send_password_reset_otp", side_effect=fake_send_email):
        client.post("/api/v1/auth/forgot-password", json={"email": email})

    wrong_otp = "999999" if captured_otp != "999999" else "888888"

    # Attempt 1-4 with wrong OTP -> 400 Bad Request
    for attempt_num in range(1, 5):
        res = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": wrong_otp})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    # Attempt 5 -> Maximum attempts exceeded error
    res5 = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": wrong_otp})
    assert res5.status_code == status.HTTP_400_BAD_REQUEST
    assert "Maximum verification attempts exceeded" in res5.json()["detail"]

    # Even correct OTP must now be rejected because max_attempts was hit
    res_correct_after_lockout = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": captured_otp})
    assert res_correct_after_lockout.status_code == status.HTTP_400_BAD_REQUEST


def test_reset_token_single_use_guarantee():
    """
    TEST: Verify that a reset_token and OTP cannot be reused after password reset.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"singleuse_{uid}@example.com"

    client.post("/api/v1/auth/register", json={"name": "SingleUse User", "email": email, "password": "Password123!"})

    captured_otp = None

    def fake_send_email(*args, **kwargs):
        nonlocal captured_otp
        captured_otp = kwargs.get("otp") or (args[1] if len(args) > 1 else None)
        return True

    with patch.object(EmailService, "send_password_reset_otp", side_effect=fake_send_email):
        client.post("/api/v1/auth/forgot-password", json={"email": email})

    verify_res = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": captured_otp})
    reset_token = verify_res.json()["reset_token"]

    # First reset succeeds
    reset_res1 = client.post("/api/v1/auth/reset-password", json={"reset_token": reset_token, "new_password": "NewPassword123!"})
    assert reset_res1.status_code == status.HTTP_200_OK

    # Second reset with same reset_token must fail
    reset_res2 = client.post("/api/v1/auth/reset-password", json={"reset_token": reset_token, "new_password": "AnotherPassword123!"})
    assert reset_res2.status_code == status.HTTP_400_BAD_REQUEST
    assert "already been used" in reset_res2.json()["detail"]


def test_normal_access_token_cannot_be_used_as_reset_token():
    """
    TEST: Verify that a normal user access token cannot be used to reset a password.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"typecheck_{uid}@example.com"

    reg_res = client.post("/api/v1/auth/register", json={"name": "TypeCheck User", "email": email, "password": "Password123!"})
    access_token = reg_res.json()["access_token"]

    # Try using access token as reset_token
    res = client.post("/api/v1/auth/reset-password", json={"reset_token": access_token, "new_password": "NewPassword123!"})
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid or expired password reset token" in res.json()["detail"]


def test_reset_token_cannot_access_protected_apis():
    """
    TEST: Verify that a reset_token cannot be used as a Bearer access token to call GET /api/v1/auth/me.
    """
    uid = uuid.uuid4().hex[:8]
    email = f"noaccess_{uid}@example.com"

    client.post("/api/v1/auth/register", json={"name": "NoAccess User", "email": email, "password": "Password123!"})

    captured_otp = None

    def fake_send_email(*args, **kwargs):
        nonlocal captured_otp
        captured_otp = kwargs.get("otp") or (args[1] if len(args) > 1 else None)
        return True

    with patch.object(EmailService, "send_password_reset_otp", side_effect=fake_send_email):
        client.post("/api/v1/auth/forgot-password", json={"email": email})

    verify_res = client.post("/api/v1/auth/verify-reset-otp", json={"email": email, "otp": captured_otp})
    reset_token = verify_res.json()["reset_token"]

    # Use reset_token as Authorization Bearer token
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {reset_token}"})
    assert me_res.status_code == status.HTTP_401_UNAUTHORIZED
