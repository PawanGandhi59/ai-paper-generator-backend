# 📚 Backend API Endpoint Directory & Reference Guide

This document lists all available API endpoints in the **AI Paper Generator / Educational Tutor Backend**, organized by feature module, along with their exact HTTP method, route, authentication requirements, purpose, request body, and response structure.

---

## 📑 Table of Contents
1. [Health & System Monitoring](#1-health--system-monitoring)
2. [Authentication & Authorization](#2-authentication--authorization)
3. [Workspace Management](#3-workspace-management)
4. [Subject Management](#4-subject-management)
5. [Book Management](#5-book-management)
6. [Chapter Management](#6-chapter-management)
7. [Document Ingestion & Parsing](#7-document-ingestion--parsing)
8. [AI Educational Tutor & Visuals](#8-ai-educational-tutor--visuals)

---

## 1. Health & System Monitoring

### `GET /api/v1/health`
- **Purpose**: Verify backend container and web server status.
- **Auth Required**: No (Public)
- **Response**: `200 OK`
  ```json
  {
    "status": "healthy",
    "app_name": "AI Paper Generator",
    "environment": "development"
  }
  ```

### `GET /api/v1/health/db`
- **Purpose**: Test live database connection to PostgreSQL + pgvector.
- **Auth Required**: No (Public)
- **Response**: `200 OK`
  ```json
  {
    "status": "healthy",
    "database": "connected"
  }
  ```

---

## 2. Authentication & Authorization

### `POST /api/v1/auth/register`
- **Purpose**: Register a new student/user account using email and password.
- **Auth Required**: No (Public)
- **Request Body**:
  ```json
  {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "password": "SecurePassword123!"
  }
  ```
- **Response**: `201 Created`
  ```json
  {
    "access_token": "eyJhbGci...",
    "refresh_token": "eyJhbGci...",
    "token_type": "bearer",
    "user": {
      "id": "10956a2a-0a9a-4534-8bae-acb95fd48730",
      "name": "Jane Doe",
      "email": "jane@example.com"
    }
  }
  ```

### `POST /api/v1/auth/login`
- **Purpose**: Authenticate an existing user with email and password.
- **Auth Required**: No (Public)
- **Request Body**:
  ```json
  {
    "email": "jane@example.com",
    "password": "SecurePassword123!"
  }
  ```
- **Response**: `200 OK` (Returns access & refresh token pair).

### `POST /api/v1/auth/refresh`
- **Purpose**: Exchange a valid refresh token for a new access token (Token Rotation).
- **Auth Required**: No (Token in payload)
- **Request Body**:
  ```json
  {
    "refresh_token": "eyJhbGci..."
  }
  ```
- **Response**: `200 OK` (Returns new `access_token` and rotated `refresh_token`).

### `POST /api/v1/auth/logout`
- **Purpose**: Revoke active refresh token on logout.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**:
  ```json
  {
    "refresh_token": "eyJhbGci..."
  }
  ```
- **Response**: `200 OK` (`{"message": "Successfully logged out"}`)

### `POST /api/v1/auth/google`
- **Purpose**: Single Sign-On (SSO) login/registration via Google OAuth ID token.
- **Auth Required**: No (Public)
- **Request Body**:
  ```json
  {
    "id_token": "google-oauth-jwt-token"
  }
  ```
- **Response**: `200 OK` (Returns user object and token pair).

---

## 3. Workspace Management

Workspaces serve as top-level multi-tenant security isolation boundaries.

### `POST /api/v1/workspaces`
- **Purpose**: Create a new workspace.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**: `{"name": "Physics & Chemistry 2026"}`
- **Response**: `201 Created`

### `GET /api/v1/workspaces`
- **Purpose**: List all workspaces owned by the authenticated user.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK` (Array of user workspaces).

### `GET /api/v1/workspaces/{workspace_id}`
- **Purpose**: Retrieve details of a specific workspace.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `PUT /api/v1/workspaces/{workspace_id}`
- **Purpose**: Update workspace name.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**: `{"name": "Updated Workspace Name"}`
- **Response**: `200 OK`

### `DELETE /api/v1/workspaces/{workspace_id}`
- **Purpose**: Delete workspace and all associated subjects, books, chapters, and document embeddings.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `204 No Content`

---

## 4. Subject Management

Subjects organize course content within a workspace.

### `POST /api/v1/workspaces/{workspace_id}/subjects`
- **Purpose**: Create a new subject under a workspace.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**: `{"name": "Thermodynamics", "code": "PHYS-201"}`
- **Response**: `201 Created`

### `GET /api/v1/workspaces/{workspace_id}/subjects`
- **Purpose**: List all subjects within a workspace.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `GET /api/v1/subjects/{subject_id}`
- **Purpose**: Get specific subject details.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `PUT /api/v1/subjects/{subject_id}`
- **Purpose**: Update subject details.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `DELETE /api/v1/subjects/{subject_id}`
- **Purpose**: Delete subject and child books/chapters.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `204 No Content`

---

## 5. Book Management

Books represent textbooks or study materials under a subject.

### `POST /api/v1/subjects/{subject_id}/books`
- **Purpose**: Create a book entry under a subject.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**: `{"title": "Concepts of Physics", "author": "H.C. Verma"}`
- **Response**: `201 Created`

### `GET /api/v1/subjects/{subject_id}/books`
- **Purpose**: List all books belonging to a subject.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `GET /api/v1/books/{book_id}`
- **Purpose**: Get specific book details.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `PUT /api/v1/books/{book_id}`
- **Purpose**: Update book title or metadata.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `DELETE /api/v1/books/{book_id}`
- **Purpose**: Delete a book and its chapters/documents.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `204 No Content`

---

## 6. Chapter Management

Chapters partition books into specific topics.

### `POST /api/v1/books/{book_id}/chapters`
- **Purpose**: Create a chapter within a book.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Request Body**: `{"chapter_number": 1, "title": "Laws of Motion"}`
- **Response**: `201 Created`

### `GET /api/v1/books/{book_id}/chapters`
- **Purpose**: List chapters in a book ordered by chapter number.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `GET /api/v1/chapters/{chapter_id}`
- **Purpose**: Get specific chapter details.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `PUT /api/v1/chapters/{chapter_id}`
- **Purpose**: Update chapter number or title.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `DELETE /api/v1/chapters/{chapter_id}`
- **Purpose**: Delete chapter and documents.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `204 No Content`

---

## 7. Document Ingestion & Parsing

Handles PDF/PPTX uploads, PyMuPDF page parsing, Tesseract OCR fallback, chunking, and pgvector embedding generation via Celery workers.

### `POST /api/v1/documents/upload`
- **Purpose**: Upload a course material document (PDF/PPTX) to a book or chapter. Triggers asynchronous Celery background parsing and vector embedding.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `file`: Document file binary
  - `book_id`: Target Book UUID
  - `chapter_id` *(optional)*: Target Chapter UUID
- **Response**: `202 Accepted`
  ```json
  {
    "id": "5da58ee1-247d-4462-8f70-bfd9b9e3d9d9",
    "filename": "thermodynamics.pdf",
    "status": "PROCESSING",
    "message": "Document uploaded successfully and queued for background processing."
  }
  ```

### `GET /api/v1/documents/{document_id}`
- **Purpose**: Check processing status (`PROCESSING`, `READY`, `FAILED`), total page count, and metadata of an uploaded document.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `200 OK`

### `DELETE /api/v1/documents/{document_id}`
- **Purpose**: Delete document file from storage and remove all vector chunks from pgvector database.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Response**: `204 No Content`

---

## 8. AI Educational Tutor & Visuals

AI RAG Educational Tutor powered by **Gemini 3.1 Flash Image** and **LangChain LCEL**.

### `POST /api/v1/ai/query`
- **Purpose**: Execute an authenticated educational RAG query. Performs cosine similarity search across workspace documents, constructs structured context, and queries Gemini to generate Markdown explanations and structured visual artifacts (Mermaid diagrams, JSON charts, or educational images).
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Rate Limit**: 10 requests per 60 seconds per user (Sliding Window Redis Rate Limiter).
- **Request Body**:
  ```json
  {
    "query": "Explain with a clear text diagram: how are the different birds near Jaggu's house categorized?",
    "workspace_id": "51168143-ef07-412f-9ba5-ce946bbbdd65",
    "book_id": "6d210a6e-ecbd-4ce9-8198-da6904f4e8cd",
    "chapter_id": "7430b450-f4c4-4d56-b1d3-c409485e9ba3",
    "document_id": "5da58ee1-247d-4462-8f70-bfd9b9e3d9d9",
    "top_k": 5
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "answer": "The birds near Jaggu's house are classified by color...",
    "visuals": [
      {
        "id": "visual_1",
        "type": "diagram",
        "format": "mermaid",
        "title": "Bird Classification Tree",
        "content": "graph TD\n  Birds --> Crow[Crow: Black]\n  Birds --> Pigeon[Pigeon: Grey]",
        "caption": "Classification based on features"
      }
    ],
    "model_used": "gemini-3.1-flash-image",
    "sources": [
      {
        "chunk_id": "8de93dc9-8ba0-4105-a5d2-78bc8d727ccd",
        "document_id": "5da58ee1-247d-4462-8f70-bfd9b9e3d9d9",
        "page_number": 6,
        "chapter_id": "7430b450-f4c4-4d56-b1d3-c409485e9ba3",
        "distance": 0.2831
      }
    ]
  }
  ```

### `GET /api/v1/ai/visuals/{visual_id}`
- **Purpose**: Stream authenticated generated PNG image files created by `gemini-3.1-flash-image`.
- **Auth Required**: Yes (`Bearer <ACCESS_TOKEN>`)
- **Security Check**: Checks `visual.user_id == current_user.id` to enforce IDOR security defense, returning `404 Not Found` for unauthorized access attempts.
- **Response**: Binary file stream (`Content-Type: image/png`).
