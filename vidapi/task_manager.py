"""Task manager for vidapi - orchestrates download tasks with persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from vidapi.core import (
    DownloadSession,
    CookieSession,
    get_ffmpeg_location,
    get_downloads_folder,
    detect_system_proxy,
    build_format_selector,
    classify_site,
    verify_bilibili_cookie_jar,
)
from vidapi.core.config import get_config, Config
from vidapi.db import Database

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages download tasks with thread pool execution and SQLite persistence."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.config = get_config()

        # Thread pool for running synchronous yt-dlp downloads
        self.executor = ThreadPoolExecutor(max_workers=self.config.concurrency)

        # In-memory progress queues for SSE streaming
        self._progress_queues: dict[str, asyncio.Queue] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}

        # Background task for queue cleanup
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Initialize and recover tasks on startup."""
        # Reset stuck downloading tasks
        reset_count = await self.db.reset_downloading_tasks()
        if reset_count:
            logger.info("Reset %d stuck downloading tasks to failed", reset_count)

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_queues())

    async def stop(self) -> None:
        """Shutdown gracefully."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        self.executor.shutdown(wait=True)

    async def _cleanup_queues(self) -> None:
        """Periodically clean up empty progress queues."""
        while True:
            await asyncio.sleep(60)
            to_remove = [
                task_id for task_id, q in self._progress_queues.items()
                if q.empty() and task_id not in self._task_locks
            ]
            for task_id in to_remove:
                del self._progress_queues[task_id]

    def _get_queue(self, task_id: str) -> asyncio.Queue:
        """Get or create progress queue for a task."""
        if task_id not in self._progress_queues:
            self._progress_queues[task_id] = asyncio.Queue()
        return self._progress_queues[task_id]

    # --- Task CRUD ---

    async def create_task(self, request: dict[str, Any]) -> str:
        """Create a new download task."""
        task_id = str(uuid.uuid4())[:8]

        urls = request["urls"]
        download_mode = request.get("download_mode", self.config.download_mode)
        quality = request.get("quality", self.config.quality)
        proxy = request.get("proxy") or self.config.proxy or detect_system_proxy()
        cookie_header = request.get("cookie_header") or self.config.cookie_header

        # Determine download directory
        download_dir = request.get("download_dir") or self.config.download_dir
        if not download_dir:
            download_dir = str(get_downloads_folder())

        # Build format selector
        format_selector = build_format_selector(download_mode, quality)

        # Create task record
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
            "cookie_header": cookie_header,
            "download_mode": download_mode,
            "quality": quality,
        }

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

        await self.db.update_task_state(task_id, "cancelled", "Cancelled by user")
        queue = self._get_queue(task_id)
        await queue.put({"event": "state_change", "data": {"state": "cancelled"}})
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
        queue = self._get_queue(task_id)
        event = {
            "event": "progress",
            "data": {
                "task_id": task_id,
                "progress_pct": progress,
                "message": message,
                "current_file": current_file,
                "state": task["state"],
            },
        }
        await queue.put(event)

    async def log_message(self, task_id: str, message: str) -> None:
        """Emit log message to SSE queue."""
        queue = self._get_queue(task_id)
        event = {"event": "log", "data": {"task_id": task_id, "message": message}}
        await queue.put(event)

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

        queue = self._get_queue(task_id)
        event = {
            "event": "state_change",
            "data": {
                "task_id": task_id,
                "state": new_state,
                "error": error,
            },
        }
        await queue.put(event)

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

        queue = self._get_queue(task_id)
        event = {
            "event": "complete" if success else "error",
            "data": {
                "task_id": task_id,
                "state": new_state,
                "success": success,
                "failed": failed,
                "skipped": skipped,
            },
        }
        await queue.put(event)

        # Cleanup
        self._progress_queues.pop(task_id, None)
        self._task_locks.pop(task_id, None)

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
        cookie_header = task.get("cookie_header")

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
        )

        # Inject cookie header into session if provided
        if cookie_header:
            session.cookie_header = cookie_header

        # Run in executor
        try:
            success, failed, skipped = await loop.run_in_executor(self.executor, session.run)
            await self.complete_task(task_id, success > 0, failed, skipped)
        except asyncio.CancelledError:
            await self.state_change(task_id, "cancelled", "Task cancelled")
        except Exception as e:
            logger.exception("Download task %s failed", task_id)
            await self.state_change(task_id, "failed", str(e))

    async def get_progress_stream(self, task_id: str) -> asyncio.Queue:
        """Get progress queue for SSE streaming."""
        return self._get_queue(task_id)

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