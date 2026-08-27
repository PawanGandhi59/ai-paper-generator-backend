# AI Paper Generator Backend — API Documentation

This document provides a comprehensive, production-ready API guide for integrating with the **AI Paper Generator Backend**. It is designed for frontend developers building mobile or web client applications.

---

## 1. Overview & Architecture

### Base URL
- **Local Development**: `http://localhost:8000/api/v1`
- **Production Server**: `https://your-domain.com/api/v1`

### Authentication Model
- All protected endpoints require a **JWT Bearer Token** passed in the HTTP Request Header:
  ```http
  Authorization: Bearer <your_jwt_access_token>
  ```
- Unprotected endpoints: `/auth/register`, `/auth/login`, `/health`, `/health/db`.

### Data Formats & Headers
- **Request Body**: `application/json` (except file upload endpoints which use `multipart/form-data`).
- **Response Body**: `application/json`.
- **Date/Time Standard**: ISO-8601 strings (`YYYY-MM-DDTHH:MM:SS.uuuuuuZ`).
- **UUID Standards**: All entity IDs are standard 36-character UUID strings (e.g., `95b10b9f-1346-4a75-af03-4ee2c24d6e29`).

---

## 2. Entity Hierarchy & Workspace Flow

The system enforces multi-tenant security and workspace scoping according to the following strict hierarchy:

```
Workspace
 └── Subject
      ├── Book
      │    ├── Chapter
      │    └── Educational Document (PDF/PPTX) -> Chunking, OCR & Vector Embedding
      └── Reference Paper (Past/Sample PDF) -> Blueprint Extraction & Adaptation
```

---

## 3. Standard HTTP Response Codes

| Status Code | Meaning | Cause |
| :--- | :--- | :--- |
| `200 OK` | Success | The request succeeded and payload is returned. |
| `201 Created` | Created | The entity was successfully created. |
| `400 Bad Request` | Client Error | Invalid parameter, un-grounded source material, or math mismatch. |
| `401 Unauthorized` | Auth Error | Missing or expired JWT bearer token. |
| `403 Forbidden` | Permission Error | User does not own the requested resource/workspace. |
| `404 Not Found` | Not Found | Entity ID does not exist. |
| `422 Unprocessable` | Validation Error | Missing required fields or invalid UUID/data type format. |
| `429 Rate Exceeded` | Quota Exceeded | Redis/Gemini rate limit exceeded. |
| `500 Server Error` | Backend Failure | Internal server exception. |

---

## 4. Complete Endpoint Reference

---

### Section 1: Authentication & User Profile

#### 1.1 Register New User
- **Method**: `POST`
- **Endpoint**: `/auth/register`
- **Auth Required**: No
- **Purpose**: Creates a new user account.

**Request Body**:
```json
{
  "name": "John Doe",
  "email": "teacher@example.com",
  "password": "SecurePassword123"
}
```

**Response (`201 Created`)**:
```json
{
  "id": "daa50eaf-7a0d-40f3-a2a0-e7cc75943d23",
  "name": "John Doe",
  "email": "teacher@example.com",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "created_at": "2026-08-24T10:00:00.000000Z"
}
```

---

#### 1.2 Login & Token Generation
- **Method**: `POST`
- **Endpoint**: `/auth/login`
- **Auth Required**: No
- **Purpose**: Authenticates credentials and returns a JWT access token.

**Request Body**:
```json
{
  "email": "teacher@example.com",
  "password": "SecurePassword123"
}
```

**Response (`200 OK`)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

#### 1.3 Get Current User Profile
- **Method**: `GET`
- **Endpoint**: `/auth/me`
- **Auth Required**: Yes (`Bearer Token`)
- **Purpose**: Retrieves profile information for the authenticated user.

**Response (`200 OK`)**:
```json
{
  "id": "daa50eaf-7a0d-40f3-a2a0-e7cc75943d23",
  "name": "John Doe",
  "email": "teacher@example.com",
  "created_at": "2026-08-24T10:00:00.000000Z"
}
```

---

### Section 2: Workspaces

#### 2.1 Create Workspace
- **Method**: `POST`
- **Endpoint**: `/workspaces`
- **Auth Required**: Yes
- **Purpose**: Creates an isolated workspace container (e.g. "Grade 10 English", "Semester 1").

