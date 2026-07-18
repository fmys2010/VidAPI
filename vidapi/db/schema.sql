-- vidapi database schema

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
    quality        TEXT,
    subtitle_language TEXT,
    embed_subtitles INTEGER DEFAULT 1,
    site           TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);