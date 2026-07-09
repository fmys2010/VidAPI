"""Async database layer for vidapi using aiosqlite."""

from __future__ import annotations

import aiosqlite
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite database for task persistence."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            if Path.home().joinpath(".config").exists():
                config_dir = Path.home() / ".config" / "vidapi"
            else:
                config_dir = Path.home() / "AppData" / "Local" / "vidapi"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = config_dir / "tasks.sqlite3"

        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize database connection and schema."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id        TEXT PRIMARY KEY,
                urls           TEXT NOT NULL,
                state          TEXT NOT NULL,
                progress_pct   REAL DEFAULT 0,
                current_file   TEXT,
                error_msg      TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                download_dir   TEXT,
                format_selector TEXT,
                proxy          TEXT,
                cookie_header  TEXT,
                download_mode  TEXT,
                quality        TEXT
            );

            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        """)
        await self._conn.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    # --- Task operations ---

    async def save_task(self, task: dict[str, Any]) -> None:
        """Insert or update a task."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        urls_json = json.dumps(task.get("urls", []), ensure_ascii=False)

        await self._conn.execute(
            """
            INSERT INTO tasks (task_id, urls, state, progress_pct, current_file, error_msg,
                              created_at, updated_at, download_dir, format_selector, proxy,
                              cookie_header, download_mode, quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                urls = excluded.urls,
                state = excluded.state,
                progress_pct = excluded.progress_pct,
                current_file = excluded.current_file,
                error_msg = excluded.error_msg,
                updated_at = excluded.updated_at,
                download_dir = excluded.download_dir,
                format_selector = excluded.format_selector,
                proxy = excluded.proxy,
                cookie_header = excluded.cookie_header,
                download_mode = excluded.download_mode,
                quality = excluded.quality
            """,
            (
                task["task_id"],
                urls_json,
                task.get("state"),
                task.get("progress_pct", 0),
                task.get("current_file"),
                task.get("error_msg"),
                task.get("created_at"),
                task.get("updated_at"),
                task.get("download_dir"),
                task.get("format_selector"),
                task.get("proxy"),
                task.get("cookie_header"),
                task.get("download_mode"),
                task.get("quality"),
            ),
        )
        await self._conn.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get a single task by ID."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        if row:
            return self._row_to_task(row)
        return None

    async def list_tasks(
        self,
        state: str | None = None,
        site: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        query = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []

        if state:
            query += " AND state = ?"
            params.append(state)
        if site:
            query += " AND download_mode LIKE ?"
            params.append(f"%{site}%")

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        cursor = await self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def update_task_state(
        self,
        task_id: str,
        state: str,
        progress_pct: float | None = None,
        current_file: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        """Update task state and optional fields."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        updates = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [state]

        if progress_pct is not None:
            updates.append("progress_pct = ?")
            params.append(progress_pct)
        if current_file is not None:
            updates.append("current_file = ?")
            params.append(current_file)
        if error_msg is not None:
            updates.append("error_msg = ?")
            params.append(error_msg)

        params.append(task_id)

        await self._conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
            params,
        )
        await self._conn.commit()

    async def reset_downloading_tasks(self) -> int:
        """Reset all 'downloading' tasks to 'failed' on startup recovery."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        cursor = await self._conn.execute(
            """
            UPDATE tasks
            SET state = 'failed',
                error_msg = 'Server restarted, task interrupted',
                updated_at = CURRENT_TIMESTAMP
            WHERE state = 'downloading'
            """
        )
        await self._conn.commit()
        return cursor.rowcount

    # --- Config operations ---

    async def save_config(self, key: str, value: str) -> None:
        """Save a config value."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        await self._conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
        await self._conn.commit()

    async def get_config(self, key: str, default: str = "") -> str:
        """Get a config value."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        cursor = await self._conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

    async def get_all_config(self) -> dict[str, str]:
        """Get all config values."""
        if not self._conn:
            raise RuntimeError("Database not initialized")

        cursor = await self._conn.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert database row to task dict."""
        import json
        task = dict(row)
        task["urls"] = json.loads(task["urls"]) if task["urls"] else []
        return task