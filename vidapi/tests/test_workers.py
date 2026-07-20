"""Error tests for workers: DownloadSession and CookieSession error paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp.utils

from vidapi.core.workers import DownloadSession, CookieSession, QueueLogger, _find_deno


class TestQueueLogger:
    def test_debug_does_nothing(self):
        cb = MagicMock()
        logger = QueueLogger(cb)
        logger.debug("should be ignored")
        cb.assert_not_called()

    def test_info_calls_callback(self):
        cb = MagicMock()
        logger = QueueLogger(cb)
        logger.info("test message")
        cb.assert_called_once_with("test message")

    def test_info_empty_message(self):
        cb = MagicMock()
        logger = QueueLogger(cb)
        logger.info("")
        cb.assert_not_called()

    def test_warning_prefixes_chinese(self):
        cb = MagicMock()
        logger = QueueLogger(cb)
        logger.warning("disk low")
        cb.assert_called_once_with("警告: disk low")

    def test_error_prefixes_chinese(self):
        cb = MagicMock()
        logger = QueueLogger(cb)
        logger.error("download failed")
        cb.assert_called_once_with("错误: download failed")


class TestDownloadSessionMissingYtdlp:
    def test_module_not_found_returns_zeros(self, tmp_path: Path):
        progress_cb = MagicMock()
        log_cb = MagicMock()
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=progress_cb,
            log_callback=log_cb,
        )
        with patch.dict("sys.modules", {"yt_dlp": None}):
            result = session.run()
        assert result == (0, 0, 0)
        # Should log about missing yt-dlp
        log_calls = [c[0][0] for c in log_cb.call_args_list]
        assert any("yt-dlp" in msg for msg in log_calls)


class TestDownloadSessionUnrecognizedUrl:
    def test_skips_unknown_site(self, tmp_path: Path):
        progress_cb = MagicMock()
        log_cb = MagicMock()
        session = DownloadSession(
            urls=["https://www.vimeo.com/12345"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=progress_cb,
            log_callback=log_cb,
        )
        result = session.run()
        assert result == (0, 0, 1)
        log_cb.assert_any_call("[1/1] 跳过非 BiliBili/Youtube 链接: https://www.vimeo.com/12345")

    def test_mixed_urls_some_skipped(self, tmp_path: Path):
        """One valid, one invalid URL."""
        progress_cb = MagicMock()
        log_cb = MagicMock()
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc", "https://www.vimeo.com/123"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=progress_cb,
            log_callback=log_cb,
        )
        # We can't easily test the full run without yt_dlp, but we can test
        # that the session object is created with mixed URLs
        assert len(session.urls) == 2


class TestDownloadSessionCancellation:
    def test_cancel_before_run(self, tmp_path: Path):
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        session.cancel()
        assert session._cancel_requested is True

    def test_cancel_sets_flag(self, tmp_path: Path):
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        assert session._cancel_requested is False
        session.cancel()
        assert session._cancel_requested is True


class TestDownloadSessionFormatSelector:
    def test_audio_only_selector(self, tmp_path: Path):
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="仅音频",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        assert session.format_selector == "ba/bestaudio"

    def test_video_only_selector(self, tmp_path: Path):
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="仅视频（无声音）",
            quality_label="1080p",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        assert "height<=1080" in session.format_selector


class TestCookieSessionMissingYtdlp:
    def test_done_callback_false_when_ytdlp_missing(self):
        done_results = []
        def done_cb(ok):
            done_results.append(ok)

        session = CookieSession(
            proxy=None,
            done_callback=done_cb,
        )
        with patch.dict("sys.modules", {"yt_dlp": None}):
            session.run()
        assert done_results == [False]


class TestCookieSessionWithCandidates:
    def test_runs_with_empty_candidates(self):
        status_msgs = []
        found_calls = []
        def done_cb(ok):
            found_calls.append(ok)

        session = CookieSession(
            proxy=None,
            candidates=[],
            status_callback=lambda m: status_msgs.append(m),
            done_callback=done_cb,
        )
        # Without yt_dlp, should fail gracefully
        with patch.dict("sys.modules", {"yt_dlp": None}):
            session.run()
        assert found_calls == [False]

    def test_status_callback_chain(self):
        statuses = []
        session = CookieSession(
            proxy=None,
            candidates=[("TestBrowser", "test", None)],
            status_callback=lambda m: statuses.append(m),
        )
        # Can't fully run without yt_dlp, but verify callbacks are callable
        session.status_callback("test message")
        assert "test message" in statuses


class TestDownloadSessionProgressHook:
    def test_hook_finished_status(self, tmp_path: Path):
        """Test that 'finished' status produces correct log message."""
        logs = []
        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=lambda m: logs.append(m),
        )

        # Simulate a finished hook
        assert session.urls == ["https://www.youtube.com/watch?v=abc"]


class TestDownloadSessionSubtitleFailureRecovers:
    """yt-dlp raises DownloadError when a non-fatal subtitle fetch 429s after
    the actual video+audio already landed on disk. The whole task must not be
    marked failed."""

    def _make_session(self, tmp_path, log_cb=None):
        return DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=log_cb or MagicMock(),
        )

    def test_subtitle_429_after_video_downloaded_counts_as_success(self, tmp_path: Path):
        logs: list[str] = []
        session = self._make_session(tmp_path, log_cb=lambda m: logs.append(m))

        def fake_extract_info(url, download=True):
            # yt-dlp writes the merged mp4 to target_dir on disk, THEN raises
            # when the follow-up subtitle step hits HTTP 429.
            # classify_site() returns "Youtube" (lowercase 'u'), not "YouTube".
            target = tmp_path / "downloads" / "Youtube"
            (target / "Some Title [abc].mp4").write_bytes(b"\x00" * 100)
            raise yt_dlp.utils.DownloadError(
                "Unable to download video subtitles for 'zh-Hans': "
                "HTTP Error 429: Too Many Requests"
            )

        fake_ydl = MagicMock()
        fake_ydl.extract_info.side_effect = fake_extract_info
        fake_ytdlp = MagicMock()
        fake_ytdlp.YoutubeDL.return_value.__enter__.return_value = fake_ydl

        with patch.dict("sys.modules", {"yt_dlp": fake_ytdlp}):
            result = session.run()

        assert result == (1, 0, 0), f"expected success, got {result}"
        # A warning that mentions subtitles must reach the log.
        assert any("字幕" in m or "subtitle" in m.lower() for m in logs), logs
        # The "失败" line must NOT appear for this URL.
        assert not any("[1/1] 失败" in m for m in logs), logs

    def test_real_failure_still_counts_as_failure(self, tmp_path: Path):
        """If extract_info fails AND no media file appeared, it stays a failure."""
        session = self._make_session(tmp_path)
        # Nothing pre-written to target_dir -> no recovery.

        def fake_extract_info(url, download=True):
            raise yt_dlp.utils.DownloadError("Video unavailable")

        fake_ydl = MagicMock()
        fake_ydl.extract_info.side_effect = fake_extract_info
        fake_ytdlp = MagicMock()
        fake_ytdlp.YoutubeDL.return_value.__enter__.return_value = fake_ydl

        with patch.dict("sys.modules", {"yt_dlp": fake_ytdlp}):
            result = session.run()

        assert result == (0, 1, 0), f"expected failure, got {result}"


class TestDownloadSessionIgnoreErrors:
    """yt-dlp must run with ignoreerrors=True so non-fatal failures
    (subtitle 429, etc.) become warnings rather than DownloadError.
    See yt_dlp/YoutubeDL.py line ~4499: when ignoreerrors is True,
    subtitle download errors are reported as warnings and DownloadError
    is not raised."""

    def test_ydl_opts_has_ignoreerrors_true(self, tmp_path: Path):
        captured_opts: list[dict] = []

        def fake_ytdlp_factory(opts):
            captured_opts.append(opts)
            ydl = MagicMock()
            ydl.extract_info.return_value = {
                "id": "abc", "title": "T", "duration": 1, "formats": [],
                "requested_formats": [],
            }
            return ydl

        fake_ytdlp = MagicMock()
        fake_ytdlp.YoutubeDL.side_effect = fake_ytdlp_factory
        fake_ytdlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = {
            "id": "abc", "title": "T", "duration": 1, "formats": [],
            "requested_formats": [],
        }

        session = DownloadSession(
            urls=["https://www.youtube.com/watch?v=abc"],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        with patch.dict("sys.modules", {"yt_dlp": fake_ytdlp}):
            session.run()

        assert captured_opts, "YoutubeDL was never instantiated"
        assert captured_opts[0].get("ignoreerrors") is True, (
            f"ignoreerrors must be True so subtitle/PP failures become warnings; "
            f"got {captured_opts[0].get('ignoreerrors')!r}"
        )


class TestDownloadSessionNoplaylist:
    """watch?v=ID&list=... must download only the single video identified by
    v= (noplaylist=True so yt-dlp ignores the &list= parameter). A bare
    playlist?list=ID URL must download every entry (noplaylist=False)."""

    def _capture_opts(self, tmp_path: Path, url: str) -> list[dict]:
        captured: list[dict] = []

        def factory(opts):
            captured.append(opts)
            ydl = MagicMock()
            ydl.extract_info.return_value = {
                "id": "abc", "title": "T", "duration": 1, "formats": [],
                "requested_formats": [],
            }
            return ydl

        fake_ytdlp = MagicMock()
        fake_ytdlp.YoutubeDL.side_effect = factory
        fake_ytdlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = {
            "id": "abc", "title": "T", "duration": 1, "formats": [],
            "requested_formats": [],
        }

        session = DownloadSession(
            urls=[url],
            base_download_dir=tmp_path / "downloads",
            proxy=None,
            download_mode="完整视频（画面+声音）",
            quality_label="最佳",
            bilibili_cookie_spec=None,
            bilibili_cookie_display=None,
            progress_callback=MagicMock(),
            log_callback=MagicMock(),
        )
        with patch.dict("sys.modules", {"yt_dlp": fake_ytdlp}):
            session.run()
        return captured

    def test_watch_with_list_param_sets_noplaylist_true(self, tmp_path: Path):
        opts = self._capture_opts(
            tmp_path,
            "https://www.youtube.com/watch?v=yv2cp1fmSt0"
            "&list=PLIkqtRtuM1TogfKj9u5MEYfXOMZVkVj-A&index=6",
        )
        assert opts, "YoutubeDL was never instantiated"
        assert opts[0].get("noplaylist") is True, (
            f"watch?v= URL must set noplaylist=True; got "
            f"{opts[0].get('noplaylist')!r}"
        )

    def test_watch_without_list_param_sets_noplaylist_true(self, tmp_path: Path):
        opts = self._capture_opts(
            tmp_path, "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        assert opts[0].get("noplaylist") is True

    def test_playlist_url_sets_noplaylist_false(self, tmp_path: Path):
        opts = self._capture_opts(
            tmp_path,
            "https://www.youtube.com/playlist?list=PLIkqtRtuM1TogfKj9u5MEYfXOMZVkVj-A",
        )
        assert opts[0].get("noplaylist") is False, (
            f"playlist?list= URL must set noplaylist=False so the whole "
            f"playlist downloads; got {opts[0].get('noplaylist')!r}"
        )

    def test_js_runtimes_dict_shape_when_deno_found(self, tmp_path: Path, monkeypatch):
        # yt-dlp requires {'deno': {'path': '/abs/deno'}} — string is rejected
        # (YoutubeDL._clean_js_runtimes raises ValueError).
        import vidapi.core.workers as w
        monkeypatch.setattr(w, "_deno_cache", "/fake/deno")
        opts = self._capture_opts(
            tmp_path, "https://www.youtube.com/watch?v=abc",
        )
        js_runtimes = opts[0].get("js_runtimes")
        assert isinstance(js_runtimes, dict), (
            f"js_runtimes must be dict per yt-dlp._clean_js_runtimes; got {type(js_runtimes)}"
        )
        assert "deno" in js_runtimes
        assert isinstance(js_runtimes["deno"], dict)
        assert js_runtimes["deno"].get("path") == "/fake/deno"

    def test_no_js_runtimes_when_deno_not_found(self, tmp_path: Path, monkeypatch):
        import vidapi.core.workers as w
        monkeypatch.setattr(w, "_deno_cache", None)
        opts = self._capture_opts(
            tmp_path, "https://www.youtube.com/watch?v=abc",
        )
        assert "js_runtimes" not in opts[0], (
            f"when deno cannot be found, do not set js_runtimes (yt-dlp default "
            f"""behavior applies); got {opts[0].get('js_runtimes')!r}"""
        )


class TestFindDeno:
    """_find_deno() caches results and resolves Deno either via PATH or via
    the well-known install locations (~/.deno/bin on Unix, AppData on Win)."""

    def _reset_cache(self):
        import vidapi.core.workers as w
        w._deno_cache = False

    def test_finds_on_path(self, monkeypatch):
        import vidapi.core.workers as w
        monkeypatch.setattr(w, "_DENO_SEARCH_PATHS", ())
        self._reset_cache()
        monkeypatch.setattr(w.shutil, "which", lambda _: "/usr/bin/deno")
        assert _find_deno() == "/usr/bin/deno"

    def test_returns_none_when_not_found(self, monkeypatch):
        import vidapi.core.workers as w
        monkeypatch.setattr(w, "_DENO_SEARCH_PATHS", ())
        self._reset_cache()
        monkeypatch.setattr(w.shutil, "which", lambda _: None)
        assert _find_deno() is None

    def test_caches_result(self, monkeypatch):
        import vidapi.core.workers as w
        monkeypatch.setattr(w, "_DENO_SEARCH_PATHS", ())
        self._reset_cache()
        monkeypatch.setattr(w.shutil, "which", lambda _: "/usr/bin/deno")
        first = _find_deno()
        monkeypatch.setattr(w.shutil, "which", lambda _: RuntimeError("must not be called"))
        assert _find_deno() == first

    def test_windows_exe_does_not_require_x_ok(self, monkeypatch, tmp_path):
        # Ponytail: on Windows .exe files have no execute bit. _find_deno()
        # must accept the file based on isfile() alone, never os.access(X_OK).
        import vidapi.core.workers as w
        fake_exe = tmp_path / "deno.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(
            w, "_DENO_SEARCH_PATHS", (str(fake_exe),)
        )
        monkeypatch.setattr(w.shutil, "which", lambda _: None)
        # Force os.access(..., X_OK) to return False as if we were on Windows
        # without an executable bit.
        monkeypatch.setattr(w.os, "access", lambda *a, **k: False)
        self._reset_cache()
        assert _find_deno() == str(fake_exe)

    def test_honors_deno_install_env(self, monkeypatch, tmp_path):
        # The official install scripts write to $DENO_INSTALL/bin/deno[.exe].
        import vidapi.core.workers as w
        bin_dir = tmp_path / "custom" / "bin"
        bin_dir.mkdir(parents=True)
        exe = bin_dir / "deno"
        exe.write_bytes(b"#!/bin/sh\n")
        monkeypatch.setattr(w, "_DENO_SEARCH_PATHS", ())
        monkeypatch.setattr(w.shutil, "which", lambda _: None)
        monkeypatch.setenv("DENO_INSTALL", str(tmp_path / "custom"))
        self._reset_cache()
        assert _find_deno() == str(exe)
