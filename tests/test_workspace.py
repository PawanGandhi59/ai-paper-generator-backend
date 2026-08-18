from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_workspace_crud_and_isolation():
    uid = uuid4().hex[:8]
    email_a = f"usera_{uid}@example.com"
    email_b = f"userb_{uid}@example.com"

    # Register User A
    user_a_reg = client.post(
        "/api/v1/auth/register",
        json={"name": "User A", "email": email_a, "password": "password123"},
    )
    assert user_a_reg.status_code == 201
    headers_a = {"Authorization": f"Bearer {user_a_reg.json()['access_token']}"}

    # Register User B
    user_b_reg = client.post(
        "/api/v1/auth/register",
        json={"name": "User B", "email": email_b, "password": "password123"},
    )
    assert user_b_reg.status_code == 201
    headers_b = {"Authorization": f"Bearer {user_b_reg.json()['access_token']}"}

    # User A creates Workspace
    ws_resp = client.post(
        "/api/v1/workspaces",
        json={"name": "Class 12 Science"},
        headers=headers_a,
    )
    assert ws_resp.status_code == 201
    ws_data = ws_resp.json()
    ws_id = ws_data["id"]
    assert ws_data["name"] == "Class 12 Science"

    # User A lists workspaces
    list_a = client.get("/api/v1/workspaces", headers=headers_a).json()
    assert len(list_a) >= 1
    assert any(w["id"] == ws_id for w in list_a)

    # User B cannot get User A's workspace
    unauth_get = client.get(f"/api/v1/workspaces/{ws_id}", headers=headers_b)
    assert unauth_get.status_code == 404

    # User B cannot update User A's workspace
    unauth_patch = client.patch(f"/api/v1/workspaces/{ws_id}", json={"name": "Hacked Workspace"}, headers=headers_b)
    assert unauth_patch.status_code == 404

    # User B cannot delete User A's workspace
    unauth_del = client.delete(f"/api/v1/workspaces/{ws_id}", headers=headers_b)
    assert unauth_del.status_code == 404

    # User A updates own workspace
    patch_a = client.patch(f"/api/v1/workspaces/{ws_id}", json={"name": "Class 12 Advanced Science"}, headers=headers_a)
    assert patch_a.status_code == 200
    assert patch_a.json()["name"] == "Class 12 Advanced Science"

    # User A deletes own workspace
    del_a = client.delete(f"/api/v1/workspaces/{ws_id}", headers=headers_a)
    assert del_a.status_code == 204
