import time
from uuid import uuid4
import fitz
import httpx


def main():
    # 1. Setup sample PDF with fluid dynamics content
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Fluid Dynamics: Bernoulli's principle states that an increase in the speed of a fluid occurs simultaneously with a decrease in static pressure or fluid potential energy.")
    pdf_bytes = doc.tobytes()
    doc.close()

    uid = uuid4().hex[:8]
    email = f"e2e_rag_{uid}@example.com"

    with httpx.Client(base_url="http://localhost:8000", timeout=30.0) as c:
        # 2. Register & Auth
        r_user = c.post(
            "/api/v1/auth/register",
            json={"name": "RAG E2E User", "email": email, "password": "password123"},
        )
        token = r_user.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Hierarchy
        ws = c.post("/api/v1/workspaces", json={"name": "Physics Workspace"}, headers=headers).json()
        subj = c.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": "Fluid Mechanics"}, headers=headers).json()
        book = c.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": "Physics Vol 2"}, headers=headers).json()

        # 4. Upload Document
        upload = c.post(
            "/api/v1/documents/upload",
            data={"book_id": book["id"]},
            files={"file": ("fluid_mechanics.pdf", pdf_bytes, "application/pdf")},
            headers=headers,
        )
        print("UPLOAD RESPONSE STATUS:", upload.status_code)
        doc_id = upload.json()["id"]

        # 5. Poll for READY status (Document Processing + Embedding Pipeline)
        ready = False
        for i in range(15):
            time.sleep(1)
            st = c.get(f"/api/v1/documents/{doc_id}", headers=headers).json()
            print(f"Poll {i+1}s: status={st['processing_status']}")
            if st["processing_status"] == "READY":
                ready = True
                print("DOCUMENT IS READY FOR RAG RETRIEVAL!")
                break

        if not ready:
            raise RuntimeError("Document embedding pipeline timed out.")

        # 6. Execute RAG Query
        rag_payload = {
            "query": "Explain Bernoulli's principle",
            "workspace_id": ws["id"],
            "top_k": 3
        }
        rag_resp = c.post("/api/v1/ai/query", json=rag_payload, headers=headers)
        print("RAG QUERY STATUS:", rag_resp.status_code)
        rag_data = rag_resp.json()
        print("RAG ANSWER:", rag_data["answer"])
        print("RAG SOURCES:", rag_data["sources"])

        assert rag_resp.status_code == 200
        assert "answer" in rag_data
        assert len(rag_data["sources"]) > 0
        print("SUCCESS: Real RAG query executed end-to-end!")


if __name__ == "__main__":
    main()
