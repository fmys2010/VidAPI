# PROJECT KNOWLEDGE BASE

**Generated:** 2025-07-09
**Commit:** HEAD
**Branch:** main

## OVERVIEW
vidapi — Standalone FastAPI video download API for BiliBili and YouTube. Extracted from Video Downloader desktop app. Uses yt-dlp + aiosqlite + SSE for progress streaming.

## STRUCTURE
```
vidapi/
├── api/        # REST endpoints (tasks, streaming, cookies, config, system)
├── core/       # Download engine (url_utils, format_utils, cookie_utils, workers, thread_runner)
├── db/         # SQLite persistence (async, WAL mode)
├── models.py   # Pydantic v2 schemas (enums use Chinese labels)
├── task_manager.py  # Orchestration: ThreadPoolExecutor + asyncio queues
└── main.py     # FastAPI app factory + lifespan
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add new API endpoint | `vidapi/api/*.py` | Router per domain; register in `api/__init__.py` |
| Change download logic | `vidapi/core/workers.py` | `DownloadSession.run()` drives yt-dlp |
| Modify format/quality | `vidapi/core/format_utils.py` | `build_format_selector()` |
| Adjust BiliBili cookies | `vidapi/core/cookie_utils.py` | Raw header injection only |
| Change DB schema | `vidapi/db/schema.sql` + `migrate.py` | Tasks + config tables |
| Update config defaults | `vidapi/core/config.py` | Pydantic Settings |
| Task lifecycle | `vidapi/task_manager.py` | State machine + SSE queues |

## CODE MAP
| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `app` | FastAPI | main.py:105 | entry | App factory |
| `TaskManager` | class | task_manager.py:30 | high | Orchestrator |
| `DownloadSession` | class | core/workers.py:120 | high | yt-dlp runner |
| `CookieSession` | class | core/workers.py:400 | med | BiliBili cookie verify |
| `Database` | class | db/database.py:14 | high | Async SQLite |
| `Config` | class | core/config.py:10 | med | Settings |
| `create_task` | fn | api/routes.py:27 | med | POST /tasks |
| `get_task_manager` | fn | main.py:91 | high | DI provider |

## CONVENTIONS
- **Python 3.10+**, type hints everywhere, `from __future__ import annotations`
- **Ruff**: line-length=100, target-version=py310
- **Pydantic v2**: `BaseModel`, `Field`, `field_validator`, enums as `str, Enum`
- **Async boundary**: `ThreadPoolExecutor(max_workers=config.concurrency)` for sync yt-dlp; callbacks via `asyncio.Queue` + `call_soon_threadsafe`
- **State machine**: `pending → downloading → completed/failed/cancelled` (SPEC.md)
- **Chinese labels** in enums (`DownloadMode.AV = "完整视频（画面+声音）"`)
- **Config path**: `~/.config/vidapi/config.json` (Linux) / `%LOCALAPPDATA%/vidapi` (Windows)

## ANTI-PATTERNS (THIS PROJECT)
- No browser cookie extraction (headless server)
- No subprocess wrapper for yt-dlp (loses progress callbacks)
- No global mutable config — use `Config` instance via `get_config()`
- Don't block event loop in download path — always `run_in_executor`
- Don't store cookies in DB — only raw header string in config

## UNIQUE STYLES
- SSE streaming via `sse-starlette` (`/api/v1/tasks/{id}/stream`)
- Task recovery: `downloading` → `failed` on restart with "Server restarted" error
- WAL mode + FKs on SQLite (`PRAGMA journal_mode=WAL`)
- Cookie verification endpoint (`POST /cookies/bilibili` + `GET /status`)

## COMMANDS
```bash
# Dev
./run.sh                    # venv + uvicorn reload
uvicorn vidapi.main:app --reload

# Test
pytest vidapi/tests/ -v

# Lint/Format
ruff check vidapi/
ruff format vidapi/

# Docker
docker-compose up -d
```

## NOTES
- No CI/CD workflows (.github/workflows absent)
- Tests directory empty; pytest config points to `vidapi/tests/`
- SPEC.md is the authoritative design doc — 212 lines, keep in sync
- `requirements.txt` duplicates pyproject deps; prefer pyproject
- FFmpeg via `imageio-ffmpeg` (bundled) or system `ffmpeg`
- Proxy: `HTTP_PROXY`/`HTTPS_PROXY` env or config `proxy` field