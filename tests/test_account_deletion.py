import os
import shutil
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.document import Document
from app.models.generated_paper import GeneratedPaper
from app.models.generated_visual import GeneratedVisual
from app.models.reference_paper import ReferencePaper
from app.models.subject import Subject
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.auth import DeleteAccountRequest, DeleteAccountResponse
from app.services.auth_service import AuthService
from app.services.storage import storage_service


def test_delete_account_success_with_password():
    """Verify user can delete account with correct password confirmation."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    password = "CorrectPassword123!"
    user = User(
        id=uuid4(),
        name="Test Delete User",
        email="delete_me@example.com",
        password_hash=get_password_hash(password),
        is_active=True,
    )

    auth_service.user_repo.get_by_id = MagicMock(return_value=user)
    auth_service.user_repo.delete_user = MagicMock()

    # Mock execute for workspaces & visuals
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    req = DeleteAccountRequest(password=password)
    response = auth_service.delete_account(current_user=user, data=req)

    assert isinstance(response, DeleteAccountResponse)
    assert response.message == "Account successfully deleted."
    auth_service.user_repo.delete_user.assert_called_once_with(user)


def test_delete_account_success_without_password():
    """Verify user can delete account without password payload."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    user = User(
        id=uuid4(),
        name="Direct Delete User",
        email="direct_delete@example.com",
        password_hash=get_password_hash("SomePassword123!"),
        is_active=True,
    )

    auth_service.user_repo.get_by_id = MagicMock(return_value=user)
    auth_service.user_repo.delete_user = MagicMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    response = auth_service.delete_account(current_user=user, data=None)

    assert response.message == "Account successfully deleted."
    auth_service.user_repo.delete_user.assert_called_once_with(user)


def test_delete_account_success_oauth_user():
    """Verify OAuth user with password_hash=None can delete account without password."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    oauth_user = User(
        id=uuid4(),
        name="Google User",
        email="google_user@gmail.com",
        password_hash=None,
        is_active=True,
    )

    auth_service.user_repo.get_by_id = MagicMock(return_value=oauth_user)
    auth_service.user_repo.delete_user = MagicMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    response = auth_service.delete_account(current_user=oauth_user, data=None)

    assert response.message == "Account successfully deleted."
    auth_service.user_repo.delete_user.assert_called_once_with(oauth_user)


def test_delete_account_incorrect_password_rejected():
    """Verify account deletion fails with 400 when an incorrect password is provided."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    user = User(
        id=uuid4(),
        name="Protected User",
        email="protected@example.com",
        password_hash=get_password_hash("RealPassword123!"),
        is_active=True,
    )

    auth_service.user_repo.delete_user = MagicMock()

    req = DeleteAccountRequest(password="WrongPassword999!")
    with pytest.raises(HTTPException) as exc_info:
        auth_service.delete_account(current_user=user, data=req)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Incorrect password" in exc_info.value.detail
    auth_service.user_repo.delete_user.assert_not_called()


