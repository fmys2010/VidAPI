"""FastAPI application entry point for vidapi."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    db_path = Path(config.config_path).parent / "tasks.sqlite3"

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
    """Create and configure FastAPI application.

    The web UI has been removed; the FastAPI app serves only the JSON API
    surface (/api/v1/*), an OpenAPI debugger (/docs, /redoc), and a
    /health probe. The user-facing surface is the native Tk GUI launched
    by run.py, which talks to this FastAPI app on localhost.
    """
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
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router)

    @app.get("/")
    async def root_redirect():
        # ponytail: no web UI ships anymore — return a one-line pointer so a
        # stray HTTP request to the root does not 404 with no context.
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("vidapi API. Start the Tk GUI: python run.py\n")

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
