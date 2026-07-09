# vidapi/core — Core Download Engine

**OVERVIEW**
Core engine for yt-dlp integration: URL parsing, format selection, BiliBili cookies, system utilities, config, and download workers.

**STRUCTURE**
```
core/
├── url_utils.py        # extract_urls, classify_site, normalize_url
├── format_utils.py     # build_format_selector, quality_to_height, format descriptions
├── cookie_utils.py     # BiliBili cookie candidates, verification, header building
├── system_utils.py     # downloads folder, proxy detection, ffmpeg path, formatters
├── config.py           # Config (Pydantic Settings), get_config() singleton
├── workers.py          # DownloadSession, CookieSession, QueueLogger (yt-dlp runners)
├── thread_runner.py    # AsyncThreadRunner, SessionThreadRunner (executor wrappers)
└── __init__.py         # Re-exports all public symbols (26 items)
```

**WHERE TO LOOK**
| Task | Location |
|------|----------|
| Add new site support | `url_utils.py` (classify_site) |
| Change format/quality logic | `format_utils.py` (build_format_selector) |
| Modify BiliBili cookie handling | `cookie_utils.py` |
| Adjust download concurrency | `config.py` (Config.concurrency) |
| Change yt-dlp progress handling | `workers.py` (DownloadSession.run) |
| Modify thread pool behavior | `thread_runner.py` (AsyncThreadRunner) |

**CONVENTIONS**
- All public functions have type hints
- Chinese labels in enums (`DownloadMode.AV = "完整视频（画面+声音）"`)
- `Config` via `get_config()` singleton — no global mutable config
- Sync yt-dlp calls wrapped in `ThreadPoolExecutor` via `thread_runner`
- Progress callbacks → `asyncio.Queue` + `call_soon_threadsafe`

**ANTI-PATTERNS**
- No browser cookie extraction (headless server)
- No subprocess wrapper for yt-dlp (loses progress callbacks)
- Don't block event loop in download path — always `run_in_executor`
- Don't store cookies in DB — only raw header string in config