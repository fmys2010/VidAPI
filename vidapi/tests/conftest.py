"""Shared fixtures for vidapi tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from vidapi.core.config import Config
from vidapi.db.database import Database
from vidapi.task_manager import TaskManager


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture()
def config_file(tmp_dir: Path) -> Path:
    """A writable config.json path."""
    cfg = tmp_dir / "config.json"
    cfg.write_text(json.dumps(Config.DEFAULT_CONFIG), encoding="utf-8")
    return cfg


@pytest.fixture()
def config(config_file: Path) -> Config:
    """Fresh Config backed by a temp file."""
    return Config(config_path=config_file)


@pytest.fixture()
def db_file(tmp_dir: Path) -> Path:
    """A writable SQLite path."""
    return tmp_dir / "test.sqlite3"


@pytest.fixture()
async def database(db_file: Path) -> Database:
    """Initialized in-memory-ish database."""
    db = Database(db_path=db_file)
    await db.init()
    yield db
    await db.close()


@pytest.fixture()
async def task_manager(database: Database, config: Config) -> TaskManager:
    """TaskManager with temp DB and config."""
    # Patch get_config to return our test config
    with patch("vidapi.task_manager.get_config", return_value=config):
        tm = TaskManager(database)
        tm.config = config
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._task_locks = {}
        yield tm


@pytest.fixture()
def mock_callbacks() -> dict:
    """Collectors for progress/log callbacks."""
    return {
        "progress": [],
        "log": [],
    }
