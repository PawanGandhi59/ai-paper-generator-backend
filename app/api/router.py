from fastapi import APIRouter

from app.api.v1.ai import router as ai_router
from app.api.v1.auth import router as auth_router
from app.api.v1.books import router as books_router
from app.api.v1.chapters import router as chapters_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.papers import router as papers_router
from app.api.v1.reference_papers import router as reference_papers_router
from app.api.v1.subjects import router as subjects_router
from app.api.v1.workspaces import router as workspaces_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(workspaces_router)
api_router.include_router(subjects_router)
api_router.include_router(books_router)
api_router.include_router(chapters_router)
api_router.include_router(documents_router)
api_router.include_router(reference_papers_router)
api_router.include_router(papers_router)
api_router.include_router(ai_router, prefix="/ai", tags=["ai"])
