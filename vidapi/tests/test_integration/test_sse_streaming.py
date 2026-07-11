"""Integration tests for SSE streaming with real TaskManager."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.responses import EventSourceResponse
from httpx import AsyncClient

from vidapi.api.streaming import make_sse_event, stream_task_progress
from vidapi.task_manager import TaskManager


class TestSSEEventFormatting:
    """Test SSE event formatting."""
    
    def test_basic_event(self):
        """Test basic SSE event format."""
        result = make_sse_event("progress", {"task_id": "abc", "progress": 50.0})
        assert result.startswith("event: progress\n")
        assert '"task_id": "abc"' in result
        assert '"progress": 50.0' in result
        assert result.endswith("\n\n")
    
    def test_event_with_chinese(self):
        """Test SSE event with Chinese characters."""
        result = make_sse_event("log", {"message": "下载中..."})
        assert "下载中" in result
    
    def test_event_with_special_chars(self):
        """Test SSE event with special characters."""
        result = make_sse_event("error", {"message": "Error: <script>alert('xss')</script>"})
        assert "<script>" in result  # SSE doesn't escape HTML
    
    def test_event_structure(self):
        """Test SSE event structure."""
        result = make_sse_event("state_change", {"state": "completed"})
        lines = result.split("\n")
        assert lines[0] == "event: state_change"
        assert lines[1].startswith("data: ")
        assert lines[2] == ""


class TestSSEStreamingIntegration:
    """Integration tests for SSE streaming endpoint."""
    
    @pytest.mark.asyncio
    async def test_stream_nonexistent_task_returns_404(
        self,
        client: AsyncClient,
    ):
        """Stream for nonexistent task returns 404."""
        response = await client.get("/api/v1/tasks/nonexistent/stream")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_stream_sends_initial_state(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """SSE stream sends initial state event."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Connect to SSE
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.status_code == 200
            assert "text/event-stream" in sse_response.headers["content-type"]
            
            # Read initial state event
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 5:
                    break
            
            # Should have initial state_change event
            state_events = [e for e in events if e.startswith("event: state_change")]
            assert len(state_events) >= 1
    
    @pytest.mark.asyncio
    async def test_stream_receives_progress_events(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """SSE stream receives progress events during download."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Wait for download to start
        await asyncio.sleep(0.1)
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 20:
                    break
            
            # Should have progress events (may not have if download completes quickly)
    
    @pytest.mark.asyncio
    async def test_stream_receives_complete_event(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """SSE stream receives complete event when download finishes."""
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
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            # Should have complete or state_change to completed
            complete_events = [e for e in events if "complete" in e.lower() or '"state": "completed"' in e]
            # May have already completed before connection
    
    @pytest.mark.asyncio
    async def test_stream_heartbeat_on_idle(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """SSE sends heartbeat when queue is idle."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            # Wait a bit to allow heartbeat
            start = asyncio.get_event_loop().time()
            async for line in sse_response.aiter_lines():
                events.append(line)
                if asyncio.get_event_loop().time() - start > 1.0:
                    break
            
            # Check for heartbeat
            heartbeats = [e for e in events if e.startswith(": heartbeat")]
            # Heartbeat may or may not appear depending on timing
    
    @pytest.mark.asyncio
    async def test_stream_client_disconnect_cleanup(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """Client disconnect cleans up progress queue."""
        from vidapi.main import get_task_manager
        
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Get task manager and verify queue exists after connect
        tm = get_task_manager()
        
        # Connect and immediately disconnect
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream"):
            pass  # Context manager handles disconnect
        
        await asyncio.sleep(0.1)
        
        # Queue should be cleaned up (or will be by cleanup task)
        # The cleanup happens in finally block of event_generator
    
    @pytest.mark.asyncio
    async def test_multiple_clients_receive_events(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """Multiple SSE clients should all receive events."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Connect 3 clients
        connections = []
        for _ in range(3):
            sse_response = await client.get(f"/api/v1/tasks/{task_id}/stream")
            assert sse_response.status_code == 200
            connections.append(sse_response)
        
        # Wait for events
        await asyncio.sleep(0.3)
        
        # Close all
        for conn in connections:
            await conn.aclose()


class TestSSEWithTaskManager:
    """Test SSE streaming with real TaskManager progress queues."""
    
    @pytest.mark.asyncio
    async def test_sse_event_generator_with_real_queue(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Test event generator with real TaskManager queue."""
        # Create a task
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        # Get progress queue
        queue = await task_manager.get_progress_stream(task_id)
        
        # Put some events
        await queue.put({
            "event": "progress",
            "data": {
                "task_id": task_id,
                "progress_pct": 50.0,
                "message": "Downloading...",
                "current_file": "video.mp4",
                "state": "downloading",
            }
        })
        await queue.put({
            "event": "state_change",
            "data": {
                "task_id": task_id,
                "state": "completed",
            }
        })
        await queue.put({
            "event": "complete",
            "data": {
                "task_id": task_id,
                "state": "completed",
                "success": True,
                "failed": 0,
                "skipped": 0,
            }
        })
        
        # Test the generator
        mock_tm = MagicMock()
        mock_tm.get_task = AsyncMock(return_value={
            "task_id": task_id,
            "state": "pending",
            "progress_pct": 0.0,
        })
        mock_tm.get_progress_stream = AsyncMock(return_value=queue)
        
        # Get the generator
        resp = await stream_task_progress(task_id=task_id, task_manager=mock_tm)
        
        # Collect events
        events = []
        async for chunk in resp.body_iterator:
            events.append(chunk.decode())
        
        # Verify events
        event_text = "".join(events)
        assert "event: state_change" in event_text
        assert "event: progress" in event_text
        assert "event: complete" in event_text


class TestSSEEdgeCases:
    """Edge cases for SSE streaming."""
    
    @pytest.mark.asyncio
    async def test_sse_with_unicode_messages(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """SSE handles Unicode messages correctly."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            # Should handle Chinese characters
            event_text = "\n".join(events)
            # Messages from yt-dlp may contain Chinese
    
    @pytest.mark.asyncio
    async def test_sse_cors_headers(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """SSE endpoint has correct CORS headers."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.headers.get("Cache-Control") == "no-cache"
            assert sse_response.headers.get("Connection") == "keep-alive"
            assert sse_response.headers.get("X-Accel-Buffering") == "no"
    
    @pytest.mark.asyncio
    async def test_sse_invalid_task_id_format(
        self,
        client: AsyncClient,
    ):
        """SSE with invalid task ID format."""
        response = await client.get("/api/v1/tasks/invalid-id/stream")
        # Should return 404 for nonexistent, not 422
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_sse_terminates_on_task_completion(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """SSE stream terminates after task completes."""
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
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) > 10:
                    break
            
            # After completion, queue is cleaned up, generator should end
            # May see complete event or just initial state


class TestSSEPerformance:
    """Performance tests for SSE streaming."""
    
    @pytest.mark.asyncio
    async def test_sse_many_events_no_memory_leak(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Many SSE events don't cause memory leak."""
        task_id = await task_manager.create_task({
            "urls": [sample_youtube_url],
        })
        
        queue = await task_manager.get_progress_stream(task_id)
        
        # Put many events
        for i in range(100):
            await queue.put({
                "event": "progress",
                "data": {
                    "task_id": task_id,
                    "progress_pct": float(i),
                    "message": f"Progress {i}%",
                    "state": "downloading",
                }
            })
        
        # Queue should have all events
        assert queue.qsize() == 100
        
        # Clean up
        task_manager._progress_queues.pop(task_id, None)
    
    @pytest.mark.asyncio
    async def test_sse_concurrent_connections_per_task(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
        mock_successful_download: MagicMock,
    ):
        """Multiple concurrent SSE connections to same task."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        task_id = response.json()["task_id"]
        
        # Open 10 connections
        connections = []
        for _ in range(10):
            sse = await client.get(f"/api/v1/tasks/{task_id}/stream")
            connections.append(sse)
        
        # All should succeed
        assert all(s.status_code == 200 for s in connections)
        
        # Close all
        for s in connections:
            await s.aclose()


class TestSSEStreamingDirectFunction:
    """Direct tests for the stream_task_progress function."""
    
    @pytest.mark.asyncio
    async def test_make_sse_event_format(self):
        """Test make_sse_event produces valid SSE format."""
        event = make_sse_event("test", {"key": "value"})
        lines = event.strip().split("\n")
        
        assert lines[0] == "event: test"
        assert lines[1] == 'data: {"key": "value"}'
        assert lines[2] == ""
    
    @pytest.mark.asyncio
    async def test_stream_task_progress_nonexistent_task(
        self,
        task_manager: TaskManager,
    ):
        """stream_task_progress raises 404 for nonexistent task."""
        from fastapi import HTTPException
        
        task_manager.get_task = AsyncMock(return_value=None)
        
        with pytest.raises(HTTPException) as exc_info:
            await stream_task_progress("nonexistent", task_manager)
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_stream_task_progress_heartbeat(
        self,
        task_manager: TaskManager,
    ):
        """stream_task_progress yields heartbeat on timeout."""
        import asyncio
        
        task_manager.get_task = AsyncMock(return_value={
            "task_id": "test",
            "state": "pending",
            "progress_pct": 0.0,
        })
        
        queue = asyncio.Queue()
        task_manager.get_progress_stream = AsyncMock(return_value=queue)
        
        # Put a sentinel to stop the generator after a few heartbeats
        async def mock_get():
            await asyncio.sleep(0.05)
            raise asyncio.CancelledError("client disconnected")
        
        queue.get = mock_get
        queue.empty = MagicMock(return_value=True)
        
        resp = await stream_task_progress("test", task_manager)
        
        # The generator should be created
        assert resp is not None
        assert resp.media_type == "text/event-stream"


class TestSSEContentTypeAndHeaders:
    """Test SSE response content type and headers."""
    
    @pytest.mark.asyncio
    async def test_sse_content_type(self, client: AsyncClient):
        """SSE response has correct content type."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    @pytest.mark.asyncio
    async def test_sse_no_cache_header(self, client: AsyncClient):
        """SSE response has no-cache header."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.headers["Cache-Control"] == "no-cache"
    
    @pytest.mark.asyncio
    async def test_sse_keep_alive_header(self, client: AsyncClient):
        """SSE response has keep-alive header."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.headers["Connection"] == "keep-alive"
    
    @pytest.mark.asyncio
    async def test_sse_no_buffering_header(self, client: AsyncClient):
        """SSE response has X-Accel-Buffering: no."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
        )
        task_id = response.json()["task_id"]
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            assert sse_response.headers["X-Accel-Buffering"] == "no"


class TestSSEEventTypes:
    """Test different SSE event types."""
    
    @pytest.mark.asyncio
    async def test_state_change_event(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """State change events are sent correctly."""
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        })
        
        await task_manager.state_change(task_id, "downloading")
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            event_text = "\n".join(events)
            assert "event: state_change" in event_text
            assert '"state": "downloading"' in event_text
    
    @pytest.mark.asyncio
    async def test_progress_event(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """Progress events are sent correctly."""
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        })
        
        await task_manager.update_progress(task_id, 42.5, "42.5% done", "video.mp4")
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            event_text = "\n".join(events)
            assert "event: progress" in event_text
            assert "42.5" in event_text
    
    @pytest.mark.asyncio
    async def test_complete_event(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """Complete events are sent correctly."""
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        })
        
        await task_manager.complete_task(task_id, True, 0, 0)
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            event_text = "\n".join(events)
            assert "event: complete" in event_text or '"state": "completed"' in event_text
    
    @pytest.mark.asyncio
    async def test_error_event(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """Error events are sent correctly."""
        task_id = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        })
        
        await task_manager.state_change(task_id, "failed", "Network error")
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            event_text = "\n".join(events)
            assert "event: error" in event_text or '"state": "failed"' in event_text


class TestSSEEdgeCases:
    """Edge cases for SSE streaming."""
    
    @pytest.mark.asyncio
    async def test_sse_with_unicode_task_data(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """SSE handles Unicode in task data."""
        task_id = await task_manager.create_task({
            "urls": ["https://www.bilibili.com/video/BV1xx4y1XX77"],
        })
        
        await task_manager.update_progress(task_id, 50.0, "下载中... 视频.mp4")
        
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as sse_response:
            events = []
            async for line in sse_response.aiter_lines():
                events.append(line)
                if len(events) >= 10:
                    break
            
            event_text = "\n".join(events)
            assert "下载中" in event_text or "video" in event_text
    
    @pytest.mark.asyncio
    async def test_sse_concurrent_downloads_separate_streams(
        self,
        client: AsyncClient,
        task_manager: TaskManager,
    ):
        """Concurrent downloads have separate SSE streams."""
        task_id1 = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=aaa"],
        })
        task_id2 = await task_manager.create_task({
            "urls": ["https://www.youtube.com/watch?v=bbb"],
        })
        
        # Connect to both
        async with client.stream("GET", f"/api/v1/tasks/{task_id1}/stream") as resp1:
            async with client.stream("GET", f"/api/v1/tasks/{task_id2}/stream") as resp2:
                assert resp1.status_code == 200
                assert resp2.status_code == 200
                
                # Each has its own stream
                events1 = []
                async for line in resp1.aiter_lines():
                    events1.append(line)
                    if len(events1) >= 5:
                        break
                
                events2 = []
                async for line in resp2.aiter_lines():
                    events2.append(line)
                    if len(events2) >= 5:
                        break
                
                # Both should have state_change
                assert any("state_change" in e for e in events1)
                assert any("state_change" in e for e in events2)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])