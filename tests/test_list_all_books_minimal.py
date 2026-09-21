from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register_user(name_prefix: str):
    uid = uuid4().hex[:8]
    email = f"{name_prefix}_{uid}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"name": f"{name_prefix} Name", "email": email, "password": "password123"},
    )
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_list_all_books_minimal_structure_and_values():
    headers = _register_user("user_struct")

    # 1. Create Workspace
    ws_resp = client.post(
        "/api/v1/workspaces",
        json={"name": "Grade 11 Science"},
        headers=headers,
    )
    assert ws_resp.status_code == 201
    ws_id = ws_resp.json()["id"]

    # 2. Create Subject
    subj_resp = client.post(
        f"/api/v1/workspaces/{ws_id}/subjects",
        json={"name": "Physics"},
        headers=headers,
    )
    assert subj_resp.status_code == 201
    subj_id = subj_resp.json()["id"]

    # 3. Create Book
    book_resp = client.post(
        f"/api/v1/subjects/{subj_id}/books",
        json={"name": "NCERT Physics Part 1"},
        headers=headers,
    )
    assert book_resp.status_code == 201
    book_id = book_resp.json()["id"]

    # 4. Add Chapters (in non-sequential creation order to test chapter_number sorting)
    ch2_resp = client.post(
        f"/api/v1/books/{book_id}/chapters",
        json={"chapter_number": 2, "name": "Units and Measurements"},
        headers=headers,
    )
    assert ch2_resp.status_code == 201
    ch1_resp = client.post(
        f"/api/v1/books/{book_id}/chapters",
        json={"chapter_number": 1, "name": "Physical World"},
        headers=headers,
    )
    assert ch1_resp.status_code == 201

    # 5. Call GET /api/v1/books
    resp = client.get("/api/v1/books", headers=headers)
    assert resp.status_code == 200
    books = resp.json()

    assert isinstance(books, list)
    assert len(books) >= 1

    matched = next((b for b in books if b["id"] == book_id), None)
    assert matched is not None
    assert matched["name"] == "NCERT Physics Part 1"
    assert "pdf_url" in matched

    # Verify Minimal Workspace metadata
    assert matched["workspace"]["id"] == ws_id
    assert matched["workspace"]["name"] == "Grade 11 Science"

    # Verify Minimal Subject metadata
    assert matched["subject"]["id"] == subj_id
    assert matched["subject"]["name"] == "Physics"

    # Verify Chapters: strictly minimal (id, chapter_number, name) and sorted by chapter_number
    assert len(matched["chapters"]) == 2
    assert matched["chapters"][0]["chapter_number"] == 1
    assert matched["chapters"][0]["name"] == "Physical World"
    assert matched["chapters"][1]["chapter_number"] == 2
    assert matched["chapters"][1]["name"] == "Units and Measurements"

    # Verify that heavy fields like exam_digest, page content, vectors are NOT included in minimal schema
    assert "exam_digest" not in matched["chapters"][0]
    assert "start_page" not in matched["chapters"][0]
    assert "end_page" not in matched["chapters"][0]


def test_list_all_books_no_parameters_returns_all_workspaces():
    headers = _register_user("user_noparam")

    # Workspace 1 with Book 1
    ws1 = client.post("/api/v1/workspaces", json={"name": "WS 1"}, headers=headers).json()
    subj1 = client.post(f"/api/v1/workspaces/{ws1['id']}/subjects", json={"name": "Subj 1"}, headers=headers).json()
    b1 = client.post(f"/api/v1/subjects/{subj1['id']}/books", json={"name": "Book 1"}, headers=headers).json()

    # Workspace 2 with Book 2
    ws2 = client.post("/api/v1/workspaces", json={"name": "WS 2"}, headers=headers).json()
    subj2 = client.post(f"/api/v1/workspaces/{ws2['id']}/subjects", json={"name": "Subj 2"}, headers=headers).json()
    b2 = client.post(f"/api/v1/subjects/{subj2['id']}/books", json={"name": "Book 2"}, headers=headers).json()

    # Call GET /api/v1/books without any query parameters -> Returns all user books across all workspaces
    resp = client.get("/api/v1/books", headers=headers)
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()]
    assert b1["id"] in ids
    assert b2["id"] in ids


