"""API routers, all mounted under /api."""

from fastapi import APIRouter

from .auth_routes import router as auth_router
from .system_routes import router as system_router
from .urls_routes import router as urls_router

api_router = APIRouter(prefix="/api")
api_router.include_router(system_router)
api_router.include_router(auth_router)
api_router.include_router(urls_router)

__all__ = ["api_router"]