**Request Body**:
```json
{
  "name": "Grade 10 Curriculum"
}
```

**Response (`201 Created`)**:
```json
{
  "id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "name": "Grade 10 Curriculum",
  "owner_id": "daa50eaf-7a0d-40f3-a2a0-e7cc75943d23",
  "created_at": "2026-08-24T10:05:00.000000Z",
  "updated_at": "2026-08-24T10:05:00.000000Z"
}
```

---

#### 2.2 List Workspaces
- **Method**: `GET`
- **Endpoint**: `/workspaces`
- **Auth Required**: Yes
- **Purpose**: Returns all workspaces owned by the user.

**Response (`200 OK`)**:
```json
[
  {
    "id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
    "name": "Grade 10 Curriculum",
    "owner_id": "daa50eaf-7a0d-40f3-a2a0-e7cc75943d23",
    "created_at": "2026-08-24T10:05:00.000000Z",
    "updated_at": "2026-08-24T10:05:00.000000Z"
  }
]
```

---

#### 2.3 Get Workspace Details
- **Method**: `GET`
- **Endpoint**: `/workspaces/{workspace_id}`
- **Auth Required**: Yes

**Response (`200 OK`)**:
```json
{
  "id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "name": "Grade 10 Curriculum",
  "owner_id": "daa50eaf-7a0d-40f3-a2a0-e7cc75943d23",
  "created_at": "2026-08-24T10:05:00.000000Z",
  "updated_at": "2026-08-24T10:05:00.000000Z"
}
```

---

#### 2.4 Delete Workspace
- **Method**: `DELETE`
- **Endpoint**: `/workspaces/{workspace_id}`
- **Auth Required**: Yes
- **Purpose**: Deletes workspace and all nested subjects, books, documents, and generated papers.

**Response (`204 No Content`)**

---

### Section 3: Subjects

#### 3.1 Create Subject
- **Method**: `POST`
- **Endpoint**: `/workspaces/{workspace_id}/subjects`
- **Auth Required**: Yes

**Request Body**:
```json
{
  "name": "English Literature"
}
```

**Response (`201 Created`)**:
```json
{
  "id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
  "workspace_id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "name": "English Literature",
  "created_at": "2026-08-24T10:10:00.000000Z",
  "updated_at": "2026-08-24T10:10:00.000000Z"
}
```

---

#### 3.2 List Subjects in Workspace
- **Method**: `GET`
- **Endpoint**: `/workspaces/{workspace_id}/subjects`
- **Auth Required**: Yes

**Response (`200 OK`)**:
```json
[
  {
    "id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
    "workspace_id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
    "name": "English Literature",
    "created_at": "2026-08-24T10:10:00.000000Z",
    "updated_at": "2026-08-24T10:10:00.000000Z"
  }
]
```

---

### Section 4: Books

#### 4.1 Create Book
- **Method**: `POST`
- **Endpoint**: `/subjects/{subject_id}/books`
- **Auth Required**: Yes

**Request Body**:
```json
{
  "name": "Santoor Reader Grade 10"
}
```

**Response (`201 Created`)**:
```json
{
  "id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "subject_id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
  "name": "Santoor Reader Grade 10",
  "created_at": "2026-08-24T10:15:00.000000Z",
  "updated_at": "2026-08-24T10:15:00.000000Z"
}
```

---

#### 4.2 List Books in Subject
- **Method**: `GET`
- **Endpoint**: `/subjects/{subject_id}/books`
- **Auth Required**: Yes

---

### Section 5: Chapters

#### 5.1 Create Chapter Manually
- **Method**: `POST`
- **Endpoint**: `/books/{book_id}/chapters`
- **Auth Required**: Yes

**Request Body**:
```json
{
  "name": "Gone with the Scooter",
  "chapter_number": 1,
  "start_page": 11,
  "end_page": 26
}
```

**Response (`201 Created`)**:
```json
{
  "id": "4550c9d0-eb6c-41f4-bb8a-286101dcbec4",
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "name": "Gone with the Scooter",
  "chapter_number": 1,
  "start_page": 11,
  "end_page": 26,
  "created_at": "2026-08-24T10:20:00.000000Z",
  "updated_at": "2026-08-24T10:20:00.000000Z"
}
```

---

#### 5.2 List Chapters in Book
- **Method**: `GET`
- **Endpoint**: `/books/{book_id}/chapters`
- **Auth Required**: Yes

