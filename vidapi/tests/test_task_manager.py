"""Error tests for task manager: state machine, invalid transitions, edge cases."""

from __future__ import annotations


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
        queue, _ = task_manager.subscribe(task_id)
        await task_manager.log_message(task_id, "test log entry")
        # The log is in the queue, not in the task data
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
        queue, _ = task_manager.subscribe(task_id)
        queue.put_nowait({"event": "test", "data": {}})
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
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


class TestTaskManagerSubscriberBroadcast:
    """C2: per-subscriber SSE queues. Unsubscribing one client must not break others."""

    @pytest.mark.asyncio
    async def test_subscribe_returns_distinct_queues(self, task_manager: TaskManager):
        q1, sub1 = task_manager.subscribe("t1")
        q2, sub2 = task_manager.subscribe("t1")
        assert q1 is not q2
        assert sub1 != sub2
        assert set(task_manager._progress_queues["t1"].keys()) == {sub1, sub2}

    @pytest.mark.asyncio
    async def test_broadcast_delivers_to_all(self, task_manager: TaskManager):
        q1, _ = task_manager.subscribe("t1")
        q2, _ = task_manager.subscribe("t1")
        task_manager._broadcast("t1", {"event": "log", "data": {"x": 1}})
        assert q1.qsize() == q2.qsize() == 1
        assert q1.get_nowait() == q2.get_nowait() == {"event": "log", "data": {"x": 1}}

    @pytest.mark.asyncio
    async def test_unsubscribe_last_removes_entry(self, task_manager: TaskManager):
        _, sub = task_manager.subscribe("t1")
        task_manager.unsubscribe("t1", sub)
        assert "t1" not in task_manager._progress_queues

    @pytest.mark.asyncio
    async def test_unsubscribe_one_keeps_other_active(self, task_manager: TaskManager):
        q1, sub1 = task_manager.subscribe("t1")
        q2, _ = task_manager.subscribe("t1")
        task_manager.unsubscribe("t1", sub1)
        assert "t1" in task_manager._progress_queues
        task_manager._broadcast("t1", {"event": "log", "data": {}})
        assert q2.qsize() == 1
        assert q1.qsize() == 0

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers_is_noop(self, task_manager: TaskManager):
        task_manager._broadcast("no-such-task", {"event": "log", "data": {}})

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_is_noop(self, task_manager: TaskManager):
        task_manager.unsubscribe("unknown", "unknown-sub")

    @pytest.mark.asyncio
    async def test_update_progress_broadcasts_to_all_subscribers(self, task_manager: TaskManager):
        task_id = await task_manager.create_task({"urls": ["https://youtube.com/watch?v=x"]})
        q1, _ = task_manager.subscribe(task_id)
        q2, _ = task_manager.subscribe(task_id)
        await task_manager.update_progress(task_id, 50.0, "downloading", "video.mp4")
        assert q1.qsize() == q2.qsize() == 1
        e1 = q1.get_nowait()
        assert e1["event"] == "progress"
        assert e1["data"]["progress_pct"] == 50.0
