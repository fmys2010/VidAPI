"""Shared fixtures for integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from vidapi.core.config import Config
from vidapi.db.database import Database
from vidapi.main import create_app
from vidapi.task_manager import TaskManager


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test artifacts (alias for tmp_dir)."""
    return tmp_path


@pytest.fixture
def config_file(tmp_dir: Path) -> Path:
    """A writable config.json path."""
    cfg = tmp_dir / "config.json"
    cfg.write_text(json.dumps(Config.DEFAULT_CONFIG), encoding="utf-8")
    return cfg


@pytest.fixture
def config(config_file: Path) -> Config:
    """Fresh Config backed by a temp file."""
    return Config(config_path=config_file)


@pytest_asyncio.fixture
async def temp_db(tmp_path: Path) -> AsyncGenerator[Database, None]:
    """Database that persists across fixture scope."""
    db_path = tmp_path / "temp_db.sqlite3"
    db = Database(db_path=db_path)
    await db.init()
    yield db
    await db.close()
    db_path.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def database(temp_db: Database) -> AsyncGenerator[Database, None]:
    """Initialized database (uses temp_db)."""
    yield temp_db


@pytest_asyncio.fixture
async def task_manager(database: Database, config: Config) -> AsyncGenerator[TaskManager, None]:
    """TaskManager with temp DB and config."""
    with patch("vidapi.task_manager.get_config", return_value=config):
        tm = TaskManager(database)
        tm.config = config
        # Use a small executor for tests
        from concurrent.futures import ThreadPoolExecutor

        tm.executor = ThreadPoolExecutor(max_workers=2)
        tm._progress_queues = {}
        tm._download_sessions = {}
        await tm.start()
        yield tm
        await tm.stop()
        tm.executor.shutdown(wait=False)


@pytest_asyncio.fixture
async def app(config: Config, database: Database, task_manager: TaskManager) -> FastAPI:
    """Create a real FastAPI app with test dependencies."""
    # Patch the global instances
    import vidapi.main as main_module

    original_task_manager = main_module._task_manager
    original_database = main_module._database

    main_module._task_manager = task_manager
    main_module._database = database

    # Create app with test lifespan
    app = create_app()

    # Manually run startup
    await task_manager.start()

    yield app

    # Cleanup
    await task_manager.stop()
    main_module._task_manager = original_task_manager
    main_module._database = original_database


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def streaming_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for SSE streaming tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _mock_download_session_global():
    """Autouse: replace vidapi.task_manager.DownloadSession with a fast mock
    so tests that go through POST /tasks never hit the real yt-dlp / network.

    Known sites (YouTube/BiliBili) succeed. Unknown hosts raise
    UnsupportedSiteError so run_download's except branch records
    state=failed with an "unsupported" message — matching what the real
    DownloadSession does for sites the format selector can't reach.

    Tests that need a specific DownloadSession override this with their own
    `with patch("vidapi.task_manager.DownloadSession") as ...:` block, which
    takes precedence for the duration of the with-statement."""
    from vidapi.core.url_utils import classify_site

    class UnsupportedSiteError(Exception):
        pass

    def _factory(urls=None, **kwargs):
        session = MagicMock()
        session.cancel = MagicMock()
        session.format_selector = "bv*+ba/b"
        session._cancel_requested = False
        first_url = (urls or [None])[0]
        site = classify_site(first_url) if first_url else "youtube"
        if site in ("Youtube", "BiliBili"):
            session.run = MagicMock(return_value=(1, 0, 0))
        else:
            session.run = MagicMock(
                side_effect=UnsupportedSiteError(f"Unsupported site: {first_url}")
            )
        return session

    with patch("vidapi.task_manager.DownloadSession", side_effect=_factory):
        yield


@pytest.fixture
def mock_download_session() -> MagicMock:
    """Mock DownloadSession that simulates a successful download."""
    session = MagicMock()
    # run() is called in executor, so it must be sync and return tuple directly
    session.run = MagicMock(return_value=(1, 0, 0))  # success=1, failed=0, skipped=0
    session.cancel = MagicMock()
    session.format_selector = "bv*+ba/b"
    session._cancel_requested = False
    return session


