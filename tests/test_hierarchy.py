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


def test_chapter_number_validation_and_duplicate_prevention():
    uid = uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Dup User", "email": f"dup_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": "Math WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Algebra"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Linear Algebra"}, headers=headers).json()

    # 1. Missing chapter_number returns 422 Unprocessable Entity (Field Required)
    missing_ch = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Poems"}, headers=headers)
    assert missing_ch.status_code == 422

    # 2. Create Chapter 1 -> 201 Created
    ch1 = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 1, "name": "Matrices"},
        headers=headers,
    )
    assert ch1.status_code == 201
    assert ch1.json()["chapter_number"] == 1

    # 3. Create Duplicate Chapter 1 -> 400 Bad Request
    dup_ch = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 1, "name": "Vectors"},
        headers=headers,
    )
    assert dup_ch.status_code == 400
    assert "already exists in this book" in dup_ch.json()["detail"]

    # 4. Create Chapter 2 -> 201 Created
    ch2 = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 2, "name": "Vectors"},
        headers=headers,
    )
    assert ch2.status_code == 201

    # 5. Patch Chapter 2 to Chapter 1 -> 400 Bad Request (duplicate conflict)
    patch_dup = client.patch(
        f"/api/v1/chapters/{ch2.json()['id']}",
        json={"chapter_number": 1},
        headers=headers,
    )
    assert patch_dup.status_code == 400
    assert "already exists in this book" in patch_dup.json()["detail"]
