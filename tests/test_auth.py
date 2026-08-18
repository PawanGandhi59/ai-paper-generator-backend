from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.services.auth_service import AuthService

client = TestClient(app)


def test_user_registration_and_login_flow():
    uid = uuid4().hex[:8]
    email = f"testuser_{uid}@example.com"
    password = "secretpassword123"
    name = "Test Student"

    # 1. Register user
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert "refresh_token" in reg_data
    assert reg_data["user"]["email"] == email
    assert reg_data["user"]["name"] == name

    # 2. Password length > 72 rejected
    long_pwd_resp = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": f"long_{uid}@example.com", "password": "a" * 73},
    )
    assert long_pwd_resp.status_code == 422

    # 3. Duplicate registration rejected
    dup_resp = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert dup_resp.status_code == 400

    # 4. Login with correct credentials
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]

    # 5. Login with wrong password rejected
    wrong_pwd_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert wrong_pwd_resp.status_code == 401

    # 6. Access /me with valid access token
    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    # 7. Access /me with invalid access token rejected
    me_invalid_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalidtoken123"},
    )
    assert me_invalid_resp.status_code == 401

    # 8. Refresh token rotation
    ref_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert ref_resp.status_code == 200
    new_access_token = ref_resp.json()["access_token"]
    new_refresh_token = ref_resp.json()["refresh_token"]
    assert new_refresh_token != refresh_token

    # 9. Reusing old refresh token is rejected
    reuse_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert reuse_resp.status_code == 401

    # 10. Logout with active refresh token
    logout_resp = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_refresh_token},
    )
    assert logout_resp.status_code == 200


def test_jwt_token_type_validation():
    uid = uuid4().hex[:8]
    email = f"type_{uid}@example.com"
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"name": "Type User", "email": email, "password": "password123"},
    ).json()
    user_id = reg_resp["user"]["id"]

    # 1. Token without type claim rejected
    no_type_token = jwt.encode(
        {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    no_type_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {no_type_token}"},
    )
    assert no_type_resp.status_code == 401

    # 2. Token with type != access rejected (e.g. type="refresh")
    wrong_type_token = jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    wrong_type_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {wrong_type_token}"},
    )
    assert wrong_type_resp.status_code == 401


def test_google_oauth_security_validation():
    target_client_id = "test-google-web-client-id.apps.googleusercontent.com"
    settings.GOOGLE_WEB_CLIENT_ID = target_client_id

    uid = uuid4().hex[:8]
    email = f"google_{uid}@example.com"

    # 1. Valid Google token with accepted audience & verified email
    mock_google_payload = {
        "sub": f"google-sub-{uid}",
        "email": email,
        "name": "Google User",
        "aud": target_client_id,
        "iss": "https://accounts.google.com",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "email_verified": True,
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_google_payload

    with patch("httpx.Client.get", return_value=mock_resp):
        g_resp = client.post("/api/v1/auth/google", json={"id_token": "valid_token_string"})
        assert g_resp.status_code == 200
        g_data = g_resp.json()
        assert g_data["user"]["email"] == email

    # 2. Wrong audience rejected
    mock_wrong_aud = mock_google_payload.copy()
    mock_wrong_aud["aud"] = "malicious-app-client-id.apps.googleusercontent.com"
    mock_resp.json.return_value = mock_wrong_aud

    with patch("httpx.Client.get", return_value=mock_resp):
        g_bad_aud = client.post("/api/v1/auth/google", json={"id_token": "bad_aud_token"})
        assert g_bad_aud.status_code == 401
        assert "audience" in g_bad_aud.json()["detail"].lower()

    # 3. Invalid issuer rejected
    mock_bad_iss = mock_google_payload.copy()
    mock_bad_iss["iss"] = "https://fake-google-issuer.com"
    mock_resp.json.return_value = mock_bad_iss

    with patch("httpx.Client.get", return_value=mock_resp):
        g_bad_iss = client.post("/api/v1/auth/google", json={"id_token": "bad_iss_token"})
        assert g_bad_iss.status_code == 401
        assert "issuer" in g_bad_iss.json()["detail"].lower()

    # 4. Unverified email rejected
    mock_unverified = mock_google_payload.copy()
    mock_unverified["email_verified"] = False
    mock_resp.json.return_value = mock_unverified

    with patch("httpx.Client.get", return_value=mock_resp):
        g_unverified = client.post("/api/v1/auth/google", json={"id_token": "unverified_email_token"})
        assert g_unverified.status_code == 400
        assert "verified" in g_unverified.json()["detail"].lower()

    # 5. Expired token rejected
    mock_expired = mock_google_payload.copy()
    mock_expired["exp"] = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
    mock_resp.json.return_value = mock_expired

    with patch("httpx.Client.get", return_value=mock_resp):
        g_expired = client.post("/api/v1/auth/google", json={"id_token": "expired_token"})
        assert g_expired.status_code == 401
        assert "expired" in g_expired.json()["detail"].lower()


def test_concurrent_refresh_token_rotation():
    uid = uuid4().hex[:8]
    email = f"concurrent_{uid}@example.com"
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"name": "Concurrent User", "email": email, "password": "password123"},
    ).json()
    refresh_token = reg_resp["refresh_token"]

    def do_refresh():
        db = SessionLocal()
        try:
            service = AuthService(db)
            res = service.refresh_tokens(refresh_token)
            return ("success", res)
        except HTTPException as exc:
            return ("http_error", exc.status_code, exc.detail)
        except Exception as exc:
            return ("error", str(exc))
        finally:
            db.close()

    # Run two concurrent refresh requests in parallel threads across independent DB connections
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_refresh)
        f2 = executor.submit(do_refresh)
        res1 = f1.result()
        res2 = f2.result()

    results = [res1[0], res2[0]]
    # Exactly one request succeeds, and the other is rejected with HTTP 401 due to row locking and token reuse policy
    assert "success" in results
    assert "http_error" in results

    http_err = res1 if res1[0] == "http_error" else res2
    assert http_err[1] == 401
