"""Synchronous download and cookie sessions for Video Downloader.

Replaces the threaded ``DownloaderWorker`` and ``BilibiliCookieWorker`` with
synchronous sessions that drive progress through callbacks.
No ``threading`` or ``queue`` imports in the session classes — the caller
decides how (and whether) to run these sessions.

Public API
----------
* ``QueueLogger`` — dropped-in replacement for the app.py version.
* ``DownloadSession`` — ``run()`` → ``(success, failed, skipped)``.
* ``CookieSession``  — ``run()`` → calls callbacks directly.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse

from vidapi.core.cookie_utils import (
    BILIBILI_COOKIE_CANDIDATES,
    inspect_bilibili_cookie_jar,
    verify_bilibili_cookie_jar,
)
from vidapi.core.format_utils import (
    DOWNLOAD_MODE_AUDIO_ONLY,
    describe_selected_formats,
    quality_to_height,
    build_format_selector,
    build_subtitle_opts,
    selected_video_height,
)
from vidapi.core.system_utils import format_bytes, format_eta, get_ffmpeg_location
from vidapi.core.url_utils import classify_site


# ---------------------------------------------------------------------------
# QueueLogger — copied from app.py:503-521 unchanged.
# ---------------------------------------------------------------------------

# Deno install paths beyond PATH — ~/.deno/bin/deno (unix) is the curl install
# script default; AppData\Local\deno\deno.exe on Windows. Cached on first call.
_DENO_SEARCH_PATHS = (
    "~/.deno/bin/deno",
    "~/.deno/bin/deno.exe",
    "~/Library/Application Support/deno/bin/deno",
    "~/AppData/Local/deno/deno.exe",
)
_deno_cache: str | None | bool = False


def _find_deno() -> str | None:
    """Locate the Deno executable. Returns its path or None."""
    global _deno_cache
    if _deno_cache is not False:
        return _deno_cache if _deno_cache else None
    path_on_path = shutil.which("deno")
    if path_on_path:
        _deno_cache = path_on_path
        return path_on_path
    for candidate in _DENO_SEARCH_PATHS:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            _deno_cache = expanded
            return expanded
    _deno_cache = None
    return None


class QueueLogger:
    def __init__(self, log_callback: Callable[[str], None]):
        self.log_callback = log_callback

    def debug(self, msg):
        # Keep the UI clean. yt-dlp sends many non-actionable debug lines here.
        pass

    def info(self, msg):
        if msg:
            self.log_callback(str(msg))

    def warning(self, msg):
        if msg:
            self.log_callback("警告: " + str(msg))

    def error(self, msg):
        if msg:
            self.log_callback("错误: " + str(msg))


# ---------------------------------------------------------------------------
# Callback type aliases
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]
FoundCallback = Callable[[str, str, str | None, str], None]
DoneCallback = Callable[[bool], None]


# ---------------------------------------------------------------------------
# Download session
# ---------------------------------------------------------------------------

class DownloadSession:
    """Synchronous download session using yt-dlp and callbacks for progress.

    Parameters
    ----------
    urls : list[str]
    base_download_dir : Path
    proxy : str | None
    download_mode : str
    quality_label : str
    bilibili_cookie_spec : tuple[str, ...] | None
    bilibili_cookie_display : str | None
    progress_callback : ProgressCallback
    log_callback : LogCallback
    cookie_header : str | None
        Raw Cookie header for BiliBili (used when bilibili_cookie_spec is not available)
    subtitle_language : str
        Subtitle language preference
    embed_subtitles : bool
        Whether to embed subtitles into video file
    """

    def __init__(
        self,
        urls: list[str],
        base_download_dir: Path,
        proxy: str | None,
        download_mode: str,
        quality_label: str,
        bilibili_cookie_spec: tuple[str, ...] | None,
        bilibili_cookie_display: str | None,
        progress_callback: ProgressCallback,
        log_callback: LogCallback,
        cookie_header: str | None = None,
        subtitle_language: str = "中英双语（优先原生字幕）",
        embed_subtitles: bool = True,
    ):
        self.urls = urls
        self.base_download_dir = base_download_dir
        self.proxy = proxy
        self.download_mode = download_mode
        self.quality_label = quality_label
        self.bilibili_cookie_spec = bilibili_cookie_spec
        self.bilibili_cookie_display = bilibili_cookie_display
        self.cookie_header = cookie_header
        self.subtitle_language = subtitle_language
        self.embed_subtitles = embed_subtitles
        self.format_selector = build_format_selector(download_mode, quality_label)
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self._cancel_requested = False

    def cancel(self) -> None:
        """Signal cancellation before or during ``run()``."""
        self._cancel_requested = True

    # -- public ----------------------------------------------------------------

    def run(self) -> tuple[int, int, int]:
        """Execute downloads synchronously.

        Returns ``(success_count, failed_count, skipped_count)``.
        """
        try:
            import yt_dlp
        except ModuleNotFoundError:
            self.log_callback(
                "缺少依赖 yt-dlp。请运行：python -m pip install -r requirements.txt"
            )
            return (0, 0, 0)

        ffmpeg_location, ffmpeg_error = get_ffmpeg_location()
        total = len(self.urls)
        success_count = 0
        skipped_count = 0
        failed_count = 0

        self.log_callback(f"下载模式: {self.download_mode}")
        if self.download_mode == DOWNLOAD_MODE_AUDIO_ONLY:
            self.log_callback("清晰度: 仅音频模式不使用清晰度选项")
        else:
            self.log_callback(f"清晰度: {self.quality_label}")
        if self.bilibili_cookie_spec:
            self.log_callback(f"B 站 Cookies: 从 {self.bilibili_cookie_display} 读取")
        else:
            self.log_callback("B 站 Cookies: 未获取，B 站高画质可能受限")
        self.log_callback(f"yt-dlp 格式选择器: {self.format_selector}")
        if ffmpeg_error:
            self.log_callback(f"警告: FFmpeg 不可用 - {ffmpeg_error} (音视频合并可能失败)")

        for index, url in enumerate(self.urls, start=1):
            if self._cancel_requested:
                self.log_callback("已取消剩余任务。")
                break

            site = classify_site(url)
            if site is None:
                skipped_count += 1
                self.log_callback(
                    f"[{index}/{total}] 跳过非 BiliBili/Youtube 链接: {url}"
                )
                continue

            target_dir = self.base_download_dir / site
            target_dir.mkdir(parents=True, exist_ok=True)

            # Windows long path support (\\?\ prefix)
            if sys.platform == "win32":
                target_dir_str = str(target_dir.resolve())
                if len(target_dir_str) > 240:
                    target_dir_str = "\\\\?\\" + target_dir_str
            else:
                target_dir_str = str(target_dir)

            self.progress_callback(0.0, f"准备下载到 {target_dir}")

            def hook(d, _idx=index, _url=url, _total=total):
                if self._cancel_requested:
                    raise RuntimeError("用户取消下载")

                status = d.get("status")
                if status == "downloading":
                    downloaded = d.get("downloaded_bytes") or 0
                    total_bytes = d.get("total_bytes") or d.get(
                        "total_bytes_estimate"
                    ) or 0
                    speed = d.get("speed")
                    eta = d.get("eta")
                    filename = Path(d.get("filename") or "").name

                    if total_bytes:
                        percent = max(0.0, min(100.0, downloaded / total_bytes * 100.0))
                    else:
                        percent = 0.0

                    message = (
                        f"{percent:.1f}% | "
                        f"{format_bytes(downloaded)} / {format_bytes(total_bytes)} | "
                        f"{format_bytes(speed)}/s | ETA {format_eta(eta)}"
                    )
                    if filename:
                        message += f" | {filename}"
                    self.progress_callback(percent, message)

                elif status == "finished":
                    filename = Path(d.get("filename") or "").name
                    self.progress_callback(
                        100.0, f"下载完成，正在合并/后处理: {filename}"
                    )

            # ponytail: distinguish "give me one video by id" from "give me the
            # whole playlist". watch?v=ID&list=...&index=N must download only
            # the video identified by v= (yt-dlp noplaylist=True); playlist?list=
            # must download every entry (noplaylist=False). Without this yt-dlp
            # pulls all 49 entries of the underlying playlist even when the URL
            # points at index N — which is the user-reported bug.
            parsed = urlparse(url)
            query_params = dict(parse_qsl(parsed.query))
            is_playlist_url = (
                parsed.path == "/playlist"
                and bool(query_params.get("list"))
            )
            ydl_opts = {
                "format": self.format_selector,
                "outtmpl": str(
                    Path(target_dir_str) / "%(title).200B [%(id)s] [%(format_id)s].%(ext)s"
                ),
                "continuedl": True,
                "retries": 10,
                "windowsfilenames": True,
                "noprogress": True,
                "quiet": True,
                "no_warnings": False,
                "noplaylist": not is_playlist_url,
                # ponytail: ignoreerrors=True makes non-fatal errors (subtitle
                # HTTP 429, postprocessing hiccups) warnings, not DownloadError.
                # Confirmed against yt_dlp/YoutubeDL.py subtitle-fail path:
                # with ignoreerrors=True, yt-dlp calls report_warning() instead
                # of raise DownloadError(). This is the root-cause fix for
                # users whose task fails after video/audio already landed.
                "ignoreerrors": True,
                "logger": QueueLogger(self.log_callback),
                "progress_hooks": [hook],
                # Network timeouts to prevent indefinite hangs
                "socket_timeout": 30,
                "timeout": 30,
                # Limit concurrent fragment downloads for HLS/DASH
                "concurrent_fragment_downloads": 4,
            }

            # Auto-locate Deno so yt-dlp-ejs can solve YouTube nsig challenges
            # even when Deno is not on the user's PATH (common on macOS where
            # ~/.deno/bin is not in the default GUI shell PATH).
            deno_bin = _find_deno()
            if deno_bin:
                ydl_opts["js_runtimes"] = {"deno": {"path": deno_bin}}

            if self.download_mode != DOWNLOAD_MODE_AUDIO_ONLY and self.download_mode != "仅视频（无声音）":
                ydl_opts["merge_output_format"] = "mp4"

            if self.proxy:
                ydl_opts["proxy"] = self.proxy

            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location

            if site == "BiliBili":
                if self.bilibili_cookie_spec:
                    ydl_opts["cookiesfrombrowser"] = self.bilibili_cookie_spec
                elif self.cookie_header:
                    # Use raw cookie header for BiliBili
                    ydl_opts["http_headers"] = {"Cookie": self.cookie_header}

            subtitle_opts = build_subtitle_opts(self.subtitle_language, self.embed_subtitles)
            ydl_opts.update(subtitle_opts)

            # ponytail: detect partial-success recovery. yt-dlp raises
            # DownloadError if a non-fatal step (e.g. subtitle fetch 429, JS
            # runtime warning) happens AFTER the video+audio already landed on
            # disk. We snapshot media files before the call; if any new media
            # file appeared despite the exception, treat this URL as success
            # with a warning instead of marking the whole task failed.
            media_suffixes = (
                ".mp4", ".mkv", ".webm", ".m4a", ".opus", ".mp3",
            ) if self.download_mode != DOWNLOAD_MODE_AUDIO_ONLY else (
                ".m4a", ".opus", ".mp3", ".webm",
            )
            media_before = {
                p.name for p in target_dir.glob("*") if p.suffix.lower() in media_suffixes
            }

            _idx = index
            _url = url
            _total = total

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                selected_summary = describe_selected_formats(info)
                if selected_summary:
                    self.log_callback(selected_summary)
                expected_height = quality_to_height(self.quality_label)
                actual_height = selected_video_height(info)
                if (
                    self.download_mode != DOWNLOAD_MODE_AUDIO_ONLY
                    and expected_height
                    and actual_height
                    and actual_height < expected_height
                ):
                    self.log_callback(
                        f"提示: 实际只拿到 {actual_height}p，低于选择的 "
                        f"{expected_height}p。常见原因是视频本身没有更高清，"
                        "或站点需要登录/VIP Cookies。"
                    )
                success_count += 1
                self.log_callback(f"[{_idx}/{_total}] 完成: {_url}")
            except Exception as exc:
                # Re-raise user-cancel: that is a real cancellation, not a failure.
                if self._cancel_requested:
                    raise
                media_after = {
                    p.name for p in target_dir.glob("*")
                    if p.suffix.lower() in media_suffixes
                }
                new_media = media_after - media_before
                if new_media:
                    self.log_callback(
                        f"警告: yt-dlp 报告错误但媒体文件已落盘，按成功处理: {exc}"
                    )
                    success_count += 1
                    self.log_callback(f"[{_idx}/{_total}] 完成（部分）: {_url}")
                else:
                    failed_count += 1
                    self.log_callback(f"[{_idx}/{_total}] 失败: {_url}\n原因: {exc}")

            # Clean up yt-dlp temp files (merged intermediate files)
            for pattern in ("*.f*.webm", "*.f*.m4a", "*.part", "*.ytdl", "*.tmp"):
                for temp_file in target_dir.glob(pattern):
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass

            time.sleep(0.1)

        self.log_callback(
            f"全部任务结束：成功 {success_count}，失败 {failed_count}，跳过 {skipped_count}"
        )
        return (success_count, failed_count, skipped_count)


# ---------------------------------------------------------------------------
# Cookie session
# ---------------------------------------------------------------------------

# Per-instance cache for extracted cookie jars to avoid re-extraction
# Using a simple dict with max size to prevent unbounded growth
_MAX_COOKIE_JAR_CACHE = 8


class CookieSession:
    """Synchronous BiliBili cookie inspection session. Call run() from
    whatever thread you like.

    Parameters
    ----------
    proxy : str | None
    candidates : list[tuple[str, str, str | None]] | None
    action_label : str
    status_callback : StatusCallback
    found_callback : FoundCallback
    done_callback : DoneCallback
    """

    def __init__(
        self,
        proxy: str | None,
        candidates: list[tuple[str, str, str | None]] | None = None,
        action_label: str = "获取",
        status_callback: StatusCallback | None = None,
        found_callback: FoundCallback | None = None,
        done_callback: DoneCallback | None = None,
    ):
        self.proxy = proxy
        self.candidates = candidates or list(BILIBILI_COOKIE_CANDIDATES)
        self.action_label = action_label
        self.status_callback = status_callback or (lambda _: None)
        self.found_callback = found_callback or (lambda *a: None)
        self.done_callback = done_callback or (lambda _: None)
        # Instance-level bounded cache
        self._cookie_jar_cache: dict[tuple[str, str | None], Any] = {}

    # -- public ----------------------------------------------------------------

    def run(self) -> None:
        """Run the cookie inspection session synchronously.

        Fires ``status_callback``, ``found_callback``, and ``done_callback``.
        """
        try:
            from yt_dlp.cookies import extract_cookies_from_browser
        except ModuleNotFoundError:
            self.done_callback(False)
            return

        fallback: tuple[str, str, str | None, str] | None = None
        self.status_callback(f"正在{self.action_label} B 站 Cookies...")

        for display_name, browser_name, profile in self.candidates:
            self.status_callback(f"正在读取 {display_name} Cookies...")
            cache_key = (browser_name, profile)

            # Try to get cached cookie jar first
            if cache_key in self._cookie_jar_cache:
                self.status_callback(f"{display_name}: 使用缓存的 Cookies")
                cookie_jar = self._cookie_jar_cache[cache_key]
            else:
                try:
                    cookie_jar = extract_cookies_from_browser(
                        browser_name,
                        profile=profile,
                        logger=QueueLogger(self.status_callback),
                    )
                    # Cache the cookie jar for future use (bounded)
                    if len(self._cookie_jar_cache) >= _MAX_COOKIE_JAR_CACHE:
                        # Remove oldest entry
                        oldest = next(iter(self._cookie_jar_cache))
                        del self._cookie_jar_cache[oldest]
                    self._cookie_jar_cache[cache_key] = cookie_jar
                except (OSError, FileNotFoundError, PermissionError, ModuleNotFoundError, ImportError) as exc:
                    self.status_callback(f"{display_name}: 读取 Cookies 失败：{exc}")
                    continue
                except Exception as exc:
                    # Catch-all for unexpected errors from yt-dlp internals
                    self.status_callback(f"{display_name}: 读取 Cookies 失败：{type(exc).__name__}: {exc}")
                    continue

            local = inspect_bilibili_cookie_jar(cookie_jar)
            if not local["has_login_cookie"]:
                missing = ", ".join(local["missing"]) if local["missing"] else "登录 Cookie"
                self.status_callback(
                    f"{display_name}: 找到 {local['count']} 个 B 站 Cookie，"
                    f"但登录态不完整，缺少 {missing}"
                )
                continue

            self.status_callback(
                f"{display_name}: 发现登录 Cookies，正在在线测试..."
            )
            test_result = verify_bilibili_cookie_jar(cookie_jar, self.proxy)
            message = test_result["message"]
            self.status_callback(f"{display_name}: {message}")

            if test_result["ok"] and test_result["online"]:
                self.found_callback(display_name, browser_name, profile, message)
                self.done_callback(True)
                return

            if test_result["ok"] and fallback is None:
                fallback = (display_name, browser_name, profile, message)

        if fallback:
            self.found_callback(*fallback)
            self.done_callback(True)
            return

        self.status_callback(
            "未获取到可用的 B 站 Cookies；请先在浏览器登录 B 站后重试"
        )
        self.done_callback(False)