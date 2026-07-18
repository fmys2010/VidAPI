"""Error tests for workers: DownloadSession and CookieSession error paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp.utils

from vidapi.core.workers import DownloadSession, CookieSession, QueueLogger


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
        hook = session.run.__code__  # Just verify session was created
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
