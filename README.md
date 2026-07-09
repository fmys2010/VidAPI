# vidapi

Standalone video download API for BiliBili and YouTube, extracted from the Video Downloader desktop application.

## Features

- **REST API** for managing video download tasks
- **SSE streaming** for real-time progress updates
- **BiliBili & YouTube** support via yt-dlp
- **Multiple formats**: Complete video (AV), Video-only, Audio-only
- **Quality selection**: Best, 4K, 2K, 1080p, 720p, 480p, 360p
- **Cookie authentication**: Raw Cookie header upload for BiliBili VIP content
- **Proxy support**: HTTP/SOCKS proxy for YouTube access
- **Persistence**: SQLite with WAL mode for task survival across restarts
- **Concurrency control**: Configurable thread pool

## Quick Start

### Using run.sh (Recommended)

```bash
./run.sh
```

### Manual Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn vidapi.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker-compose up -d
```

## API Endpoints

### Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tasks` | Create download task |
| GET | `/api/v1/tasks` | List tasks (filter by state, site) |
| GET | `/api/v1/tasks/{id}` | Get task details |
| DELETE | `/api/v1/tasks/{id}` | Cancel & delete task |
| POST | `/api/v1/tasks/{id}/cancel` | Cancel running task |
| GET | `/api/v1/tasks/{id}/stream` | SSE progress stream |

### Cookies (BiliBili)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/cookies/bilibili` | Upload raw Cookie header |
| GET | `/api/v1/cookies/bilibili/status` | Verify stored cookie |

### System & Config

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/system/info` | System info (ffmpeg, proxy, etc.) |
| GET | `/api/v1/config` | Get current config |
| PUT | `/api/v1/config` | Update config (partial) |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |

## Usage Examples

### Create Download Task

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    "download_mode": "完整视频（画面+声音）",
    "quality": "1080p"
  }'
```

Response:
```json
{
  "task_id": "a1b2c3d4",
  "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
  "state": "pending",
  "progress_pct": 0.0,
  "created_at": "2024-01-01T00:00:00",
  "download_mode": "完整视频（画面+声音）",
  "quality": "1080p"
}
```

### Stream Progress (SSE)

```bash
curl -N http://localhost:8000/api/v1/tasks/a1b2c3d4/stream
```

Events:
```
event: state_change
data: {"task_id": "a1b2c3d4", "state": "downloading", "progress": 0}

event: progress
data: {"task_id": "a1b2c3d4", "progress_pct": 45.2, "message": "45.2% | 10.5 MB / 23.1 MB | 2.1 MB/s | ETA 0:06", "current_file": "video.mp4"}

event: complete
data: {"task_id": "a1b2c3d4", "state": "completed", "success": true, "failed": 0, "skipped": 0}
```

### Upload BiliBili Cookie

```bash
# Get cookie from browser DevTools (Application > Cookies > bilibili.com)
# Copy SESSDATA, bili_jct, DedeUserID values
curl -X POST http://localhost:8000/api/v1/cookies/bilibili \
  -H "Content-Type: application/json" \
  -d '{"cookie_header": "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"}'
```

### Check Cookie Status

```bash
curl http://localhost:8000/api/v1/cookies/bilibili/status
```

### Update Configuration

```bash
curl -X PUT http://localhost:8000/api/v1/config \
  -H "Content-Type: application/json" \
  -d '{"concurrency": 4, "download_dir": "/custom/path"}'
```

## Download Modes

| Mode | Chinese Label | Description |
|------|---------------|-------------|
| AV | 完整视频（画面+声音） | Best video + best audio, merged |
| VIDEO_ONLY | 仅视频（无声音） | Video stream only |
| AUDIO_ONLY | 仅音频 | Best audio stream |

## Quality Options

| Option | Resolution |
|--------|------------|
| 最佳 | Best available |
| 2160p / 4K | 3840×2160 |
| 1440p / 2K | 2560×1440 |
| 1080p | 1920×1080 |
| 720p | 1280×720 |
| 480p | 854×480 |
| 360p | 640×360 |

## Task States

```
pending → downloading → completed
              ↓
              ├── failed
              └── cancelled
```

## Configuration

Config file: `~/.config/vidapi/config.json`

```json
{
  "download_mode": "完整视频（画面+声音）",
  "quality": "最佳",
  "download_dir": "",
  "proxy": "",
  "concurrency": 3,
  "auto_merge": true,
  "cookie_header": ""
}
```

## Deployment Notes

- **FFmpeg**: Required for audio/video merging (bundled via imageio-ffmpeg)
- **Proxy**: Set `proxy` config or `HTTP_PROXY`/`HTTPS_PROXY` env vars for YouTube
- **Cookies**: BiliBili VIP content requires valid cookie header
- **Persistence**: Tasks survive restarts (SQLite WAL mode)
- **Concurrency**: Controlled by `concurrency` setting (default 3)

## Architecture

```
vidapi/
├── main.py                 # FastAPI app factory
├── models.py               # Pydantic schemas
├── task_manager.py         # Task orchestration + persistence
├── core/                   # Core engine (copied from Video Downloader)
│   ├── url_utils.py        # URL extraction & classification
│   ├── format_utils.py     # yt-dlp format selectors
│   ├── cookie_utils.py     # BiliBili cookie handling
│   ├── system_utils.py     # System utilities (ffmpeg, proxy, paths)
│   ├── config.py           # Configuration management
│   ├── workers.py          # DownloadSession, CookieSession
│   └── thread_runner.py    # Async thread pool wrapper
├── db/                     # Persistence layer
│   ├── database.py         # Async SQLite (aiosqlite)
│   └── schema.sql          # Tables & indexes
├── api/                    # REST endpoints
│   ├── routes.py           # Task CRUD
│   ├── streaming.py        # SSE progress
│   ├── cookies.py          # Cookie management
│   ├── system.py           # System info
│   └── config.py           # Config API
└── tests/                  # Pytest suite
```

## Development

```bash
# Run tests
pytest vidapi/tests/ -v

# Lint
ruff check vidapi/

# Format
ruff format vidapi/
```

## License

MIT