@pytest.fixture
def mock_successful_download() -> MagicMock:
    """Alias for mock_download_session (some tests use this name)."""
    session = MagicMock()
    session.run = MagicMock(return_value=(1, 0, 0))
    session.cancel = MagicMock()
    session.format_selector = "bv*+ba/b"
    session._cancel_requested = False
    return session


@pytest.fixture
def mock_failed_download_session() -> MagicMock:
    """Mock DownloadSession that simulates a failed download."""
    session = MagicMock()
    session.run = MagicMock(return_value=(0, 1, 0))  # success=0, failed=1, skipped=0
    session.cancel = MagicMock()
    session._cancel_requested = False
    return session


@pytest.fixture
def mock_ytdlp_success():
    """Mock yt_dlp module to simulate successful downloads."""
    with patch.dict("sys.modules", {"yt_dlp": MagicMock()}):
        mock_ytdlp = MagicMock()
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            "id": "test123",
            "title": "Test Video",
            "duration": 100,
            "formats": [],
            "requested_formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "height": 1080,
                    "vcodec": "avc1",
                    "acodec": "none",
                },
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "height": None,
                    "vcodec": "none",
                    "acodec": "mp4a",
                },
            ],
        }
        mock_ydl.download = MagicMock()
        mock_ytdlp.YoutubeDL.return_value.__enter__.return_value = mock_ydl

        with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
            yield mock_ytdlp


@pytest.fixture
def mock_ytdlp_failure():
    """Mock yt_dlp module to simulate download failures."""
    with patch.dict("sys.modules", {"yt_dlp": MagicMock()}):
        mock_ytdlp = MagicMock()
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Video unavailable")
        mock_ydl.download.side_effect = Exception("Video unavailable")
        mock_ytdlp.YoutubeDL.return_value.__enter__.return_value = mock_ydl

        with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
            yield mock_ytdlp


@pytest.fixture
def sample_youtube_url() -> str:
    """Sample YouTube URL for testing."""
    return "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def sample_bilibili_url() -> str:
    """Sample BiliBili URL for testing."""
    return "https://www.bilibili.com/video/BV1xx4y1XX77"


@pytest.fixture
def valid_cookie_header() -> str:
    """Valid BiliBili cookie header for testing."""
    return "SESSDATA=abc123; bili_jct=xyz789; DedeUserID=123456"


class MockDownloadSession:
    """A mock DownloadSession that can be controlled for testing."""

    def __init__(
        self,
        urls: list[str],
        success_count: int = 1,
        fail_count: int = 0,
        skip_count: int = 0,
        delay: float = 0.01,
        should_cancel: bool = False,
    ):
        self.urls = urls
        self.success_count = success_count
        self.fail_count = fail_count
        self.skip_count = skip_count
        self.delay = delay
        self.should_cancel = should_cancel
        self._cancel_requested = False
        self.progress_callback = None
        self.log_callback = None
        self.format_selector = "bv*+ba/b"

    @property
    def _cancel_requested(self) -> bool:
        return self._cancel_requested

    @_cancel_requested.setter
    def _cancel_requested(self, value: bool):
        self._cancel_requested = value

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        import time

        total = len(self.urls)
        for i, url in enumerate(self.urls):
            if self._cancel_requested:
                return (0, 0, total - i)

            # Simulate progress updates
            if self.progress_callback:
                for p in [10, 30, 50, 70, 90, 100]:
                    if self._cancel_requested:
                        return (0, 0, total - i)
                    self.progress_callback(p, f"Downloading {url}... {p}%")
                    time.sleep(self.delay)

            if self.log_callback:
                self.log_callback(f"Processing {url}")

            time.sleep(self.delay)

        return (self.success_count, self.fail_count, self.skip_count)

    def set_callbacks(self, progress_cb, log_cb):
        self.progress_callback = progress_cb
        self.log_callback = log_cb


@pytest.fixture
def mock_download_session_factory():
    """Factory for creating controlled MockDownloadSession instances."""

    def _factory(
        urls: list[str],
        success_count: int = 1,
        fail_count: int = 0,
        skip_count: int = 0,
        delay: float = 0.01,
    ) -> MockDownloadSession:
        return MockDownloadSession(
            urls=urls,
            success_count=success_count,
            fail_count=fail_count,
            skip_count=skip_count,
            delay=delay,
        )

    return _factory