---

#### 5.3 Update Chapter Page Range
- **Method**: `PUT`
- **Endpoint**: `/chapters/{chapter_id}`
- **Auth Required**: Yes

**Request Body**:
```json
{
  "name": "Gone with the Scooter (Revised)",
  "chapter_number": 1,
  "start_page": 11,
  "end_page": 28
}
```

---

### Section 6: Educational Documents (Textbooks/Syllabus PDFs)

#### 6.1 Upload Textbook Document
- **Method**: `POST`
- **Endpoint**: `/books/{book_id}/documents/upload`
- **Auth Required**: Yes
- **Content-Type**: `multipart/form-data`
- **Purpose**: Uploads PDF or PPTX file. Triggers background text extraction, OCR fallback, chapter auto-detection, paragraph chunking, and 768-dim Gemini vector embedding.

**Form Parameters**:
- `file`: PDF or PPTX file binary (`required`).

**Response (`202 Accepted`)**:
```json
{
  "id": "7f2a1b90-884c-490b-b1a9-994f2910c4d8",
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "filename": "santoor_textbook.pdf",
  "mime_type": "application/pdf",
  "file_size": 2450192,
  "status": "PROCESSING",
  "error_message": null,
  "created_at": "2026-08-24T10:25:00.000000Z"
}
```

---

#### 6.2 Get Document Processing Status
- **Method**: `GET`
- **Endpoint**: `/documents/{document_id}`
- **Auth Required**: Yes
- **Purpose**: Polling endpoint to check if document status transitioned from `PROCESSING` to `COMPLETED` or `FAILED`.

**Response (`200 OK`)**:
```json
{
  "id": "7f2a1b90-884c-490b-b1a9-994f2910c4d8",
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "filename": "santoor_textbook.pdf",
  "mime_type": "application/pdf",
  "file_size": 2450192,
  "status": "COMPLETED",
  "error_message": null,
  "created_at": "2026-08-24T10:25:00.000000Z"
}
```

---

#### 6.3 Preview Document File
- **Method**: `GET`
- **Endpoint**: `/documents/{document_id}/preview`
- **Auth Required**: Yes
- **Returns**: File stream with `Content-Disposition: inline`.

---

#### 6.4 Download Document File
- **Method**: `GET`
- **Endpoint**: `/documents/{document_id}/download`
- **Auth Required**: Yes
- **Returns**: File attachment download stream.

---

### Section 7: Reference Exam Papers (Past Papers / Question Banks)

#### 7.1 Upload Reference Paper PDF
- **Method**: `POST`
- **Endpoint**: `/subjects/{subject_id}/reference-papers/upload`
- **Auth Required**: Yes
- **Content-Type**: `multipart/form-data`
- **Purpose**: Uploads past exam paper PDF to serve as a structure/blueprint reference during paper generation.

**Form Parameters**:
- `file`: PDF file binary (`required`).
- `title`: String (`required`, e.g. "Final Exam 2024").
- `year`: Integer (`optional`, e.g. `2024`).
- `exam_type`: String (`optional`, e.g. `FINAL`).

**Response (`201 Created`)**:
```json
{
  "id": "b8cef379-e7d2-4ef8-8e7c-0a61d5de60cc",
  "workspace_id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "subject_id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
  "title": "Final Exam 2024",
  "year": 2024,
  "exam_type": "FINAL",
  "original_filename": "past_paper_2024.pdf",
  "stored_path": "/app/storage/reference_papers/b8cef379.../original.pdf",
  "mime_type": "application/pdf",
  "file_size": 1204850,
  "created_at": "2026-08-24T10:30:00.000000Z",
  "updated_at": "2026-08-24T10:30:00.000000Z"
}
```

---

#### 7.2 List Reference Papers in Subject
- **Method**: `GET`
- **Endpoint**: `/subjects/{subject_id}/reference-papers`
- **Auth Required**: Yes

---

### Section 8: Paper Generation (Custom & Reference Modes)

#### 8.1 Generate Exam Paper
- **Method**: `POST`
- **Endpoint**: `/papers/generate`
- **Auth Required**: Yes
- **Purpose**: Triggers AI paper generation, RAG context retrieval, difficulty distribution calculation, bloom's taxonomy enforcement, and optional answer key generation.

---

