"""Integration tests for task lifecycle state machine transitions."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from vidapi.task_manager import TaskManager


class TestTaskStateMachine:
    """Test the complete task state machine: pending → downloading → completed/failed/cancelled"""
    
    @pytest.mark.asyncio
    async def test_initial_state_is_pending(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Newly created task should be in pending state."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        task = await task_manager.get_task(task_id)
        assert task is not None
        assert task["state"] == "pending"
        assert task["progress_pct"] == 0.0
        assert task["error_msg"] is None
    
    @pytest.mark.asyncio
    async def test_pending_to_downloading_transition(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Task can transition from pending to downloading."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.state_change(task_id, "downloading")
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "downloading"
    
    @pytest.mark.asyncio
    async def test_downloading_to_completed_transition(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Task can transition from downloading to completed."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.state_change(task_id, "downloading")
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "completed"
        assert task["progress_pct"] == 100.0
    
    @pytest.mark.asyncio
    async def test_downloading_to_failed_transition(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Task can transition from downloading to failed."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.state_change(task_id, "downloading")
        await task_manager.complete_task(task_id, success=False, failed=1, skipped=0)
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "failed"
        assert task["error_msg"] is not None
        assert "Failed: 1" in task["error_msg"]
    
    @pytest.mark.asyncio
    async def test_pending_to_cancelled_transition(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Task can transition from pending to cancelled."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        result = await task_manager.cancel_task(task_id)
        assert result is True
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "cancelled"
    
    @pytest.mark.asyncio
    async def test_downloading_to_cancelled_transition(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Task can transition from downloading to cancelled."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.state_change(task_id, "downloading")
        
        # Mock a download session
        mock_session = MagicMock()
        mock_session.cancel = MagicMock()
        task_manager._download_sessions[task_id] = mock_session
        
        result = await task_manager.cancel_task(task_id)
        assert result is True
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "cancelled"
        mock_session.cancel.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cannot_cancel_completed_task(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Completed task cannot be cancelled."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
        
        result = await task_manager.cancel_task(task_id)
        assert result is False
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "completed"
    
    @pytest.mark.asyncio
    async def test_cannot_cancel_failed_task(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Failed task cannot be cancelled."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.complete_task(task_id, success=False, failed=1, skipped=0)
        
        result = await task_manager.cancel_task(task_id)
        assert result is False
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "failed"
    
    @pytest.mark.asyncio
    async def test_cannot_cancel_already_cancelled_task(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Already cancelled task cannot be cancelled again."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.cancel_task(task_id)
        result = await task_manager.cancel_task(task_id)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_state_change_with_error_message(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """State change can include error message."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.state_change(task_id, "failed", "Custom error message")
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "failed"
        assert task["error_msg"] == "Custom error message"
    
    @pytest.mark.asyncio
    async def test_update_progress_updates_state_and_pct(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """update_progress updates progress percentage and state."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.update_progress(
            task_id,
            progress=75.5,
            message="Downloading...",
            current_file="video.mp4",
            state="downloading",
        )
        
        task = await task_manager.get_task(task_id)
        assert task["progress_pct"] == 75.5
        assert task["current_file"] == "video.mp4"
        assert task["state"] == "downloading"
    
    @pytest.mark.asyncio
    async def test_update_progress_nonexistent_task_no_error(
        self,
        task_manager: TaskManager,
    ):
        """update_progress on nonexistent task doesn't raise."""
        await task_manager.update_progress("nonexistent", 50.0, "test")
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_log_message_queues_event(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """log_message queues log event to progress stream."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })

        queue = await task_manager.get_progress_stream(task_id)
        await task_manager.log_message(task_id, "Test log message")
        assert not queue.empty()
        
        event = await queue.get()
        assert event["event"] == "log"
        assert event["data"]["message"] == "Test log message"
    
    @pytest.mark.asyncio
    async def test_complete_task_cleans_up_resources(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """complete_task cleans up progress queue and download session."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        # Add some items to queue
        queue = await task_manager.get_progress_stream(task_id)
        await queue.put({"event": "test", "data": {}})
        
        # Add mock session
        mock_session = MagicMock()
        task_manager._download_sessions[task_id] = mock_session
        
        await task_manager.complete_task(task_id, success=True, failed=0, skipped=0)
        
        # Queue and session should be cleaned up
        assert task_id not in task_manager._progress_queues
        assert task_id not in task_manager._download_sessions


class TestTaskStateMachineViaAPI:
    """Test state machine transitions via API endpoints."""
    
    @pytest.mark.asyncio
    async def test_create_task_pending_via_api(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """API creates task in pending state."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        assert response.status_code == 201
        
        task = response.json()
        assert task["state"] == "pending"
        assert task["progress_pct"] == 0.0
    
    @pytest.mark.asyncio
    async def test_get_task_returns_current_state(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """GET /tasks/{id} returns current state."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        response = await client.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 200
        
        task = response.json()
        assert "state" in task
        assert "progress_pct" in task
        assert "urls" in task
        assert "created_at" in task
        assert "updated_at" in task
    
    @pytest.mark.asyncio
    async def test_list_tasks_filters_by_state(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """List tasks can filter by state."""
        # Create multiple tasks
        await client.post("/api/v1/tasks", json={"urls": [sample_youtube_url]})
        await client.post("/api/v1/tasks", json={"urls": [sample_youtube_url]})
        
        # Wait for one to complete
        await asyncio.sleep(0.2)
        
        # List all
        response = await client.get("/api/v1/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
        
        # Filter by pending
        response = await client.get("/api/v1/tasks?state=pending")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_cancel_task_via_api(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """Cancel task via API endpoint."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert response.status_code == 200
        
        response = await client.get(f"/api/v1/tasks/{task_id}")
        assert response.json()["state"] == "cancelled"
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task_404(
        self,
        client: AsyncClient,
    ):
        """Cancel nonexistent task returns 404."""
        response = await client.post("/api/v1/tasks/nonexistent/cancel")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_cancel_completed_task_400(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """Cancel completed task returns 400."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Wait for completion
        for _ in range(50):
            await asyncio.sleep(0.05)
            resp = await client.get(f"/api/v1/tasks/{task_id}")
            if resp.json()["state"] == "completed":
                break
        
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert response.status_code == 400
        assert "cannot cancel" in response.json()["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_delete_task_cancels_then_deletes(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """Delete task cancels then deletes."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        response = await client.delete(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 204
        
        # Task should be gone
        response = await client.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_task_204_or_404(
        self,
        client: AsyncClient,
    ):
        """Delete nonexistent task returns 204 or 404."""
        response = await client.delete("/api/v1/tasks/nonexistent")
        assert response.status_code in (204, 404)


class TestTaskStateValidation:
    """Test state validation and invalid transitions."""
    
    @pytest.mark.asyncio
    async def test_task_manager_allows_any_state(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """TaskManager allows setting any state (API layer enforces rules)."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        # TaskManager doesn't enforce state machine - API does
        await task_manager.state_change(task_id, "invalid_state_xyz")
        
        task = await task_manager.get_task(task_id)
        assert task["state"] == "invalid_state_xyz"
    
    @pytest.mark.asyncio
    async def test_api_enforces_valid_transitions(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """API enforces valid state transitions for cancel."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Cancel from pending - should work
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert response.status_code == 200
        
        # Cancel again - should fail
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        assert response.status_code == 400


class TestTaskProgressTracking:
    """Test progress tracking during download."""
    
    @pytest.mark.asyncio
    async def test_progress_percentage_updates(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Progress percentage updates correctly."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        for pct in [10.0, 25.5, 50.0, 75.25, 99.9]:
            await task_manager.update_progress(task_id, pct, f"{pct}% done")
        
        task = await task_manager.get_task(task_id)
        assert task["progress_pct"] == 99.9
    
    @pytest.mark.asyncio
    async def test_current_file_updates(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Current file updates correctly."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.update_progress(task_id, 50.0, "Downloading", "video.mp4")
        
        task = await task_manager.get_task(task_id)
        assert task["current_file"] == "video.mp4"
    
    @pytest.mark.asyncio
    async def test_multiple_urls_progress(
        self,
        task_manager: TaskManager,
    ):
        """Progress tracking with multiple URLs."""
        urls = [
            "https://www.youtube.com/watch?v=aaa",
            "https://www.youtube.com/watch?v=bbb",
            "https://www.youtube.com/watch?v=ccc",
        ]
        
        task_id = await task_manager.create_task({"urls": urls})
        
        # Progress should be trackable
        await task_manager.update_progress(task_id, 33.3, "1/3 done", "video1.mp4")
        await task_manager.update_progress(task_id, 66.6, "2/3 done", "video2.mp4")
        await task_manager.update_progress(task_id, 100.0, "Complete", "video3.mp4")
        
        task = await task_manager.get_task(task_id)
        assert task["progress_pct"] == 100.0


class TestTaskPersistence:
    """Test task persistence across operations."""
    
    @pytest.mark.asyncio
    async def task_persists_in_database(
        self,
        task_manager: TaskManager,
        database,
        sample_youtube_url: str,
    ):
        """Task is persisted in database."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        # Direct database query
        task = await database.get_task(task_id)
        assert task is not None
        assert task["task_id"] == task_id
        assert task["state"] == "pending"
    
    @pytest.mark.asyncio
    async def test_task_updates_persisted(
        self,
        task_manager: TaskManager,
        database,
        sample_youtube_url: str,
    ):
        """Task updates are persisted to database."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        await task_manager.update_progress(task_id, 50.0, "Halfway")
        
        # Check database directly
        task = await database.get_task(task_id)
        assert task["progress_pct"] == 50.0
    
    @pytest.mark.asyncio
    async def test_list_tasks_from_database(
        self,
        task_manager: TaskManager,
        database,
        sample_youtube_url: str,
    ):
        """List tasks retrieves from database."""
        task_id1 = await task_manager.create_task({"urls": [sample_youtube_url]})
        task_id2 = await task_manager.create_task({"urls": [sample_youtube_url]})
        
        tasks = await task_manager.list_tasks()
        assert len(tasks) >= 2
        
        task_ids = {t["task_id"] for t in tasks}
        assert task_id1 in task_ids
        assert task_id2 in task_ids
    
    @pytest.mark.asyncio
    async def test_list_tasks_with_pagination(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """List tasks supports pagination."""
        for _ in range(5):
            await task_manager.create_task({"urls": [sample_youtube_url]})
        
        page1 = await task_manager.list_tasks(limit=2, offset=0)
        assert len(page1) == 2
        
        page2 = await task_manager.list_tasks(limit=2, offset=2)
        assert len(page2) == 2
        
        # No overlap
        ids1 = {t["task_id"] for t in page1}
        ids2 = {t["task_id"] for t in page2}
        assert ids1.isdisjoint(ids2)
    
    @pytest.mark.asyncio
    async def test_list_tasks_with_state_filter(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """List tasks can filter by state."""
        await task_manager.create_task({"urls": [sample_youtube_url]})
        task_id = await task_manager.create_task({"urls": [sample_youtube_url]})
        await task_manager.state_change(task_id, "downloading")
        
        pending = await task_manager.list_tasks(state="pending")
        downloading = await task_manager.list_tasks(state="downloading")
        
        assert all(t["state"] == "pending" for t in pending)
        assert all(t["state"] == "downloading" for t in downloading)
    
    @pytest.mark.asyncio
    async def test_count_tasks(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Count tasks returns correct count."""
        initial = await task_manager.count_tasks()
        
        await task_manager.create_task({"urls": [sample_youtube_url]})
        await task_manager.create_task({"urls": [sample_youtube_url]})
        
        after = await task_manager.count_tasks()
        assert after == initial + 2


class TestTaskErrorHandling:
    """Test error handling in task operations."""
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_task_returns_none(
        self,
        task_manager: TaskManager,
    ):
        """get_task returns None for nonexistent task."""
        task = await task_manager.get_task("nonexistent")
        assert task is None
    
    @pytest.mark.asyncio
    async def test_update_progress_nonexistent_no_error(
        self,
        task_manager: TaskManager,
    ):
        """update_progress on nonexistent task doesn't error."""
        await task_manager.update_progress("nonexistent", 50.0, "test")
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_state_change_nonexistent_no_error(
        self,
        task_manager: TaskManager,
    ):
        """state_change on nonexistent task doesn't error."""
        await task_manager.state_change("nonexistent", "failed", "error")
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_log_message_nonexistent_no_error(
        self,
        task_manager: TaskManager,
    ):
        """log_message on nonexistent task doesn't error."""
        await task_manager.log_message("nonexistent", "test")
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_complete_nonexistent_no_error(
        self,
        task_manager: TaskManager,
    ):
        """complete_task on nonexistent task doesn't error."""
        await task_manager.complete_task("nonexistent", True, 0, 0)
        # Should not raise


class TestTaskQueueManagement:
    """Test progress queue management."""
    
    @pytest.mark.asyncio
    async def test_get_queue_creates_if_missing(
        self,
        task_manager: TaskManager,
    ):
        """get_queue creates new queue if missing."""
        queue = task_manager._get_queue("new_task")
        assert isinstance(queue, asyncio.Queue)
        assert queue.empty()
    
    @pytest.mark.asyncio
    async def test_get_queue_returns_existing(
        self,
        task_manager: TaskManager,
    ):
        """get_queue returns existing queue."""
        q1 = task_manager._get_queue("task1")
        q2 = task_manager._get_queue("task1")
        assert q1 is q2
    
    @pytest.mark.asyncio
    async def test_get_progress_stream_returns_queue(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """get_progress_stream returns queue for task."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        queue = await task_manager.get_progress_stream(task_id)
        assert isinstance(queue, asyncio.Queue)
    
    @pytest.mark.asyncio
    async def test_cleanup_queues_removes_empty(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Cleanup removes empty queues for completed tasks."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        # Add queue
        queue = await task_manager.get_progress_stream(task_id)
        await queue.put({"event": "test"})
        
        # Complete task (cleans up)
        await task_manager.complete_task(task_id, True, 0, 0)
        
        # Queue should be removed
        assert task_id not in task_manager._progress_queues


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])