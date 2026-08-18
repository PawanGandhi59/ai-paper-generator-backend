# AI Paper Generator - Backend Foundation

Clean, production-oriented FastAPI backend foundation, PostgreSQL+pgvector database setup, Alembic migrations, and Docker development environment for an AI-powered educational platform.

> [!IMPORTANT]
> **Current Scope Notice**: AI paper generation, authentication, workspace management, document processing, RAG, and AI integrations are **NOT** implemented yet. This codebase provides the baseline architectural scaffold, configuration, database connectivity, and health check endpoints.

---

## Technical Stack

- **Python**: 3.12
- **Framework**: FastAPI
- **Database**: PostgreSQL 16 with `pgvector` extension (`pgvector/pgvector:pg16`)
- **ORM**: SQLAlchemy 2.x
- **Database Migrations**: Alembic
- **Validation & Settings**: Pydantic v2 & `pydantic-settings`
- **Database Driver**: `psycopg3` (`psycopg[binary]`)
- **Containerization**: Docker & Docker Compose
- **Testing**: `pytest` & `httpx`

---

## Architecture Overview & Principles

The backend architecture enforces strict separation of concerns across application layers:

```text
API Layer (app/api/)
    ↓
Services Layer (app/services/)
    ↓
Repositories Layer (app/repositories/)
    ↓
Database (PostgreSQL + pgvector)
```

### Module Isolation Guidelines
- **AI Services (`app/ai/`)**: Isolated provider abstractions for LLMs, embedding generation, and vector retrieval. AI calls are never made directly inside API routes.
- **Document Processing (`app/document_processing/`)**: Isolated document ingestion, parsing, chunking, and embedding pipelines.
- **Database Logic**: SQL queries and ORM operations are restricted to repositories, keeping routes clean and decoupled.

---

## Project Structure

```text
app/
├── __init__.py
├── main.py                  # FastAPI application instantiation
├── core/
│   ├── __init__.py
│   ├── config.py            # Pydantic BaseSettings loading from .env
│   ├── database.py          # SQLAlchemy 2.0 engine & session factory
│   └── security.py          # Authentication/Security stubs
├── api/
│   ├── __init__.py
│   ├── router.py            # API router (/api/v1 prefix)
│   └── v1/
│       ├── __init__.py
│       └── health.py        # Health & Database check endpoints
├── models/                  # SQLAlchemy ORM models package
├── schemas/                 # Pydantic validation schemas package
├── repositories/            # Data access layer package
├── services/                # Business logic package
├── ai/                      # AI provider abstractions package
├── document_processing/     # Document ingestion and processing package
└── utils/                   # Shared utilities package

tests/
├── __init__.py
└── test_health.py           # Pytest suite for health endpoints

migrations/                  # Alembic migration scripts
├── env.py
├── script.py.mako
└── versions/
    └── 0001_initial_pgvector.py
```

---

## Environment Variables

Configuration settings are loaded dynamically using `pydantic-settings` from `.env`.

| Variable | Description | Default (Dev) |
|---|---|---|
| `APP_NAME` | Application Name | `AI Paper Generator` |
| `APP_ENV` | Running Environment (`development`/`production`) | `development` |
| `DEBUG` | Debug mode toggle | `true` |
| `DATABASE_URL` | SQLAlchemy Connection URL | `postgresql+psycopg://postgres:postgres@db:5432/ai_paper_generator` |
| `JWT_SECRET_KEY` | Secret key for JWT signing | `change-me-secret-key-for-jwt-authentication` |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration time in minutes | `60` |

---

## Prerequisites

- [Docker](https://www.docker.com/) & Docker Compose
- [Python 3.12](https://www.python.org/downloads/) (if running locally outside Docker)

---

## Docker Setup & Execution

### 1. Build and Start All Services
```bash
docker compose up --build
```

### 2. Run Detached (Background)
```bash
docker compose up -d --build
```

### 3. Apply Alembic Database Migrations
Run Alembic migrations inside the running backend container to apply the initial schema and enable `pgvector`:
```bash
docker compose exec backend alembic upgrade head
```

### 4. Inspect Docker Logs
```bash
# Backend logs
docker compose logs -f backend

# PostgreSQL logs
docker compose logs -f db
```

### 5. Stop Containers
```bash
docker compose down
```

> [!WARNING]
> **Data Loss Warning**: Executing `docker compose down -v` will remove the named Docker volume (`postgres_data`) and **permanently delete all development database data**. Use with caution!

---

## Local Development (Without Docker for Backend)

You can run PostgreSQL in Docker while running the FastAPI backend directly on your host machine.

### 1. Start PostgreSQL with pgvector in Docker
```bash
docker compose up -d db
```

### 2. Configure Local Environment Variable
When running FastAPI locally on host machine, change the database host from `db` to `localhost` in your `.env` file:
```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_paper_generator
```

### 3. Create Python Virtual Environment & Install Dependencies
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Run Alembic Migrations Locally
```bash
alembic upgrade head
```

### 5. Start FastAPI Development Server
```bash
uvicorn app.main:app --reload --port 8000
```

---

## Running Tests

Run the test suite using `pytest`:
```bash
pytest
```
Or run pytest within Docker:
```bash
docker compose exec backend pytest
```

---

## API Health Check & Documentation Endpoints

- **Swagger API Documentation UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **OpenAPI Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

| Method | Endpoint | Description | Expected Response |
|---|---|---|---|
| `GET` | `/api/v1/health` | Basic application health check | `{"status": "ok"}` |
| `GET` | `/api/v1/health/db` | Live database connectivity check | `{"status": "ok", "database": "connected"}` |


---

## Future Planned Modules

- **Authentication & User Management**: User registration, login, JWT token auth, workspace isolation.
- **Document Processing**: Ingestion of PDFs/PPTs, chunking strategies, metadata extraction.
- **AI Integrations**: LLM abstractions, embedding generators, retrieval pipelines (RAG).
- **Paper Generator Engine**: Question generation, validation, and layout creation.