##### Request Schema Fields Breakdown

| Parameter | Type | Required? | Description |
| :--- | :--- | :--- | :--- |
| `book_id` | UUID | **Yes** | Authoritative textbook source ID containing grounding material. |
| `selected_chapter_ids` | Array[UUID] | **Yes** | Array of chapter UUIDs selected to ground questions. |
| `generation_mode` | Enum String | **Yes** | `"CUSTOM"` or `"REFERENCE"`. |
| `total_marks` | Integer | **Yes** | Total paper marks (must equal sum of section marks). |
| `difficulty` | Enum String | **Yes** | `"EASY"`, `"MEDIUM"`, or `"HARD"`. |
| `topic_focus` | String | *Optional* | Specific topic emphasis (e.g. `"Scooter ride and safety"`). |
| `include_answers` | Boolean | **Yes** | If `false`, answer key fields (`correct_answer`, `expected_answer`, `solution_explanation`) are set to `null` while **`mcq_options` are preserved**. |
| `reference_paper_id` | UUID | Required if `mode=REFERENCE` | ID of uploaded reference paper to mirror structure from. |
| `question_configs` | Array[Object] | Required if `mode=CUSTOM` | Section blueprint configs. Optional in `REFERENCE` mode (auto-extracted if omitted). |

##### `question_configs` Object Fields

| Field | Type | Required? | Description |
| :--- | :--- | :--- | :--- |
| `question_type` | Enum String | **Yes** | `"MCQ"`, `"VERY_SHORT_ANSWER"`, `"SHORT_ANSWER"`, `"LONG_ANSWER"`, `"NUMERICAL"`. |
| `question_count` | Integer | **Yes** | Number of main questions in this section. |
| `marks_per_question` | Integer | **Yes** | Marks awarded per question. |
| `alternatives_per_question` | Integer | *Optional* | Alternatives per question for internal choice (defaults to `1` = no internal choice; `2` = Q(a) OR Q(b)). |

| `enable_numerical_percentage` | Boolean | *Optional* | Set `true` to generate a specific percentage of numerical questions in each section. Default `false`. |
| `numerical_percentage` | Integer | *Optional* | Percentage (1-100%) of questions in each section that should be numerical problems (required when `enable_numerical_percentage` is `true`). |

---

##### Example Payload 1: CUSTOM Mode Request Body
```json
{
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "selected_chapter_ids": [
    "4550c9d0-eb6c-41f4-bb8a-286101dcbec4"
  ],
  "generation_mode": "CUSTOM",
  "total_marks": 10,
  "difficulty": "HARD",
  "topic_focus": null,
  "include_answers": true,
  "enable_numerical_percentage": true,
  "numerical_percentage": 20,
  "question_configs": [
    {
      "question_type": "MCQ",
      "question_count": 3,
      "marks_per_question": 1,
      "alternatives_per_question": 1
    },
    {
      "question_type": "VERY_SHORT_ANSWER",
      "question_count": 2,
      "marks_per_question": 1,
      "alternatives_per_question": 1
    },
    {
      "question_type": "SHORT_ANSWER",
      "question_count": 1,
      "marks_per_question": 2,
      "alternatives_per_question": 1
    },
    {
      "question_type": "LONG_ANSWER",
      "question_count": 1,
      "marks_per_question": 3,
      "alternatives_per_question": 2
    }
  ]
}
```

##### Example Payload 2: REFERENCE Mode Request Body
```json
{
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "selected_chapter_ids": [
    "4550c9d0-eb6c-41f4-bb8a-286101dcbec4"
  ],
  "generation_mode": "REFERENCE",
  "reference_paper_id": "b8cef379-e7d2-4ef8-8e7c-0a61d5de60cc",
  "total_marks": 10,
  "difficulty": "HARD",
  "topic_focus": "Scooter journey and market events",
  "include_answers": false,
  "question_configs": null
}
```

---

