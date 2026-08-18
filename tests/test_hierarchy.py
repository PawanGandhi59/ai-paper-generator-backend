from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_full_workspace_hierarchy_and_ownership():
    uid = uuid4().hex[:8]
    email1 = f"teacher1_{uid}@example.com"
    email2 = f"teacher2_{uid}@example.com"

    # User 1
    u1 = client.post(
        "/api/v1/auth/register",
        json={"name": "Teacher One", "email": email1, "password": "password123"},
    )
    assert u1.status_code == 201
    h1 = {"Authorization": f"Bearer {u1.json()['access_token']}"}

    # User 2
    u2 = client.post(
        "/api/v1/auth/register",
        json={"name": "Teacher Two", "email": email2, "password": "password123"},
    )
    assert u2.status_code == 201
    h2 = {"Authorization": f"Bearer {u2.json()['access_token']}"}

    # 1. Create Workspace
    ws = client.post("/api/v1/workspaces", json={"name": "Physics Dept"}, headers=h1).json()
    ws_id = ws["id"]

    # 2. Create Subject
    subj = client.post(f"/api/v1/workspaces/{ws_id}/subjects", json={"name": "Physics"}, headers=h1).json()
    subj_id = subj["id"]
    assert subj["name"] == "Physics"

    # User 2 cannot create subject in User 1's workspace
    bad_subj = client.post(f"/api/v1/workspaces/{ws_id}/subjects", json={"name": "Malicious Subj"}, headers=h2)
    assert bad_subj.status_code == 404

    # 3. Create Book
    book = client.post(f"/api/v1/subjects/{subj_id}/books", json={"name": "NCERT Physics Vol 1"}, headers=h1).json()
    book_id = book["id"]
    assert book["name"] == "NCERT Physics Vol 1"

    # User 2 cannot list books in User 1's subject
    bad_books = client.get(f"/api/v1/subjects/{subj_id}/books", headers=h2)
    assert bad_books.status_code == 404

    # 4. Create Chapters
    ch1 = client.post(
        f"/api/v1/books/{book_id}/chapters",
        json={"chapter_number": 1, "name": "Electric Charges and Fields"},
        headers=h1,
    ).json()
    ch1_id = ch1["id"]

    ch2 = client.post(
        f"/api/v1/books/{book_id}/chapters",
        json={"chapter_number": 2, "name": "Electrostatic Potential"},
        headers=h1,
    ).json()

    # List chapters
    chapters = client.get(f"/api/v1/books/{book_id}/chapters", headers=h1).json()
    assert len(chapters) == 2
    assert chapters[0]["chapter_number"] == 1
    assert chapters[1]["chapter_number"] == 2

    # User 2 cannot update User 1's chapter
    bad_ch_patch = client.patch(
        f"/api/v1/chapters/{ch1_id}",
        json={"name": "Hacked Chapter"},
        headers=h2,
    )
    assert bad_ch_patch.status_code == 404

    # User 1 updates chapter
    good_ch_patch = client.patch(
        f"/api/v1/chapters/{ch1_id}",
        json={"name": "Electric Charges and Fields (Updated)"},
        headers=h1,
    )
    assert good_ch_patch.status_code == 200
    assert good_ch_patch.json()["name"] == "Electric Charges and Fields (Updated)"

    # User 1 deletes chapter
    del_ch = client.delete(f"/api/v1/chapters/{ch1_id}", headers=h1)
    assert del_ch.status_code == 204
