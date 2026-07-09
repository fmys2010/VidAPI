# vidapi Design Specification (Phase 0)

## Task Schema & State Machine

### Task States
```
pending → downloading → completed
              ↓
              ├── failed
              └── cancelled
```

| State | Description | Transitions |
|-------|-------------|-------------|
| `pending` | Task created, not yet started | → `downloading` (on start), → `cancelled` (on cancel before start) |
| `downloading` | Active download in progress | → `completed` (success), → `failed` (error), → `cancelled` (user cancel) |
| `completed` | All URLs downloaded successfully | Terminal |
| `failed` | Download error occurred | Terminal |
| `cancelled` | User requested cancellation | Terminal |

### SQLite Task Table
```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT PRIMARY KEY,
    urls           TEXT NOT NULL,              -- JSON array of strings
    state          TEXT NOT NULL,              -- pending/downloading/completed/failed/cancelled
    progress_pct   REAL DEFAULT 0,
    current_file   TEXT,                       -- filename being downloaded
    error_msg      TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    download_dir   TEXT,
    format_selector TEXT,
    proxy          TEXT,
    cookie_header  TEXT,                       -- Raw Cookie: header string
    download_mode  TEXT,
    quality        TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

**Recovery on restart:** Tasks in `downloading` state → reset to `failed` with `error_msg = "Server restarted, task interrupted"`.

---

## Async Boundary Decision

**Choice:** `ThreadPoolExecutor` + `asyncio.run_in_executor()`

**Rationale:**
- `DownloadSession.run()` and `CookieSession.run()` are synchronous, blocking functions using yt-dlp
- Running them directly in an `async def` endpoint would freeze the event loop
- `run_in_executor()` runs the sync function in a thread pool, returns an awaitable
- Progress callbacks are marshaled via `asyncio.Queue` + `loop.call_soon_threadsafe()`
- Bounded pool size = `Config.concurrency` (default 3), preventing thread exhaustion
- Cancellation works via existing `_cancel_requested` flag in sessions

**Rejected:** Subprocess wrapper — loses callback-driven progress, requires stdout parsing, more code.

---

## API Contracts

### POST /api/v1/tasks
```json
// Request
{
  "urls": ["https://..."],
  "download_mode": "完整视频（画面+声音）",
  "quality": "最佳",
  "proxy": "http://127.0.0.1:7890",
  "cookie_header": "SESSDATA=xxx; bili_jct=yyy"
}

// Response (201)
{
  "task_id": "uuid",
  "state": "pending",
  "progress_pct": 0,
  "created_at": "2024-01-01T00:00:00Z"
}
```

### GET /api/v1/tasks
```json
// Query: ?state=downloading&site=BiliBili
// Response
{
  "tasks": [...],
  "total": 42
}
```

### GET /api/v1/tasks/{task_id}
```json
{
  "task_id": "uuid",
  "urls": [...],
  "state": "downloading",
  "progress_pct": 45.2,
  "current_file": "video.mp4",
  "error_msg": null,
  "created_at": "...",
  "updated_at": "...",
  "download_dir": "/downloads/BiliBili",
  "download_mode": "...",
  "quality": "..."
}
```

### DELETE /api/v1/tasks/{task_id}
- Cancels if `downloading`, deletes record
- Returns 204

### GET /api/v1/tasks/{task_id}/stream
- Server-Sent Events (SSE)
- Events: `progress`, `log`, `state_change`, `complete`, `error`
- Data: JSON matching above fields

### POST /api/v1/cookies/bilibili
```json
// Request
{"cookie_header": "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"}
// Response
{"ok": true, "message": "Cookie header stored"}
```

### GET /api/v1/cookies/bilibili/status
```json
{
  "ok": true,
  "online": true,
  "message": "在线测试成功：用户名 / 大会员"
}
```

### GET /api/v1/system/info
```json
{
  "downloads_folder": "/home/user/Downloads",
  "ffmpeg_available": true,
  "ffmpeg_path": "/usr/bin/ffmpeg",
  "proxy_detected": "http://127.0.0.1:7890",
  "yt_dlp_version": "2024.1.0",
  "platform": "linux"
}
```

### GET /api/v1/config
```json
{
  "download_dir": "",
  "proxy": "",
  "quality": "最佳",
  "download_mode": "完整视频（画面+声音）",
  "concurrency": 3,
  "auto_merge": true
}
```

### PUT /api/v1/config
```json
// Partial update allowed
{"concurrency": 4, "download_dir": "/custom/path"}
```

---

## Cookie Strategy

**Browser extraction removed** — doesn't work on headless servers.

**Replacement:** Raw `Cookie:` header upload via `POST /cookies/bilibili`.

- User copies cookie from browser DevTools → pastes into API
- Server stores header string in config
- `DownloadSession` receives `cookie_header` and injects into yt-dlp via `http_headers` or custom cookiejar

---

## Windows-Specific Functions

| Function | Issue | Resolution |
|----------|-------|------------|
| `get_downloads_folder()` | Uses WinAPI `SHGetKnownFolderPath` | Configurable `download_dir` with fallback to `~/Downloads` |
| `detect_system_proxy()` | Reads Windows registry via `urllib` | Works if env vars set; document limitation |

---

## Concurrency Model

- `ThreadPoolExecutor(max_workers=config.concurrency)`
- One download task per thread
- Cancellation: `session._cancel_requested = True` + `executor.shutdown(wait=False)` on hard cancel
- TaskManager guards in-memory state with `threading.Lock`
- SQLite persistence on every state change (WAL mode for concurrency)

---

## Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `TASK_NOT_FOUND` | 404 | Task ID doesn't exist |
| `INVALID_URL` | 422 | No valid BiliBili/YouTube URLs in input |
| `YTDLP_ERROR` | 500 | yt-dlp raised an exception |
| `COOKIE_INVALID` | 400 | Uploaded cookie header failed verification |
| `CONFIG_INVALID` | 422 | Config validation failed |