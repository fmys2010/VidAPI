"""Error tests for task manager: state machine, invalid transitions, edge cases."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vidapi.task_manager import TaskManager


class TestTaskManagerCreateTask:
    @pytest.mark.asyncio
    async def test_create_task_with_url(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=abc"],
        })
        assert len(task_id) == 8  # UUID truncated to 8 chars

    @pytest.mark.asyncio
    async def test_create_task_with_all_fields(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "download_mode": "仅音频",
            "quality": "720p",
            "proxy": "http://proxy:8080",
            "cookie_header": "SESSDATA=test",
        })
        task = await task_manager.get_task(task_id)
        assert task is not None
        assert task["download_mode"] == "仅音频"
        assert task["quality"] == "720p"

    @pytest.mark.asyncio
    async def test_create_task_uses_config_defaults(self, task_manager: TaskManager):
        task_manager.config.quality = "1080p"
        task_manager.config.download_mode = "完整视频（画面+声音）"
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=abc"],
        })
        task = await task_manager.get_task(task_id)
        assert task["quality"] == "1080p"
        assert task["download_mode"] == "完整视频（画面+声音）"

    @pytest.mark.asyncio
    async def test_create_task_multiple_urls(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({
            "urls": [
                "https://www.youtube.com/watch?v=aaa",
                "https://www.youtube.com/watch?v=bbb",
            ],
        })
        task = await task_manager.get_task(task_id)
        assert len(task["urls"]) == 2


class TestTaskManagerGetTask:
    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, task_manager: TaskManager):
        result = await task_manager.get_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_created_task(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=abc"],
        })
        task = await task_manager.get_task(task_id)
        assert task is not None
        assert task["task_id"] == task_id


class TestTaskManagerListTasks:
    @pytest.mark.asyncio
    async def test_list_empty(self, task_manager: TaskManager):
        tasks = await task_manager.list_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_list_after_create(self, task_manager: TaskManager):
        await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        tasks = await task_manager.list_tasks()
        assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_list_with_state_filter(self, task_manager: TaskManager):
        await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        tasks = await task_manager.list_tasks(state="pending")
        assert len(tasks) >= 1

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, task_manager: TaskManager):
        for i in range(5):
            await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        tasks = await task_manager.list_tasks(limit=2, offset=0)
        assert len(tasks) == 2
        tasks2 = await task_manager.list_tasks(limit=2, offset=2)
        assert len(tasks2) == 2


class TestTaskManagerCancelTask:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, task_manager: TaskManager):
        result = await task_manager.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        result = await task_manager.cancel_task(task_id)
        assert result is True
        task = await task_manager.get_task(task_id)
        assert task["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_task_fails(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        # Manually set state to completed
        await task_manager.state_change(task_id, "completed")
        result = await task_manager.cancel_task(task_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_failed_task_fails(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.state_change(task_id, "failed")
        result = await task_manager.cancel_task(task_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_task(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.cancel_task(task_id)
        result = await task_manager.cancel_task(task_id)
        assert result is False


class TestTaskManagerProgressUpdates:
    @pytest.mark.asyncio
    async def test_update_progress(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.update_progress(task_id, 50.0, "50% downloaded", "video.mp4")
        task = await task_manager.get_task(task_id)
        assert task["progress_pct"] == 50.0
        assert task["current_file"] == "video.mp4"

    @pytest.mark.asyncio
    async def test_update_progress_nonexistent_task(self, task_manager: TaskManager):
        # Should not raise, just silently return
        await task_manager.update_progress("nonexistent", 50.0, "msg")

    @pytest.mark.asyncio
    async def test_log_message(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.log_message(task_id, "test log entry")
        # The log is in the queue, not in the task data
        queue = await task_manager.get_progress_stream(task_id)
        assert not queue.empty()

    @pytest.mark.asyncio
    async def test_log_message_nonexistent_task(self, task_manager: TaskManager):
        # Should not raise
        await task_manager.log_message("nonexistent", "msg")


class TestTaskManagerStateChange:
    @pytest.mark.asyncio
    async def test_state_change_pending_to_downloading(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.state_change(task_id, "downloading")
        task = await task_manager.get_task(task_id)
        assert task["state"] == "downloading"

    @pytest.mark.asyncio
    async def test_state_change_with_error(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.state_change(task_id, "failed", "yt-dlp crashed")
        task = await task_manager.get_task(task_id)
        assert task["state"] == "failed"
        assert task["error_msg"] == "yt-dlp crashed"

    @pytest.mark.asyncio
    async def test_state_change_nonexistent_task(self, task_manager: TaskManager):
        # Should not raise
        await task_manager.state_change("nonexistent", "completed")

    @pytest.mark.asyncio
    async def test_invalid_state_transition(self, task_manager: TaskManager):
        """Test that we can set arbitrary states (enforcement is in API layer)."""
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.state_change(task_id, "invalid_state_xyz")
        task = await task_manager.get_task(task_id)
        assert task["state"] == "invalid_state_xyz"
        # Note: TaskManager doesn't enforce state machine rules, API layer does


class TestTaskManagerCompleteTask:
    @pytest.mark.asyncio
    async def test_complete_task_success(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
        task = await task_manager.get_task(task_id)
        assert task["state"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_task_failure(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        await task_manager.complete_task(task_id, success=False, failed=1, skipped=0)
        task = await task_manager.get_task(task_id)
        assert task["state"] == "failed"

    @pytest.mark.asyncio
    async def test_complete_task_cleanup_queues(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        # Put something in the queue
        queue = task_manager._get_queue(task_id)
        await queue.put({"event": "test", "data": {}})
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
        # Queue should be cleaned up
        assert task_id not in task_manager._progress_queues


class TestTaskManagerClassifySite:
    def test_classify_youtube(self, task_manager: TaskManager):
        assert task_manager.classify_site("https://www.youtube.com/watch?v=abc") == "Youtube"

    def test_classify_bilibili(self, task_manager: TaskManager):
        assert task_manager.classify_site("https://www.bilibili.com/video/BV1xx") == "BiliBili"

    def test_classify_unknown(self, task_manager: TaskManager):
        assert task_manager.classify_site("https://vimeo.com/123") is None

    def test_classify_empty(self, task_manager: TaskManager):
        assert task_manager.classify_site("") is None


class TestTaskManagerCookieVerification:
    @pytest.mark.asyncio
    async def test_verify_cookie_with_sessdata(self, task_manager: TaskManager):
        result = await task_manager.verify_bilibili_cookie("SESSDATA=test123; bili_jct=xyz")
        assert "ok" in result
        assert "message" in result

    @pytest.mark.asyncio
    async def test_verify_cookie_empty(self, task_manager: TaskManager):
        result = await task_manager.verify_bilibili_cookie("")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_verify_cookie_malformed(self, task_manager: TaskManager):
        result = await task_manager.verify_bilibili_cookie("not-a-cookie-at-all")
        # Should handle gracefully
        assert "ok" in result or "message" in result


class TestTaskManagerDeleteTask:
    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, task_manager: TaskManager):
        result = await task_manager.delete_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_task_cancels_first(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        # Delete should cancel first, then remove
        result = await task_manager.delete_task(task_id)
        assert result is True
        task = await task_manager.get_task(task_id)
        assert task is None


class TestTaskManagerQueueManagement:
    @pytest.mark.asyncio
    async def test_get_queue_creates_if_missing(self, task_manager: TaskManager):
        queue = task_manager._get_queue("new_task_id")
        assert isinstance(queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_get_queue_returns_existing(self, task_manager: TaskManager):
        q1 = task_manager._get_queue("task_1")
        q2 = task_manager._get_queue("task_1")
        assert q1 is q2

    @pytest.mark.asyncio
    async def test_progress_stream_returns_queue(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        queue = await task_manager.get_progress_stream(task_id)
        assert isinstance(queue, asyncio.Queue)
