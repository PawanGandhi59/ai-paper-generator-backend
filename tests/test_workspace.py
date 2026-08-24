from uuid import uuid4
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.document import Document, DocumentChunk, DocumentPage

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


def test_manual_chapter_page_range_reassignment_and_security():
    uid = uuid4().hex[:8]
    email_a = f"usera_{uid}@example.com"
    email_b = f"userb_{uid}@example.com"

    # User A
    user_a = client.post("/api/v1/auth/register", json={"name": "User A", "email": email_a, "password": "password123"}).json()
    headers_a = {"Authorization": f"Bearer {user_a['access_token']}"}

    # User B
    user_b = client.post("/api/v1/auth/register", json={"name": "User B", "email": email_b, "password": "password123"}).json()
    headers_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    # User A creates hierarchy
    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers_a).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Subj_{uid}"}, headers=headers_a).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Book_{uid}"}, headers=headers_a).json()

    # Manually insert document chunks for pages 1 to 100 in DB
    db = SessionLocal()
    try:
        doc = Document(
            book_id=book["id"],
            original_filename="manual_book.pdf",
            stored_path="/fake/path.pdf",
            mime_type="application/pdf",
            file_size=1000,
            processing_status="READY",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        for p in range(1, 101):
            chk = DocumentChunk(
                document_id=doc.id,
                book_id=book["id"],
                subject_id=subj["id"],
                workspace_id=ws["id"],
                chunk_index=p - 1,
                page_number=p,
                content=f"Content for page {p}",
                chapter_id=None,
            )
            db.add(chk)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    # User A creates Chapter 1 with page range 1..20
    ch1_res = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 1, "name": "Chapter 1", "start_page": 1, "end_page": 20},
        headers=headers_a,
    )
    assert ch1_res.status_code == 201
    ch1 = ch1_res.json()
    assert ch1["start_page"] == 1
    assert ch1["end_page"] == 20

    # Verify chunks 1..20 received ch1["id"]
    db = SessionLocal()
    try:
        ch1_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id, DocumentChunk.chapter_id == ch1["id"]).all()
        assert len(ch1_chunks) == 20
        for c in ch1_chunks:
            assert 1 <= c.page_number <= 20
    finally:
        db.close()

    # User A creates Chapter 2 with page range 21..50
    ch2_res = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 2, "name": "Chapter 2", "start_page": 21, "end_page": 50},
        headers=headers_a,
    )
    assert ch2_res.status_code == 201
    ch2 = ch2_res.json()

    # Update Chapter 2 range to 21..60 (expanding)
    patch_res = client.patch(
        f"/api/v1/chapters/{ch2['id']}",
        json={"end_page": 60},
        headers=headers_a,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["end_page"] == 60

    # Verify chunks 21..60 now belong to Chapter 2
    db = SessionLocal()
    try:
        ch2_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id, DocumentChunk.chapter_id == ch2["id"]).all()
        assert len(ch2_chunks) == 40  # 21..60
    finally:
        db.close()

    # Security check: User B cannot update User A's chapter or trigger chunk reassignment
    unauth_patch = client.patch(
        f"/api/v1/chapters/{ch2['id']}",
        json={"start_page": 1, "end_page": 100},
        headers=headers_b,
    )
    assert unauth_patch.status_code == 404


def test_create_chapter_page_range_requires_whole_book_pdf():
    uid = uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Page Check User", "email": f"page_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": "Bio WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Biology"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Genetics"}, headers=headers).json()

    # 1. Attempt to create chapter with page range without uploading a whole book PDF -> 400 Bad Request
    bad_ch = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 1, "name": "DNA Structure", "start_page": 1, "end_page": 10},
        headers=headers,
    )
    assert bad_ch.status_code == 400
    assert "no whole book document has been uploaded" in bad_ch.json()["detail"]

    # 2. Creating chapter WITHOUT page range is allowed -> 201 Created
    good_ch = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 1, "name": "DNA Structure"},
        headers=headers,
    )
    assert good_ch.status_code == 201
    assert good_ch.json()["start_page"] is None
    assert good_ch.json()["end_page"] is None

    # 3. Attempting to patch page range on chapter without whole book PDF -> 400 Bad Request
    bad_patch = client.patch(
        f"/api/v1/chapters/{good_ch.json()['id']}",
        json={"start_page": 1, "end_page": 10},
        headers=headers,
    )
    assert bad_patch.status_code == 400
    assert "no whole book document has been uploaded" in bad_patch.json()["detail"]

    # 4. Now upload whole book PDF to DB
    db = SessionLocal()
    try:
        doc = Document(
            book_id=book["id"],
            original_filename="genetics_book.pdf",
            stored_path="/fake/genetics.pdf",
            mime_type="application/pdf",
            file_size=2000,
            processing_status="READY",
        )
        db.add(doc)
        db.commit()
    finally:
        db.close()

    # 5. Attempting to create chapter WITHOUT page range when whole book PDF exists -> 400 Bad Request
    missing_pages_ch = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 2, "name": "RNA Transcription"},
        headers=headers,
    )
    assert missing_pages_ch.status_code == 400
    assert "start_page and end_page are required" in missing_pages_ch.json()["detail"]

    # 6. Creating chapter WITH page range when whole book PDF exists -> 201 Created
    valid_whole_ch = client.post(
        f"/api/v1/books/{book['id']}/chapters",
        json={"chapter_number": 2, "name": "RNA Transcription", "start_page": 11, "end_page": 20},
        headers=headers,
    )
    assert valid_whole_ch.status_code == 201
    assert valid_whole_ch.json()["start_page"] == 11
    assert valid_whole_ch.json()["end_page"] == 20

