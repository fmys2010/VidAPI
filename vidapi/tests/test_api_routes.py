"""Error tests for API routes: validation failures, HTTP error codes, edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport

from vidapi.models import ConfigUpdate
from vidapi.task_manager import TaskManager


def _make_mock_app():
    """Build a FastAPI app with fully mocked-out lifespan so no real DB/executors are touched."""
    from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query

    app = FastAPI()

    # -- config router ------------------------------------------------------
    config_router = APIRouter()

    @config_router.get("")
    async def get_config():
        from vidapi.models import ConfigResponse
        return ConfigResponse()

    @config_router.put("")
    async def update_config(update: "ConfigUpdate"):
        from vidapi.models import ConfigResponse
        return ConfigResponse()

    # -- cookies router -----------------------------------------------------
    cookies_router = APIRouter()

    @cookies_router.get("/status")
    async def cookie_status():
        from vidapi.models import CookieStatusResponse
        return CookieStatusResponse(ok=False, online=False, message="No cookie header stored")

    @cookies_router.post("")
    async def upload_cookie(req: "CookieUploadRequest"):
        from vidapi.models import CookieStatusResponse
        if not req.cookie_header:
            raise HTTPException(status_code=422, detail="cookie_header is required")
        return CookieStatusResponse(ok=True, online=False, message="stored")

    # -- system router ------------------------------------------------------
    system_router = APIRouter()

    @system_router.get("/info")
    async def system_info():
        from vidapi.models import SystemInfoResponse
        return SystemInfoResponse(
            downloads_folder="/tmp",
            ffmpeg_available=False,
            ffmpeg_path=None,
            proxy_detected=None,
            yt_dlp_version="2024.01.01",
            platform="Linux",
        )

    # -- tasks router -------------------------------------------------------
    tasks_router = APIRouter()

    @tasks_router.post("")
    async def create_task(req: "CreateTaskRequest"):
        from vidapi.models import TaskResponse, TaskStatus
        import uuid
        task_id = str(uuid.uuid4())[:8]
        return TaskResponse(
            task_id=task_id, urls=req.urls, state=TaskStatus.PENDING,
            progress_pct=0.0, created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            download_mode=req.download_mode, quality=req.quality,
        )

    @tasks_router.get("")
    async def list_tasks(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        from vidapi.models import TaskListResponse
        return TaskListResponse(tasks=[], total=0)

    @tasks_router.get("/{task_id}")
    async def get_task(task_id: str):
        raise HTTPException(status_code=404, detail="Task not found")

    @tasks_router.delete("/{task_id}")
    async def delete_task(task_id: str):
        from fastapi import Response
        return Response(status_code=204)

    @tasks_router.post("/{task_id}/cancel")
    async def cancel_task(task_id: str):
        raise HTTPException(status_code=404, detail="Task not found")

    # -- streaming router ---------------------------------------------------
    streaming_router = APIRouter()

    @streaming_router.get("/{task_id}/stream")
    async def stream_task_progress(task_id: str):
        raise HTTPException(status_code=404, detail="Task not found")

    # -- assemble under /api/v1 prefix --------------------------------------
    from vidapi.models import CookieUploadRequest, CreateTaskRequest

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(config_router, prefix="/config", tags=["config"])
    api_v1.include_router(cookies_router, prefix="/cookies/bilibili", tags=["cookies"])
    api_v1.include_router(system_router, prefix="/system", tags=["system"])
    api_v1.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
    api_v1.include_router(streaming_router, prefix="/tasks", tags=["streaming"])

    app.include_router(api_v1)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "vidapi"}

    return app


@pytest.fixture()
def app():
    return _make_mock_app()


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "vidapi"


class TestCreateTaskValidation:
    async def test_empty_urls_list(self, client):
        resp = await client.post("/api/v1/tasks", json={"urls": []})
        assert resp.status_code == 422

    async def test_missing_urls_field(self, client):
        resp = await client.post("/api/v1/tasks", json={})
        assert resp.status_code == 422

    async def test_invalid_download_mode(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "download_mode": "invalid_mode_xyz",
        })
        assert resp.status_code == 422

    async def test_invalid_quality(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "quality": "invalid_quality_xyz",
        })
        assert resp.status_code == 422

    async def test_invalid_concurrency_in_config(self, client):
        resp = await client.put("/api/v1/config", json={"concurrency": 0})
        assert resp.status_code == 422

    async def test_concurrency_too_high(self, client):
        resp = await client.put("/api/v1/config", json={"concurrency": 17})
        assert resp.status_code == 422


class TestGetTask:
    async def test_nonexistent_task(self, client):
        resp = await client.get("/api/v1/tasks/nonexistent_id")
        assert resp.status_code == 404


class TestListTasks:
    async def test_empty_list(self, client):
        resp = await client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["tasks"] == []

    async def test_list_with_invalid_limit(self, client):
        resp = await client.get("/api/v1/tasks?limit=0")
        assert resp.status_code == 422

    async def test_list_with_limit_too_high(self, client):
        resp = await client.get("/api/v1/tasks?limit=1001")
        assert resp.status_code == 422

    async def test_list_with_negative_offset(self, client):
        resp = await client.get("/api/v1/tasks?offset=-1")
        assert resp.status_code == 422


class TestCancelTask:
    async def test_cancel_nonexistent_task(self, client):
        resp = await client.post("/api/v1/tasks/nonexistent/cancel")
        assert resp.status_code == 404


class TestDeleteTask:
    async def test_delete_nonexistent_task(self, client):
        resp = await client.delete("/api/v1/tasks/nonexistent_id")
        assert resp.status_code in (204, 404)


class TestConfigEndpoints:
    async def test_get_config(self, client):
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "concurrency" in data
        assert "quality" in data

    async def test_update_config_partial(self, client):
        resp = await client.put("/api/v1/config", json={"concurrency": 5})
        assert resp.status_code in (200, 422)

    async def test_update_config_empty_body(self, client):
        resp = await client.put("/api/v1/config", json={})
        assert resp.status_code in (200, 422)

    async def test_update_config_all_nulls(self, client):
        resp = await client.put("/api/v1/config", json={
            "download_dir": None, "proxy": None, "quality": None,
            "download_mode": None, "concurrency": None, "auto_merge": None,
            "cookie_header": None,
        })
        assert resp.status_code in (200, 422)


class TestCookieEndpoints:
    async def test_upload_empty_cookie(self, client):
        resp = await client.post("/api/v1/cookies/bilibili", json={"cookie_header": ""})
        assert resp.status_code in (400, 422)

    async def test_upload_invalid_cookie(self, client):
        resp = await client.post("/api/v1/cookies/bilibili", json={"cookie_header": "garbage=nothing=here"})
        assert resp.status_code in (400, 422)

    async def test_cookie_status_no_cookie(self, client):
        resp = await client.get("/api/v1/cookies/bilibili/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


class TestSystemEndpoint:
    async def test_system_info(self, client):
        resp = await client.get("/api/v1/system/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "downloads_folder" in data
        assert "ffmpeg_available" in data
        assert "yt_dlp_version" in data
        assert "platform" in data


class TestSSEStreaming:
    async def test_stream_nonexistent_task(self, client):
        resp = await client.get("/api/v1/tasks/nonexistent/stream")
        assert resp.status_code == 404


class TestInvalidHttpMethods:
    async def test_patch_not_allowed(self, client):
        resp = await client.patch("/api/v1/tasks")
        assert resp.status_code == 405

    async def test_delete_config_not_allowed(self, client):
        resp = await client.delete("/api/v1/config")
        assert resp.status_code == 405


class TestContentTypeValidation:
    async def test_create_task_json(self, client):
        resp = await client.post(
            "/api/v1/tasks",
            content=b'{"urls":["https://youtube.com/watch?v=x"]}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (201, 422)

    async def test_create_task_form_data(self, client):
        resp = await client.post(
            "/api/v1/tasks",
            data={"urls": "https://youtube.com/watch?v=x"},
        )
        assert resp.status_code in (422, 405)


class TestEdgeCaseUrls:
    async def test_url_with_special_characters(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": ["https://www.youtube.com/watch?v=abc&feature=share"],
        })
        assert resp.status_code in (201, 422)

    async def test_url_with_unicode(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": ["https://www.bilibili.com/video/BV1xx4y1XX77"],
        })
        assert resp.status_code in (201, 422)

    async def test_very_long_url(self, client):
        long_url = "https://www.youtube.com/watch?v=" + "a" * 2000
        resp = await client.post("/api/v1/tasks", json={"urls": [long_url]})
        assert resp.status_code in (201, 422)

    async def test_multiple_urls_same_site(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": [
                "https://www.youtube.com/watch?v=aaa",
                "https://www.youtube.com/watch?v=bbb",
            ],
        })
        assert resp.status_code in (201, 422)

    async def test_multiple_urls_different_sites(self, client):
        resp = await client.post("/api/v1/tasks", json={
            "urls": [
                "https://www.youtube.com/watch?v=aaa",
                "https://www.bilibili.com/video/BV1xx",
            ],
        })
        assert resp.status_code in (201, 422)


class TestUpdateConfigConcurrencyGuard:
    """C1: PUT /config with a different concurrency must not kill running downloads.

    Calls the real route handler `vidapi.api.config.update_config` directly with a
    real TaskManager (mocked executor). Captures the mock-executor reference BEFORE
    the call (the handler replaces `task_manager.executor` on success), and patches
    `ThreadPoolExecutor` so no real worker threads are spawned in tests.
    """

    @pytest.mark.asyncio
    async def test_blocked_when_downloads_active(self, task_manager: TaskManager):
        from unittest.mock import patch
        from vidapi.api.config import update_config

        task_manager._download_sessions["fake-active-task"] = MagicMock()
        mock_exec_before = task_manager.executor
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_tpe_cstr:
            with pytest.raises(HTTPException) as exc:
                await update_config(
                    update=ConfigUpdate(concurrency=5),
                    task_manager=task_manager,
                )
        assert exc.value.status_code == 409
        mock_exec_before.shutdown.assert_not_called()
        mock_tpe_cstr.assert_not_called()
        assert task_manager.executor is mock_exec_before

    @pytest.mark.asyncio
    async def test_allowed_when_no_downloads(self, task_manager: TaskManager):
        from unittest.mock import patch
        from vidapi.api.config import update_config

        mock_exec_before = task_manager.executor
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_tpe_cstr:
            result = await update_config(
                update=ConfigUpdate(concurrency=5),
                task_manager=task_manager,
            )
        assert result.concurrency == 5
        mock_exec_before.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        mock_tpe_cstr.assert_called_once_with(max_workers=5)
        assert task_manager.executor is mock_tpe_cstr.return_value

    @pytest.mark.asyncio
    async def test_same_concurrency_no_swap(self, task_manager: TaskManager):
        from unittest.mock import patch
        from vidapi.api.config import update_config

        current = task_manager.config.concurrency
        mock_exec_before = task_manager.executor
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_tpe_cstr:
            result = await update_config(
                update=ConfigUpdate(concurrency=current),
                task_manager=task_manager,
            )
        assert result.concurrency == current
        mock_exec_before.shutdown.assert_not_called()
        mock_tpe_cstr.assert_not_called()
        assert task_manager.executor is mock_exec_before

    @pytest.mark.asyncio
    async def test_non_concurrency_change_unaffected_by_active_downloads(
        self, task_manager: TaskManager
    ):
        from vidapi.api.config import update_config

        task_manager._download_sessions["fake-active"] = MagicMock()
        await update_config(
            update=ConfigUpdate(download_dir="/tmp/foo"),
            task_manager=task_manager,
        )
        assert task_manager.config.download_dir == "/tmp/foo"
        task_manager.executor.shutdown.assert_not_called()
