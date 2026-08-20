import io
import os
import uuid

import fitz
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.reference_paper import ReferencePaper, ReferencePaperPage

client = TestClient(app)


def create_sample_pdf_bytes(pages_count: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(pages_count):
        page = doc.new_page()
        page.insert_text((50, 50), f"Sample Reference Paper Question Text Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_upload_reference_paper_success():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User", "email": f"ref_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"DBMS_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    files = {"file": ("exam_2025.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {
        "title": "DBMS Final Exam 2025",
        "year": "2025",
        "exam_type": "Final Exam",
    }

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    paper_res = res.json()

    assert paper_res["title"] == "DBMS Final Exam 2025"
    assert paper_res["year"] == 2025
    assert paper_res["exam_type"] == "Final Exam"
    assert paper_res["subject_id"] == subj["id"]
    assert paper_res["workspace_id"] == ws["id"]

    db = SessionLocal()
    try:
        # Verify DB records
        paper_db = db.query(ReferencePaper).filter(ReferencePaper.id == paper_res["id"]).first()
        assert paper_db is not None
        assert os.path.exists(paper_db.stored_path)

        # Verify page text records created
        pages_db = db.query(ReferencePaperPage).filter(ReferencePaperPage.reference_paper_id == paper_db.id).all()
        assert len(pages_db) == 2
        assert "Sample Reference Paper" in pages_db[0].text_content
    finally:
        db.close()


def test_upload_reference_paper_invalid_extension():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User 2", "email": f"ref2_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Math_{uid}"}, headers=headers).json()

    files = {"file": ("exam.txt", io.BytesIO(b"Not a pdf"), "text/plain")}
    data = {"title": "Math Exam"}

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file extension" in res.json()["detail"]


def test_upload_reference_paper_invalid_header_signature():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Ref User 3", "email": f"ref3_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Physics_{uid}"}, headers=headers).json()

    files = {"file": ("fake.pdf", io.BytesIO(b"Fake PDF text content"), "application/pdf")}
    data = {"title": "Physics Paper"}

    res = client.post(f"/api/v1/subjects/{subj['id']}/reference-papers", data=data, files=files, headers=headers)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Missing %PDF header signature" in res.json()["detail"]


def test_list_and_get_reference_papers():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "List User", "email": f"list_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Algo_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()

    # Upload 2 papers
    p1 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Midterm 2024", "year": "2024"},
        files={"file": ("p1.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    p2 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Final 2024", "year": "2024"},
        files={"file": ("p2.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    # List papers
    list_res = client.get(f"/api/v1/subjects/{subj['id']}/reference-papers", headers=headers)
    assert list_res.status_code == status.HTTP_200_OK
    papers_list = list_res.json()
    assert len(papers_list) == 2

    # Get detail by ID
    detail_res = client.get(f"/api/v1/reference-papers/{p1['id']}", headers=headers)
    assert detail_res.status_code == status.HTTP_200_OK
    detail = detail_res.json()
    assert detail["title"] == "Midterm 2024"
    assert "pages" in detail
    assert len(detail["pages"]) == 2


def test_delete_reference_paper_db_and_filesystem():
    uid = uuid.uuid4().hex[:8]
    user = client.post("/api/v1/auth/register", json={"name": "Del User", "email": f"del_{uid}@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Chem_{uid}"}, headers=headers).json()

    pdf_bytes = create_sample_pdf_bytes()
    p1 = client.post(
        f"/api/v1/subjects/{subj['id']}/reference-papers",
        data={"title": "Chem Test 2023"},
        files={"file": ("chem.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    ).json()

    paper_id = p1["id"]
    db = SessionLocal()
    try:
        paper_db = db.query(ReferencePaper).filter(ReferencePaper.id == paper_id).first()
        stored_path = paper_db.stored_path
        paper_dir = os.path.dirname(stored_path)
    finally:
        db.close()

    assert os.path.exists(stored_path)

    # Delete paper
    del_res = client.delete(f"/api/v1/reference-papers/{paper_id}", headers=headers)
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    db2 = SessionLocal()
    try:
        # DB record deleted
        assert db2.query(ReferencePaper).filter(ReferencePaper.id == paper_id).first() is None
    finally:
        db2.close()

    # Filesystem deleted
    assert not os.path.exists(paper_dir)


def test_reference_paper_unauthorized_access():
    uid1 = uuid.uuid4().hex[:8]
    uid2 = uuid.uuid4().hex[:8]

    user1 = client.post("/api/v1/auth/register", json={"name": "User 1", "email": f"u1_{uid1}@example.com", "password": "password123"}).json()
    user2 = client.post("/api/v1/auth/register", json={"name": "User 2", "email": f"u2_{uid2}@example.com", "password": "password123"}).json()

    h1 = {"Authorization": f"Bearer {user1['access_token']}"}
    h2 = {"Authorization": f"Bearer {user2['access_token']}"}

    ws1 = client.post("/api/v1/workspaces", json={"name": f"WS1_{uid1}"}, headers=h1).json()
    subj1 = client.post(f"/api/v1/workspaces/{ws1['id']}/subjects", json={"name": f"Subj1_{uid1}"}, headers=h1).json()

    pdf_bytes = create_sample_pdf_bytes()
    p1 = client.post(
        f"/api/v1/subjects/{subj1['id']}/reference-papers",
        data={"title": "Private Paper"},
        files={"file": ("priv.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=h1,
    ).json()

    # User 2 attempts to upload to User 1's subject -> 404
    bad_up = client.post(
        f"/api/v1/subjects/{subj1['id']}/reference-papers",
        data={"title": "Hacked Paper"},
        files={"file": ("hack.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=h2,
    )
    assert bad_up.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to get User 1's paper -> 404
    bad_get = client.get(f"/api/v1/reference-papers/{p1['id']}", headers=h2)
    assert bad_get.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to delete User 1's paper -> 404
    bad_del = client.delete(f"/api/v1/reference-papers/{p1['id']}", headers=h2)
    assert bad_del.status_code == status.HTTP_404_NOT_FOUND
