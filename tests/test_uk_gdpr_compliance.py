import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch, MagicMock

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.user import User
from app.schemas.auth import UserRegister, UserUpdate
from app.services.auth_service import AuthService
from app.core.audit_logger import log_security_event
from app.api.deps import get_current_unrestricted_user, HTTPException

client = TestClient(app)


def test_legal_transparency_endpoints():
    """
    UK GDPR Art. 12/13/14 and PECR Reg 6: Verify legal transparency endpoints.
    """
    # 1. Privacy notice endpoint
    pn_resp = client.get("/api/v1/legal/privacy-notice")
    assert pn_resp.status_code == status.HTTP_200_OK
    pn_data = pn_resp.json()
    assert pn_data["title"] == "UK GDPR & Data Protection Act 2018 Privacy Notice"
    assert pn_data["jurisdiction"] == "United Kingdom"
    assert "privacy@papervisor.co.uk" in pn_data["contact_email"]
    assert "Data Controller" in pn_data["content_markdown"]

    # 2. Cookie & local storage policy endpoint
    cp_resp = client.get("/api/v1/legal/cookie-policy")
    assert cp_resp.status_code == status.HTTP_200_OK
    cp_data = cp_resp.json()
    assert cp_data["title"] == "PECR Cookie & Terminal Storage Policy"
    assert cp_data["cookies_used_by_backend"] is False
    assert "PECR" in cp_data["content_markdown"]


def test_terms_and_restriction_unit_flow():
    """
    UK GDPR Art. 16 (Rectification) & Art. 18 (Restriction): Verify terms lifecycle and restriction toggle via AuthService.
    """
    mock_db = MagicMock()
    service = AuthService(mock_db)

    now = datetime.now(timezone.utc)
    user_id = uuid4()
    mock_user = User(
        id=user_id,
        name="Study User",
        email="student@example.com",
        password_hash="hashed_pw",
        email_verified=False,
        terms_version="1.0",
        terms_accepted_at=now,
        is_restricted=False,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    service.user_repo.get_by_email = MagicMock(return_value=None)
    service.user_repo.create_user = MagicMock(return_value=mock_user)
    service.user_repo.create_refresh_token = MagicMock()

    # 1. Register with terms accepted
    reg_dto = UserRegister(
        name="Study User",
        email="student@example.com",
        password="ValidPassword123!",
        terms_accepted=True,
    )

    token_pair = service.register(reg_dto)
    assert token_pair.access_token is not None
    assert token_pair.user.terms_version == "1.0"
    assert token_pair.user.terms_accepted_at is not None
    assert token_pair.user.is_restricted is False

    # 2. Update user profile & toggle Article 18 restriction freeze
    def fake_update(user, name=None, is_restricted=None):
        if name is not None:
            user.name = name
        if is_restricted is not None:
            user.is_restricted = is_restricted
        return user

    service.user_repo.update_user_profile = MagicMock(side_effect=fake_update)

    update_dto = UserUpdate(
        name="Updated Name",
        is_restricted=True,
    )
    updated_user = service.update_profile(mock_user, update_dto)
    assert updated_user.name == "Updated Name"
    assert updated_user.is_restricted is True

    # 3. Export data includes restriction status
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    exported = service.export_user_data(mock_user)
    profile = exported["user_profile"]
    assert profile["name"] == "Updated Name"
    assert profile["is_restricted"] is True
    assert profile["terms_version"] == "1.0"


def test_article_18_restriction_dependency_blocks_restricted_user():
    """
    UK GDPR Art. 18: Verify processing restriction blocks restricted users from processing tasks.
    """
    restricted_user = MagicMock()
    restricted_user.is_restricted = True

    with pytest.raises(HTTPException) as exc_info:
        get_current_unrestricted_user(restricted_user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Article 18" in exc_info.value.detail

    unrestricted_user = MagicMock()
    unrestricted_user.is_restricted = False
    assert get_current_unrestricted_user(unrestricted_user) == unrestricted_user


def test_security_audit_logger_redaction():
    """
    UK GDPR Art. 32: Verify security audit logger sanitizes passwords, tokens, and masks emails.
    """
    with patch("app.core.audit_logger.audit_logger.info") as mock_info:
        log_security_event(
            event_type="TEST_SECURITY_EVENT",
            status="SUCCESS",
            user_id="test-user-id",
            details={
                "password": "CleartextPassword123!",
                "token": "secret-jwt-token",
                "email": "student@example.com",
                "action": "view_document",
            },
        )
        assert mock_info.called
        log_call_arg = mock_info.call_args[0][0]
        assert "[REDACTED]" in log_call_arg
        assert "CleartextPassword123!" not in log_call_arg
        assert "secret-jwt-token" not in log_call_arg
        assert "s***@example.com" in log_call_arg
        assert "TEST_SECURITY_EVENT" in log_call_arg
