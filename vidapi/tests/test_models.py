"""Error tests for Pydantic models: validation failures, edge cases, serialization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vidapi.models import (
    ConfigResponse,
    ConfigUpdate,
    CookieStatusResponse,
    CookieUploadRequest,
    CreateTaskRequest,
    DownloadMode,
    ErrorResponse,
    ProgressEvent,
    Quality,
    Site,
    SystemInfoResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
)


class TestSiteEnum:
    def test_bilibili_value(self):
        assert Site.BILIBILI.value == "BiliBili"

    def test_youtube_value(self):
        assert Site.YOUTUBE.value == "Youtube"

    def test_invalid_site_string(self):
        with pytest.raises(ValueError):
            Site("invalid")


class TestDownloadModeEnum:
    def test_av_value(self):
        assert DownloadMode.AV.value == "完整视频（画面+声音）"

    def test_video_only_value(self):
        assert DownloadMode.VIDEO_ONLY.value == "仅视频（无声音）"

    def test_audio_only_value(self):
        assert DownloadMode.AUDIO_ONLY.value == "仅音频"

    def test_invalid_mode(self):
        with pytest.raises(ValueError):
            DownloadMode("invalid")


class TestQualityEnum:
    def test_best_value(self):
        assert Quality.BEST.value == "最佳"

    def test_1080p_value(self):
        assert Quality.P1080.value == "1080p"

    def test_4k_value(self):
        assert Quality.P2160.value == "2160p / 4K"

    def test_all_qualities(self):
        expected = ["最佳", "2160p / 4K", "1440p / 2K", "1080p", "720p", "480p", "360p"]
        actual = [q.value for q in Quality]
        assert actual == expected

    def test_invalid_quality(self):
        with pytest.raises(ValueError):
            Quality("invalid")


class TestTaskStatusEnum:
    def test_all_states(self):
        states = [s.value for s in TaskStatus]
        assert "pending" in states
        assert "downloading" in states
        assert "completed" in states
        assert "failed" in states
        assert "cancelled" in states

    def test_invalid_state(self):
        with pytest.raises(ValueError):
            TaskStatus("invalid")


class TestCreateTaskRequest:
    def test_valid_request(self):
        req = CreateTaskRequest(urls=["https://www.youtube.com/watch?v=abc"])
        assert len(req.urls) == 1
        assert req.download_mode == DownloadMode.AV
        assert req.quality == Quality.BEST

    def test_valid_request_with_all_fields(self):
        req = CreateTaskRequest(
            urls=["https://www.youtube.com/watch?v=abc"],
            download_mode=DownloadMode.AUDIO_ONLY,
            quality=Quality.P720,
            proxy="http://proxy:8080",
            cookie_header="SESSDATA=test",
        )
        assert req.download_mode == DownloadMode.AUDIO_ONLY
        assert req.quality == Quality.P720
        assert req.proxy == "http://proxy:8080"

    def test_empty_urls_list(self):
        with pytest.raises(ValidationError) as exc_info:
            CreateTaskRequest(urls=[])
        assert "urls" in str(exc_info.value)

    def test_missing_urls(self):
        with pytest.raises(ValidationError):
            CreateTaskRequest()

    def test_single_url(self):
        req = CreateTaskRequest(urls=["https://www.youtube.com/watch?v=abc"])
        assert req.urls == ["https://www.youtube.com/watch?v=abc"]

    def test_multiple_urls(self):
        req = CreateTaskRequest(urls=[
            "https://www.youtube.com/watch?v=aaa",
            "https://www.bilibili.com/video/BV1xx",
        ])
        assert len(req.urls) == 2

    def test_invalid_download_mode(self):
        with pytest.raises(ValidationError):
            CreateTaskRequest(
                urls=["https://www.youtube.com/watch?v=abc"],
                download_mode="invalid_mode",
            )

    def test_invalid_quality(self):
        with pytest.raises(ValidationError):
            CreateTaskRequest(
                urls=["https://www.youtube.com/watch?v=abc"],
                quality="invalid_quality",
            )

    def test_url_with_special_chars(self):
        req = CreateTaskRequest(urls=["https://www.youtube.com/watch?v=abc&feature=share"])
        assert req.urls[0] == "https://www.youtube.com/watch?v=abc&feature=share"

    def test_url_with_unicode(self):
        req = CreateTaskRequest(urls=["https://www.bilibili.com/video/BV1xx4y1XX77"])
        assert len(req.urls) == 1

    def test_empty_string_url_accepted(self):
        # Pydantic only checks min_length, not URL validity
        req = CreateTaskRequest(urls=[""])
        assert req.urls == [""]

    def test_url_with_spaces(self):
        req = CreateTaskRequest(urls=["https://www.youtube.com/watch?v=abc def"])
        assert len(req.urls) == 1


class TestTaskResponse:
    def test_from_dict(self):
        data = {
            "task_id": "abc12345",
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "state": TaskStatus.PENDING,
            "progress_pct": 0.0,
            "current_file": None,
            "error_msg": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "download_dir": "/home/user/Downloads",
            "download_mode": DownloadMode.AV,
            "quality": Quality.BEST,
        }
        resp = TaskResponse(**data)
        assert resp.task_id == "abc12345"
        assert resp.progress_pct == 0.0

    def test_from_dict_with_chinese(self):
        data = {
            "task_id": "abc12345",
            "urls": ["https://www.bilibili.com/video/BV1xx"],
            "state": TaskStatus.DOWNLOADING,
            "progress_pct": 50.0,
            "current_file": "视频.mp4",
            "error_msg": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "download_dir": "",
            "download_mode": DownloadMode.AV,
            "quality": Quality.P1080,
        }
        resp = TaskResponse(**data)
        assert resp.current_file == "视频.mp4"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            TaskResponse(
                task_id="abc",
                urls=["https://youtube.com"],
                state=TaskStatus.PENDING,
                # missing created_at
            )


class TestTaskListResponse:
    def test_empty_list(self):
        resp = TaskListResponse(tasks=[], total=0)
        assert resp.total == 0

    def test_list_with_tasks(self):
        tasks = [
            TaskResponse(
                task_id="1",
                urls=["https://youtube.com/watch?v=a"],
                state=TaskStatus.PENDING,
                created_at="2024-01-01T00:00:00",
                updated_at="2024-01-01T00:00:00",
                download_mode=DownloadMode.AV,
                quality=Quality.BEST,
            )
        ]
        resp = TaskListResponse(tasks=tasks, total=1)
        assert resp.total == 1
        assert len(resp.tasks) == 1


class TestCookieUploadRequest:
    def test_valid_cookie(self):
        req = CookieUploadRequest(cookie_header="SESSDATA=abc; bili_jct=xyz")
        assert req.cookie_header == "SESSDATA=abc; bili_jct=xyz"

    def test_empty_cookie(self):
        # Field has no min_length, so empty string is valid
        req = CookieUploadRequest(cookie_header="")
        assert req.cookie_header == ""

    def test_missing_cookie(self):
        with pytest.raises(ValidationError):
            CookieUploadRequest()


class TestCookieStatusResponse:
    def test_ok_response(self):
        resp = CookieStatusResponse(ok=True, online=True, message="登录成功")
        assert resp.ok is True

    def test_failed_response(self):
        resp = CookieStatusResponse(ok=False, online=False, message="Cookie无效")
        assert resp.ok is False


class TestConfigUpdate:
    def test_all_nulls(self):
        update = ConfigUpdate()
        assert update.concurrency is None

    def test_partial_update(self):
        update = ConfigUpdate(concurrency=5)
        assert update.concurrency == 5

    def test_concurrency_bounds(self):
        update = ConfigUpdate(concurrency=1)
        assert update.concurrency == 1

        update = ConfigUpdate(concurrency=16)
        assert update.concurrency == 16

    def test_concurrency_below_min(self):
        with pytest.raises(ValidationError):
            ConfigUpdate(concurrency=0)

    def test_concurrency_above_max(self):
        with pytest.raises(ValidationError):
            ConfigUpdate(concurrency=17)

    def test_invalid_quality_in_update(self):
        with pytest.raises(ValidationError):
            ConfigUpdate(quality="invalid")

    def test_invalid_download_mode_in_update(self):
        with pytest.raises(ValidationError):
            ConfigUpdate(download_mode="invalid")

    def test_download_dir_update(self):
        update = ConfigUpdate(download_dir="/custom/path")
        assert update.download_dir == "/custom/path"

    def test_proxy_update(self):
        update = ConfigUpdate(proxy="http://proxy:8080")
        assert update.proxy == "http://proxy:8080"

    def test_auto_merge_update(self):
        update = ConfigUpdate(auto_merge=False)
        assert update.auto_merge is False


class TestConfigResponse:
    def test_default_values(self):
        resp = ConfigResponse()
        assert resp.concurrency == 3
        assert resp.quality == Quality.BEST
        assert resp.download_mode == DownloadMode.AV
        assert resp.auto_merge is True

    def test_custom_values(self):
        resp = ConfigResponse(
            download_dir="/custom",
            proxy="http://proxy:8080",
            quality=Quality.P720,
            download_mode=DownloadMode.VIDEO_ONLY,
            concurrency=5,
            auto_merge=False,
            cookie_header="SESSDATA=test",
        )
        assert resp.download_dir == "/custom"
        assert resp.concurrency == 5


class TestSystemInfoResponse:
    def test_valid_response(self):
        resp = SystemInfoResponse(
            downloads_folder="/home/user/Downloads",
            ffmpeg_available=True,
            ffmpeg_path="/usr/bin/ffmpeg",
            proxy_detected="http://proxy:8080",
            yt_dlp_version="2024.01.01",
            platform="Linux",
        )
        assert resp.ffmpeg_available is True

    def test_no_ffmpeg(self):
        resp = SystemInfoResponse(
            downloads_folder="/home/user/Downloads",
            ffmpeg_available=False,
            ffmpeg_path=None,
            proxy_detected=None,
            yt_dlp_version="2024.01.01",
            platform="Linux",
        )
        assert resp.ffmpeg_available is False
        assert resp.ffmpeg_path is None


class TestProgressEvent:
    def test_to_sse_basic(self):
        event = ProgressEvent(event="progress", data={"task_id": "abc", "progress": 50.0})
        sse = event.to_sse()
        assert sse.startswith("event: progress\n")
        assert '"task_id": "abc"' in sse
        assert sse.endswith("\n\n")

    def test_to_sse_with_chinese(self):
        event = ProgressEvent(event="log", data={"message": "下载中..."})
        sse = event.to_sse()
        assert "下载中" in sse

    def test_to_sse_special_chars(self):
        event = ProgressEvent(event="error", data={"message": "Error: <script>"})
        sse = event.to_sse()
        assert "<script>" in sse

    def test_to_sse_newline_in_data(self):
        event = ProgressEvent(event="log", data={"message": "line1\nline2"})
        sse = event.to_sse()
        # JSON should escape the newline
        assert "\\n" in sse


class TestErrorResponse:
    def test_basic_error(self):
        resp = ErrorResponse(error="Not found", code="TASK_NOT_FOUND")
        assert resp.error == "Not found"
        assert resp.code == "TASK_NOT_FOUND"

    def test_error_with_details(self):
        resp = ErrorResponse(
            error="Validation failed",
            code="VALIDATION_ERROR",
            details={"field": "urls", "reason": "empty"},
        )
        assert resp.details["field"] == "urls"
