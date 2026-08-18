import time
import fitz
import httpx


def main():
    # 1. Setup sample PDF
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Real Docker Celery End To End Verification Test Content")
    pdf_bytes = doc.tobytes()
    doc.close()

    with httpx.Client(base_url="http://localhost:8000") as c:
        # 2. Register & Auth
        r_user = c.post(
            "/api/v1/auth/register",
            json={"name": "E2E User", "email": "e2e_celery_real@example.com", "password": "password123"},
        )
        token = r_user.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Hierarchy
        ws = c.post("/api/v1/workspaces", json={"name": "E2E WS"}, headers=headers).json()
        subj = c.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "E2E Subj"}, headers=headers).json()
        book = c.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "E2E Book"}, headers=headers).json()

        # 4. Real Upload
        upload = c.post(
            "/api/v1/documents/upload",
            data={"book_id": book["id"]},
            files={"file": ("e2e_test.pdf", pdf_bytes, "application/pdf")},
            headers=headers,
        )
        print("UPLOAD RESPONSE STATUS:", upload.status_code)
        print("UPLOAD RESPONSE BODY:", upload.json())
        doc_id = upload.json()["id"]

        # 5. Poll for Celery Worker processing
        for i in range(15):
            time.sleep(1)
            st = c.get(f"/api/v1/documents/{doc_id}", headers=headers).json()
            print(f"Poll {i+1}s: status={st['processing_status']}")
            if st["processing_status"] == "PROCESSED":
                print("SUCCESS: Real Celery worker processed document end-to-end!")
                return

        raise RuntimeError("Document processing timed out.")


if __name__ == "__main__":
    main()
