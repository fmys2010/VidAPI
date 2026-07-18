"""Task manager for vidapi - orchestrates download tasks with persistence."""

from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from vidapi.core import (
    DownloadSession,
    get_downloads_folder,
    detect_system_proxy,
    build_format_selector,
    classify_site,
    verify_bilibili_cookie_jar,
)
from vidapi.core.config import get_config
from vidapi.db import Database

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages download tasks with thread pool execution and SQLite persistence."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.config = get_config()

        # Thread pool for running synchronous yt-dlp downloads
        self.executor = ThreadPoolExecutor(max_workers=self.config.concurrency)

        # In-memory progress queues for SSE streaming (per-subscriber queues)
        self._progress_queues: dict[str, dict[str, asyncio.Queue]] = {}
        # Active download sessions for cancellation support
        self._download_sessions: dict[str, DownloadSession] = {}
        # Per-task cookie headers (in-memory only, not persisted to DB)
        self._task_cookie_headers: dict[str, str] = {}

        # Background task for queue cleanup
        self._cleanup_task: asyncio.Task | None = None

        # Strong references to running download tasks (prevents GC)
        self._running_tasks: dict[str, asyncio.Task] = {}

    def subscribe(self, task_id: str) -> tuple[asyncio.Queue, str]:
        """Register a new SSE subscriber for a task; returns its dedicated queue + sub_id."""
        sub_id = str(uuid.uuid4())[:8]
        queue: asyncio.Queue = asyncio.Queue()
        self._progress_queues.setdefault(task_id, {})[sub_id] = queue
        return queue, sub_id

    def unsubscribe(self, task_id: str, sub_id: str) -> None:
        """Drop a single SSE subscriber; if it was the last one, remove the task's entry."""
        subs = self._progress_queues.get(task_id)
        if subs:
            subs.pop(sub_id, None)
            if not subs:
                del self._progress_queues[task_id]

    def _broadcast(self, task_id: str, event: dict[str, Any]) -> None:
        """Push an event to all subscribers' queues for a task."""
        subs = self._progress_queues.get(task_id)
        if not subs:
            return
        for q in list(subs.values()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # queue is unbounded today; safety net if a maxsize is added later

    def _close_stream(self, task_id: str) -> None:
        """Remove all subscriber entries for a task (e.g. after completion)."""
        self._progress_queues.pop(task_id, None)

    def _start_download(self, task_id: str) -> None:
        """Start a download task and hold a strong reference to prevent GC."""
        self._running_tasks[task_id] = asyncio.create_task(self.run_download(task_id))

    async def start(self) -> None:
        """Initialize and recover tasks on startup."""
        # Reset stuck downloading tasks
        reset_count = await self.db.reset_downloading_tasks()
        if reset_count:
            logger.info("Reset %d stuck downloading tasks to failed", reset_count)

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_queues())

    def has_active_downloads(self) -> bool:
        return bool(self._download_sessions)

    async def stop(self) -> None:
        """Shutdown gracefully."""
        # Cancel all running downloads
        for session in self._download_sessions.values():
            session.cancel()
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        self.executor.shutdown(wait=True)
        self._download_sessions.clear()

    async def _cleanup_queues(self) -> None:
        """Periodically clean up empty progress queues."""
        while True:
            await asyncio.sleep(60)
            to_remove = [
                task_id for task_id, subs in self._progress_queues.items()
                if not subs and task_id not in self._download_sessions
            ]
            for task_id in to_remove:
                del self._progress_queues[task_id]

    def _close_stream(self, task_id: str) -> None:
        """Remove all subscriber entries for a task (e.g. after completion)."""
        self._progress_queues.pop(task_id, None)

    def _start_download(self, task_id: str) -> None:
        """Start a download task and keep a strong reference to it."""
        task = asyncio.create_task(self.run_download(task_id))
        self._running_tasks[task_id] = task

    # --- Task CRUD ---

    async def create_task(self, request: dict[str, Any]) -> str:
        """Create a new download task."""
        task_id = str(uuid.uuid4())[:8]

        urls = request["urls"]
        download_mode = request.get("download_mode", self.config.download_mode)
        quality = request.get("quality", self.config.quality)
        proxy = request.get("proxy") or self.config.proxy or detect_system_proxy()
        cookie_header = request.get("cookie_header") or self.config.cookie_header
        subtitle_language = request.get("subtitle_language", "原生")
        embed_subtitles = request.get("embed_subtitles", True)

        # Determine download directory
        download_dir = request.get("download_dir") or self.config.download_dir
        if not download_dir:
            download_dir = str(get_downloads_folder())

        # Build format selector
        format_selector = build_format_selector(download_mode, quality)

        site = classify_site(urls[0]) if urls else None

        # Create task record (cookie_header NOT persisted — stored in-memory for runtime)
        task = {
            "task_id": task_id,
            "urls": urls,
            "state": "pending",
            "progress_pct": 0.0,
            "current_file": None,
            "error_msg": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "download_dir": download_dir,
            "format_selector": format_selector,
            "proxy": proxy,
            "download_mode": download_mode,
            "quality": quality,
            "subtitle_language": subtitle_language,
            "embed_subtitles": embed_subtitles,
            "site": site,
        }

        # Store per-task cookie header in memory for DownloadSession (not in DB)
        self._task_cookie_headers[task_id] = cookie_header

        # Persist to database
        await self.db.save_task(task)

        return task_id

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID."""
        return await self.db.get_task(task_id)

    async def list_tasks(
        self, state: str | None = None, site: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        return await self.db.list_tasks(state=state, site=site, limit=limit, offset=offset)

    async def count_tasks(
        self, state: str | None = None, site: str | None = None
    ) -> int:
        """Count tasks with optional filters."""
        return await self.db.count_tasks(state=state, site=site)

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        await self.cancel_task(task_id)
        return await self.db.delete_task(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running or pending task."""
        task = await self.get_task(task_id)
        if not task:
            return False

        if task["state"] not in ("pending", "downloading"):
            return False

        # Cancel the download session if it's running
        session = self._download_sessions.get(task_id)
        if session:
            session.cancel()

        await self.db.update_task_state(task_id, "cancelled", "Cancelled by user")
        self._broadcast(task_id, {"event": "state_change", "data": {"state": "cancelled"}})
        return True

    # --- Progress tracking ---

    async def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str,
        current_file: str | None = None,
        state: str | None = None,
    ) -> None:
        """Update task progress and emit to SSE queue."""
        task = await self.get_task(task_id)
        if not task:
            return

        task["progress_pct"] = progress
        if current_file:
            task["current_file"] = current_file
        if state:
            task["state"] = state
        task["updated_at"] = datetime.now().isoformat()

        await self.db.save_task(task)

        # Emit to SSE queue
        self._broadcast(task_id, {
            "event": "progress",
            "data": {
                "task_id": task_id,
                "progress_pct": progress,
                "message": message,
                "current_file": current_file,
                "state": task["state"],
            },
        })

    async def log_message(self, task_id: str, message: str) -> None:
        """Emit log message to SSE queue."""
        self._broadcast(task_id, {"event": "log", "data": {"task_id": task_id, "message": message}})

    async def state_change(self, task_id: str, new_state: str, error: str | None = None) -> None:
        """Emit state change event."""
        task = await self.get_task(task_id)
        if not task:
            return

        task["state"] = new_state
        if error:
            task["error_msg"] = error
        task["updated_at"] = datetime.now().isoformat()

        await self.db.save_task(task)

        self._broadcast(task_id, {
            "event": "state_change",
            "data": {
                "task_id": task_id,
                "state": new_state,
                "error": error,
            },
        })

    async def complete_task(
        self,
        task_id: str,
        success: bool,
        failed: int,
        skipped: int,
    ) -> None:
        """Mark task as completed or failed."""
        new_state = "completed" if success else "failed"
        error = None if success else f"Failed: {failed}, Skipped: {skipped}"

        await self.state_change(task_id, new_state, error)

        self._broadcast(task_id, {
            "event": "complete" if success else "error",
            "data": {
                "task_id": task_id,
                "state": new_state,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "error": error,
            },
        })

        # Cleanup
        self._close_stream(task_id)
        self._download_sessions.pop(task_id, None)
        task_ref = self._running_tasks.pop(task_id, None)
        if task_ref and not task_ref.done():
            task_ref.cancel()

    # --- Download execution ---

    async def run_download(self, task_id: str) -> None:
        """Execute download task in thread pool."""
        task = await self.get_task(task_id)
        if not task:
            logger.error("Task %s not found", task_id)
            return

        await self.state_change(task_id, "downloading")

        urls = task["urls"]
        download_dir = Path(task["download_dir"])
        proxy = task.get("proxy")
        download_mode = task["download_mode"]
        quality = task["quality"]
        cookie_header = self._task_cookie_headers.get(task_id)
        subtitle_language = task.get("subtitle_language", "原生")
        embed_subtitles = task.get("embed_subtitles", True)

        bilibili_cookie_spec = None
        bilibili_cookie_display = "手动上传的 Cookie"
        if cookie_header:
            bilibili_cookie_spec = ("manual", cookie_header)

        loop = asyncio.get_running_loop()

        def make_progress_callback(p: float, m: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self.update_progress(task_id, p, m), loop
            )

        def make_log_callback(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(
                self.log_message(task_id, msg), loop
            )

        session = DownloadSession(
            urls=urls,
            base_download_dir=download_dir,
            proxy=proxy,
            download_mode=download_mode,
            quality_label=quality,
            bilibili_cookie_spec=bilibili_cookie_spec,
            bilibili_cookie_display=bilibili_cookie_display,
            progress_callback=make_progress_callback,
            log_callback=make_log_callback,
            subtitle_language=subtitle_language,
            embed_subtitles=embed_subtitles,
        )

        # Store session for cancellation support
        self._download_sessions[task_id] = session

        # Run in executor
        try:
            success, failed, skipped = await loop.run_in_executor(self.executor, session.run)
            await self.complete_task(task_id, success > 0, failed, skipped)
        except asyncio.CancelledError:
            await self.state_change(task_id, "cancelled", "Task cancelled")
            self._cleanup_download(task_id)
        except Exception as e:
            logger.exception("Download task %s failed", task_id)
            await self.state_change(task_id, "failed", str(e))
            self._cleanup_download(task_id)

    def _cleanup_download(self, task_id: str) -> None:
        """Clean up resources for a download task."""
        self._download_sessions.pop(task_id, None)
        self._task_cookie_headers.pop(task_id, None)
        task_ref = self._running_tasks.pop(task_id, None)
        if task_ref and not task_ref.done():
            task_ref.cancel()
        self._close_stream(task_id)

    # --- Cookie verification ---

    async def verify_bilibili_cookie(self, cookie_header: str) -> dict[str, Any]:
        """Verify a manually provided BiliBili cookie header."""
        try:
            import http.cookiejar

            cookie_jar = http.cookiejar.CookieJar()
            for part in cookie_header.split(";"):
                part = part.strip()
                if "=" in part:
                    name, value = part.split("=", 1)
                    cookie = http.cookiejar.Cookie(
                        version=0,
                        name=name.strip(),
                        value=value.strip(),
                        port=None,
                        port_specified=False,
                        domain=".bilibili.com",
                        domain_specified=True,
                        domain_initial_dot=True,
                        path="/",
                        path_specified=True,
                        secure=True,
                        expires=None,
                        discard=True,
                        comment=None,
                        comment_url=None,
                        rest={},
                    )
                    cookie_jar.set_cookie(cookie)

            # Run verification in executor to avoid blocking
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self.executor,
                lambda: verify_bilibili_cookie_jar(cookie_jar, self.config.proxy)
            )
            return result
        except Exception as exc:
            return {"ok": False, "online": False, "message": f"验证失败: {exc}"}

    def classify_site(self, url: str) -> str | None:
        """Classify a URL to BiliBili or YouTube."""
        return classify_site(url)