def test_list_all_books_chapter_wise_upload():
    from app.core.database import SessionLocal
    from app.models.document import Document

    headers = _register_user("user_ch_upload")

    ws = client.post("/api/v1/workspaces", json={"name": "Science WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Chemistry"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Organic Chemistry"}, headers=headers).json()

    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"chapter_number": 1, "name": "Hydrocarbons"}, headers=headers).json()
    ch2 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"chapter_number": 2, "name": "Alcohols"}, headers=headers).json()

    # Simulate chapter-wise upload for Chapter 1
    db = SessionLocal()
    try:
        doc = Document(
            book_id=book["id"],
            chapter_id=ch1["id"],
            original_filename="chapter_1_hydrocarbons.pdf",
            stored_path="/fake/chapter_1.pdf",
            mime_type="application/pdf",
            file_size=5000,
            processing_status="READY",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = str(doc.id)
    finally:
        db.close()

    # Call GET /api/v1/books
    resp = client.get("/api/v1/books", headers=headers)
    assert resp.status_code == 200
    matched = next(b for b in resp.json() if b["id"] == book["id"])

    # Book has no whole-book pdf_url
    assert matched["pdf_url"] is None

    # Chapter 1 has its chapter-specific pdf_url
    assert matched["chapters"][0]["id"] == ch1["id"]
    assert matched["chapters"][0]["pdf_url"] == f"/storage/documents/{doc_id}/original.pdf"

    # Chapter 2 has no document uploaded yet
    assert matched["chapters"][1]["id"] == ch2["id"]
    assert matched["chapters"][1]["pdf_url"] is None


def test_list_all_books_user_isolation():
    headers_a = _register_user("user_iso_a")
    headers_b = _register_user("user_iso_b")

    # User A creates Book A
    ws_a = client.post("/api/v1/workspaces", json={"name": "User A WS"}, headers=headers_a).json()
    subj_a = client.post(f"/api/v1/workspaces/{ws_a['id']}/subjects", json={"name": "User A Subj"}, headers=headers_a).json()
    b_a = client.post(f"/api/v1/subjects/{subj_a['id']}/books", json={"name": "User A Book"}, headers=headers_a).json()

    # User B lists books
    resp_b = client.get("/api/v1/books", headers=headers_b)
    assert resp_b.status_code == 200
    ids_b = [b["id"] for b in resp_b.json()]
    assert b_a["id"] not in ids_b


def test_list_all_books_soft_deleted_handling():
    headers = _register_user("user_del")

    ws = client.post("/api/v1/workspaces", json={"name": "Del WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Del Subj"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Del Book"}, headers=headers).json()

    # Add 2 chapters
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"chapter_number": 1, "name": "Active Ch"}, headers=headers).json()
    ch2 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"chapter_number": 2, "name": "To Delete Ch"}, headers=headers).json()

    # Delete Chapter 2
    del_ch_resp = client.delete(f"/api/v1/chapters/{ch2['id']}", headers=headers)
    assert del_ch_resp.status_code == 204

    # Check that GET /api/v1/books shows book with only active Chapter 1
    resp = client.get("/api/v1/books", headers=headers)
    assert resp.status_code == 200
    matched = next(b for b in resp.json() if b["id"] == book["id"])
    assert len(matched["chapters"]) == 1
    assert matched["chapters"][0]["id"] == ch1["id"]

    # Delete Book
    del_book_resp = client.delete(f"/api/v1/books/{book['id']}", headers=headers)
    assert del_book_resp.status_code == 204

    # Verify book is no longer returned in GET /api/v1/books
    resp_after = client.get("/api/v1/books", headers=headers)
    assert resp_after.status_code == 200
    assert not any(b["id"] == book["id"] for b in resp_after.json())


def test_list_all_books_ignores_generated_papers():
    from app.core.database import SessionLocal
    from app.models.document import Document

    headers = _register_user("user_gen_doc")

    ws = client.post("/api/v1/workspaces", json={"name": "GenPaper WS"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Physics"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "NCERT Physics"}, headers=headers).json()

    db = SessionLocal()
    try:
        # First doc: Generated paper PDF
        gen_doc = Document(
            book_id=book["id"],
            chapter_id=None,
            original_filename="final.pdf",
            stored_path="/app/storage/generated_papers/fake-paper-id/final.pdf",
            mime_type="application/pdf",
            file_size=1024,
            processing_status="READY",
        )
        db.add(gen_doc)

        # Second doc: Authentic textbook PDF
        book_doc_id = uuid4()
        book_doc = Document(
            id=book_doc_id,
            book_id=book["id"],
            chapter_id=None,
            original_filename="leph101.pdf",
            stored_path=f"/app/storage/documents/{book_doc_id}/original.pdf",
            mime_type="application/pdf",
            file_size=2048,
            processing_status="READY",
        )
        db.add(book_doc)
        db.commit()
        db.refresh(book_doc)
        expected_url = f"/storage/documents/{book_doc_id}/original.pdf"
    finally:
        db.close()

    resp = client.get("/api/v1/books", headers=headers)
    assert resp.status_code == 200
    matched = next(b for b in resp.json() if b["id"] == book["id"])

    # Must pick the textbook doc, ignoring final.pdf from generated papers
    assert matched["pdf_url"] == expected_url

