from fastapi import APIRouter

from app.api.health import router as health_router
from app.assistant.router import router as assistant_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.bibliography.router import router as bibliography_router
from app.citations.router import router as citations_router
from app.export.router import router as exports_router
from app.observability.router import router as observability_router
from app.projects.router import router as projects_router
from app.projects.workspace_router import router as project_workspace_router
from app.rag.router import router as rag_router
from app.security.router import router as admin_router
from app.sources.router import router as sources_router
from app.writing.router import router as writing_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(observability_router)
api_router.include_router(admin_router)
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(bibliography_router)
api_router.include_router(audit_router)
api_router.include_router(citations_router)
api_router.include_router(exports_router)
api_router.include_router(project_workspace_router)
api_router.include_router(sources_router)
api_router.include_router(rag_router)
api_router.include_router(assistant_router)
api_router.include_router(writing_router)
