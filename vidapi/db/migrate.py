"""Database migration runner."""

import aiosqlite


SCHEMA = """
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
"""


async def migrate(db_path: str) -> None:
    """Run database migrations."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def reset_downloading_tasks(db_path: str) -> int:
    """Reset tasks stuck in 'downloading' state to 'failed' on startup."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE tasks SET state = 'failed', error_msg = 'Server restarted, task interrupted', updated_at = CURRENT_TIMESTAMP WHERE state = 'downloading'"
        )
        await db.commit()
        return cursor.rowcount