##### Response (`201 Created`)
```json
{
  "id": "dc977ff0-68fc-4cfa-9310-449e7eeef3ff",
  "workspace_id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "subject_id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "reference_paper_id": null,
  "title": "Custom Exam Paper (10 Marks)",
  "generation_mode": "CUSTOM",
  "status": "COMPLETED",
  "total_marks": 10,
  "difficulty": "HARD",
  "topic_focus": null,
  "selected_chapter_ids": [
    "4550c9d0-eb6c-41f4-bb8a-286101dcbec4"
  ],
  "include_answers": true,
  "blueprint_json": {
    "total_marks": 10,
    "sections": [
      {
        "name": "Section A",
        "question_type": "MCQ",
        "question_count": 3,
        "marks_per_question": 1,
        "total_section_marks": 3,
        "has_internal_choice": false,
        "alternatives_per_question": 1
      },
      {
        "name": "Section B",
        "question_type": "SHORT_ANSWER",
        "question_count": 2,
        "marks_per_question": 2,
        "total_section_marks": 4,
        "has_internal_choice": false,
        "alternatives_per_question": 1
      },
      {
        "name": "Section C",
        "question_type": "LONG_ANSWER",
        "question_count": 1,
        "marks_per_question": 3,
        "total_section_marks": 3,
        "has_internal_choice": false,
        "alternatives_per_question": 1
      }
    ]
  },
  "error_message": null,
  "questions": [
    {
      "id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
      "question_order": 1,
      "section_name": "Section A",
      "question_type": "MCQ",
      "question_text": "Based on the story, what sequence of events explains why the scooter ended up speeding through the market without a rider?",
      "marks": 1,
      "difficulty": "HARD",
      "source_type": "AI_GENERATED",
      "choice_group": null,
      "alternative_label": null,
      "mcq_options": [
        "A. Keshav's uncle forgot his helmet at home...",
        "B. Keshav's uncle forgot his wallet at the market, returned home to fetch it, left the engine idling outside a shop, and a small boy twisted the accelerator handle.",
        "C. Keshav's uncle ran out of fuel...",
        "D. Keshav's uncle stopped to buy vegetables..."
      ],
      "correct_answer": "B. Keshav's uncle forgot his wallet at the market, returned home to fetch it, left the engine idling outside a shop, and a small boy twisted the accelerator handle.",
      "expected_answer": null,
      "numerical_values": null,
      "solution_explanation": "According to the text, Uncle realized he forgot his wallet, rode back, left the engine running while stepping into a store, and a child twisted the accelerator.",
      "unit": null
    },
    {
      "id": "2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e",
      "question_order": 4,
      "section_name": "Section B",
      "question_type": "SHORT_ANSWER",
      "question_text": "How did Uncle's decision to leave the engine idling directly cause the chain of events that disrupted the market, and what brought the runaway scooter to a stop?",
      "marks": 2,
      "difficulty": "HARD",
      "source_type": "AI_GENERATED",
      "choice_group": null,
      "alternative_label": null,
      "mcq_options": null,
      "correct_answer": null,
      "expected_answer": "Leaving the engine idling allowed a curious child standing nearby to twist the accelerator handle... stopped when it crashed into a mound of soft sand.",
      "numerical_values": null,
      "solution_explanation": "Explains cause-and-effect: idling engine -> child twisting accelerator -> market chaos -> soft sand mound.",
      "unit": null
    }
  ],
  "created_at": "2026-08-24T10:35:00.000000Z",
  "updated_at": "2026-08-24T10:35:00.000000Z"
}
```

---

#### 8.2 List Generated Papers
- **Method**: `GET`
- **Endpoint**: `/papers`
- **Auth Required**: Yes
- **Query Parameters**:
  - `workspace_id`: UUID (`optional`, filter by workspace).
  - `subject_id`: UUID (`optional`, filter by subject).

---

#### 8.3 Get Paper Details
- **Method**: `GET`
- **Endpoint**: `/papers/{paper_id}`
- **Auth Required**: Yes
- **Query Parameters**:
  - `include_answers`: Boolean (`optional`, default `true`). If set to `false`, strips answer key values while retaining `mcq_options`.

---

#### 8.4 Delete Generated Paper
- **Method**: `DELETE`
- **Endpoint**: `/papers/{paper_id}`
- **Auth Required**: Yes

---

### Section 9: AI Educational Assistant & RAG Query

#### 9.1 Execute Educational RAG Query
- **Method**: `POST`
- **Endpoint**: `/ai/query`
- **Auth Required**: Yes
- **Purpose**: Enables interactive Q&A against course textbook content. Returns verified textual answers, source citations, and rendered visual charts/diagrams (SVG format).