def test_delete_account_inactive_user_rejected():
    """Verify inactive account deletion is forbidden with 403."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    inactive_user = User(
        id=uuid4(),
        name="Inactive User",
        email="inactive@example.com",
        password_hash=get_password_hash("Pass123!"),
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_service.delete_account(current_user=inactive_user, data=None)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "inactive" in exc_info.value.detail.lower()


def test_delete_account_cascades_workspaces_and_disk_files(tmp_path):
    """Verify account deletion cascades workspace deletion and removes physical files from disk."""
    mock_db = MagicMock()
    auth_service = AuthService(mock_db)

    user_id = uuid4()
    user = User(
        id=user_id,
        name="File Owner",
        email="owner@example.com",
        password_hash=get_password_hash("Pass123!"),
        is_active=True,
    )

    workspace_id = uuid4()
    ws = Workspace(id=workspace_id, owner_id=user_id, name="User Workspace")

    # Set up physical files
    storage_root = str(tmp_path)
    doc_id = uuid4()
    doc_dir = tmp_path / "documents" / str(doc_id)
    doc_dir.mkdir(parents=True)
    (doc_dir / "sample.pdf").write_bytes(b"%PDF-doc")

    ref_id = uuid4()
    ref_dir = tmp_path / "reference_papers" / str(ref_id)
    ref_dir.mkdir(parents=True)
    (ref_dir / "ref.pdf").write_bytes(b"%PDF-ref")

    gen_id = uuid4()
    gen_dir = tmp_path / "generated_papers" / str(gen_id)
    gen_dir.mkdir(parents=True)
    (gen_dir / "gen.pdf").write_bytes(b"%PDF-gen")

    visual_path = tmp_path / "visual.png"
    visual_path.write_bytes(b"PNG-content")

    # Mocks for database queries
    doc_mock = MagicMock()
    doc_mock.id = doc_id

    ref_mock = MagicMock()
    ref_mock.id = ref_id

    gen_mock = MagicMock()
    gen_mock.id = gen_id

    visual_mock = MagicMock()
    visual_mock.file_path = str(visual_path)

    subject_mock = MagicMock()
    subject_mock.id = uuid4()
    book_mock = MagicMock()
    book_mock.id = uuid4()
    subject_mock.books = [book_mock]
    ws.subjects = [subject_mock]

    def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        res = MagicMock()
        if "from workspaces" in stmt_str:
            res.scalars.return_value.all.return_value = [ws]
        elif "from documents" in stmt_str:
            res.scalars.return_value.all.return_value = [doc_mock]
        elif "from reference_papers" in stmt_str:
            res.scalars.return_value.all.return_value = [ref_mock]
        elif "from generated_papers" in stmt_str:
            res.scalars.return_value.all.return_value = [gen_mock]
        elif "from generated_visuals" in stmt_str:
            res.scalars.return_value.all.return_value = [visual_mock]
        else:
            res.scalars.return_value.all.return_value = []
        return res

    mock_db.execute.side_effect = mock_execute
    mock_db.get.side_effect = lambda model, id_: ws if model == Workspace else None
    auth_service.user_repo.get_by_id = MagicMock(return_value=user)
    auth_service.user_repo.delete_user = MagicMock()

    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", storage_root), \
         patch.object(storage_service, "delete_prefix") as mock_storage_del:

        resp = auth_service.delete_account(current_user=user, data=None)

        assert resp.message == "Account successfully deleted."
        auth_service.user_repo.delete_user.assert_called_once_with(user)
        # Verify physical files cleaned up
        assert not doc_dir.exists()
        assert not ref_dir.exists()
        assert not gen_dir.exists()
        assert not visual_path.exists()
        assert mock_storage_del.called


def test_api_delete_account_endpoints():
    """Verify API endpoint DELETE /auth/delete-account with and without body."""
    test_user = User(
        id=uuid4(),
        name="API User",
        email="api_user@example.com",
        password_hash=get_password_hash("Password123!"),
        is_active=True,
    )

    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    client = TestClient(app)

    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch.object(AuthService, "delete_account", return_value=DeleteAccountResponse(message="Account successfully deleted.")) as mock_del:
            # 1. DELETE /api/v1/auth/delete-account with password body
            res1 = client.request("DELETE", "/api/v1/auth/delete-account", json={"password": "Password123!"})
            assert res1.status_code == 200
            assert res1.json() == {"message": "Account successfully deleted."}
            assert mock_del.called

            # 2. DELETE /api/v1/auth/delete-account without body
            mock_del.reset_mock()
            res2 = client.request("DELETE", "/api/v1/auth/delete-account")
            assert res2.status_code == 200
            assert res2.json() == {"message": "Account successfully deleted."}
            assert mock_del.called

            # 3. Verify POST /api/v1/auth/delete-account is not allowed
            res3 = client.post("/api/v1/auth/delete-account", json={"password": "Password123!"})
            assert res3.status_code == 405
    finally:
        app.dependency_overrides.clear()
