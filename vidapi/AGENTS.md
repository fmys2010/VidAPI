# vidapi — Main Package

**Generated:** 2025-07-09
**Score:** 35 — root package, high complexity, central exports

## OVERVIEW
Standalone FastAPI video download API for BiliBili and YouTube. Entry point: `main.py` → `create_app()` → `app`.

## STRUCTURE
```
vidapi/
├── main.py              # FastAPI app factory, lifespan, DI providers
├── models.py            # Pydantic v2 schemas (enums use Chinese labels)
├── task_manager.py      # Orchestrator: ThreadPoolExecutor + asyncio queues + SSE
├── api/                 # REST endpoints (tasks, streaming, cookies, system, config)
├── core/                # Download engine (yt-dlp, formats, cookies, threads)
├── db/                  # Async SQLite persistence (WAL mode)
├── tests/               # Empty — pytest configured but no tests exist
└── __init__.py          # Re-exports 26 public symbols from core + app
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| App entry point | `main.py` (create_app, lifespan, get_task_manager) |
| Task lifecycle | `task_manager.py` (create_task, run_download, cancel, SSE queues) |
| API contracts | `models.py` + `api/routes.py` |
| Download logic | `core/workers.py` (DownloadSession.run) |
| Format/quality | `core/format_utils.py` (build_format_selector) |
| BiliBili cookies | `core/cookie_utils.py` |
| Config defaults | `core/config.py` (Config class) |
| DB schema | `db/schema.sql` |

## CONVENTIONS
- Python 3.10+, type hints everywhere, `from __future__ import annotations`
- Ruff: line-length=100, target-version=py310
- Pydantic v2: `BaseModel`, `Field`, `field_validator`, enums as `str, Enum`
- Async boundary: `ThreadPoolExecutor(max_workers=config.concurrency)` for sync yt-dlp
- State machine: `pending → downloading → completed/failed/cancelled` (SPEC.md)
- Chinese labels in enums (`DownloadMode.AV = "完整视频（画面+声音）"`)
- Config path: `~/.config/vidapi/config.json` (Linux) / `%LOCALAPPDATA%/vidapi` (Windows)

## COMMANDS
```bash
# Dev
./run.sh                          # venv + uvicorn reload
uvicorn vidapi.main:app --reload

# Test
pytest vidapi/tests/ -v

# Lint/Format
ruff check vidapi/
ruff format vidapi/

# Docker
docker-compose up -d
```

## ANTI-PATTERNS (THIS PROJECT)
- No browser cookie extraction (headless server)
- No subprocess wrapper for yt-dlp (loses progress callbacks)
- No global mutable config — use `Config` instance via `get_config()`
- Don't block event loop in download path — always `run_in_executor`
- Don't store cookies in DB — only raw header string in config

## NOTES
- Tasks in `downloading` state → reset to `failed` on restart with "Server restarted" error
- SSE streaming via `sse-starlette` (`/api/v1/tasks/{id}/stream`)
- Cookie verification endpoint (`POST /cookies/bilibili` + `GET /status`)
- FFmpeg via `imageio-ffmpeg` (bundled) or system `ffmpeg`
- Proxy: `HTTP_PROXY`/`HTTPS_PROXY` env or config `proxy` field