**Request Body**:
```json
{
  "workspace_id": "509f0ddf-2360-496b-9f35-d0e2c407c5c1",
  "query": "Explain why the scooter started running without a rider and draw a flow diagram of the event sequence.",
  "subject_id": "1ea2a5bd-320d-4529-9576-ca94036d58fa",
  "book_id": "95b10b9f-1346-4a75-af03-4ee2c24d6e29",
  "chapter_id": "4550c9d0-eb6c-41f4-bb8a-286101dcbec4",
  "document_id": null,
  "top_k": 5
}
```

**Response (`200 OK`)**:
```json
{
  "answer": "The scooter started running without a rider because Keshav's uncle forgot his wallet and left the engine idling outside a shop. A curious small boy twisted the accelerator handle, launching the vehicle forward...",
  "visuals": [
    {
      "id": "e9a01f82-410c-4b5d-9a8b-123456789abc",
      "type": "flowchart",
      "format": "svg",
      "title": "Runaway Scooter Event Sequence",
      "content": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"600\" height=\"200\">...</svg>",
      "caption": "Figure 1: Sequence of events leading to market disruption."
    }
  ],
  "model_used": "gemini-3.5-flash-lite",
  "sources": [
    {
      "chunk_id": "8f7e6d5c-4b3a-2109-8765-43210fedcba9",
      "document_id": "7f2a1b90-884c-490b-b1a9-994f2910c4d8",
      "page_number": 14,
      "chapter_id": "4550c9d0-eb6c-41f4-bb8a-286101dcbec4",
      "distance": 0.14205
    }
  ]
}
```

---

#### 9.2 Get Generated Visual SVG Artifact
- **Method**: `GET`
- **Endpoint**: `/ai/visuals/{visual_id}`
- **Auth Required**: Yes
- **Returns**: Raw SVG image (`image/svg+xml`) ready for display in `<img>` tags or inline renderers.

---

### Section 10: System Health Checks

#### 10.1 Basic Server Health Check
- **Method**: `GET`
- **Endpoint**: `/health`
- **Auth Required**: No

**Response (`200 OK`)**:
```json
{
  "status": "ok",
  "service": "ai-paper-generator-backend"
}
```

---

#### 10.2 Database & Storage Health Check
- **Method**: `GET`
- **Endpoint**: `/health/db`
- **Auth Required**: No

**Response (`200 OK`)**:
```json
{
  "status": "healthy",
  "database": "connected",
  "pgvector": "active"
}
```

---

## 5. Frontend Integration Workflow Guide

Here is the exact step-by-step UI workflow for building a frontend client:

```
[1. User Login] -> Save JWT token in localStorage / SecureStore
     │
[2. Select or Create Workspace] -> POST /workspaces
     │
[3. Create Subject & Book] -> POST /subjects, POST /books
     │
[4. Upload Textbook PDF] -> POST /books/{book_id}/documents/upload
     │                      Poll GET /documents/{id} until status = "COMPLETED"
     │
[5. Auto-Detect / Select Chapters] -> GET /books/{book_id}/chapters
     │
[6. Configure & Generate Exam Paper] -> POST /papers/generate
     │
[7. Render Exam Paper UI]
     ├── Student Mode (include_answers: false) -> Display questions & mcq_options
     └── Teacher Answer Key (include_answers: true) -> Display correct_answer & solution_explanation
```

---

### Key Takeaways for Frontend Developers

1. **Header Authorization**: Always include `Authorization: Bearer <token>` for all requests except `/auth/login` and `/auth/register`.
2. **Student vs Teacher Paper Views**:
   - For **Student Test Mode**, set `"include_answers": false`. The API will return `mcq_options` so the student can select an answer, while stripping `correct_answer` and `solution_explanation`.
   - For **Teacher Answer Key Mode**, set `"include_answers": true` or fetch `GET /papers/{id}?include_answers=true`.
3. **Internal Choices Layout**:
   - Questions with internal choice will have non-null `choice_group` (e.g. `1`) and `alternative_label` (e.g. `"OR"` or `"Alternative A"` / `"Alternative B"`).
   - Display these questions grouped together with an `"OR"` divider between alternatives.
4. **Document Uploading**:
   - File upload endpoints (`/documents/upload` and `/reference-papers/upload`) use `FormData`.
   - Do NOT set `Content-Type: application/json` header manually when uploading files; let Axios/Fetch set the multipart boundary automatically.
