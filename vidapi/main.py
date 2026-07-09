"""FastAPI application entry point for vidapi."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vidapi.core import get_config
from vidapi.db import Database
from vidapi.api import api_router
from vidapi.task_manager import TaskManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("vidapi")

# Global instances
_task_manager: TaskManager | None = None
_database: Database | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _task_manager, _database

    # Startup
    logger.info("Starting vidapi...")

    config = get_config()
    db_path = Path(config.config_path).parent / "tasks.sqlite3" if hasattr(config, 'config_path') else None

    _database = Database(db_path)
    await _database.init()

    _task_manager = TaskManager(_database)
    await _task_manager.start()

    logger.info("vidapi started successfully")

    yield

    # Shutdown
    logger.info("Shutting down vidapi...")
    if _task_manager:
        await _task_manager.stop()
    if _database:
        await _database.close()
    logger.info("vidapi stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="vidapi",
        description="Standalone video download API for BiliBili and YouTube",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory="vidapi/static"), name="static")

    # Include API routes
    app.include_router(api_router)

    @app.get("/")
    @app.get("/ui")
    async def serve_ui():
        from fastapi.responses import HTMLResponse
        import os
        ui_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        with open(ui_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "vidapi"}

    return app


def get_task_manager() -> TaskManager:
    """Get the global task manager instance."""
    if _task_manager is None:
        raise RuntimeError("Task manager not initialized")
    return _task_manager


def get_database() -> Database:
    """Get the global database instance."""
    if _database is None:
        raise RuntimeError("Database not initialized")
    return _database


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("vidapi.main:app", host="0.0.0.0", port=8000, reload=True)