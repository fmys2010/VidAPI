"""Main API router assembly."""

from fastapi import APIRouter

from .routes import router as tasks_router
from .streaming import router as streaming_router
from .cookies import router as cookies_router
from .system import router as system_router
from .config import router as config_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(tasks_router)
api_router.include_router(streaming_router)
api_router.include_router(cookies_router)
api_router.include_router(system_router)
api_router.include_router(config_router)