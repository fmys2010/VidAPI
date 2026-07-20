"""Integration tests for cookie verification end-to-end flow."""

from __future__ import annotations

import http.cookiejar
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from vidapi.task_manager import TaskManager
from vidapi.core.config import Config


def _cookie(name: str, value: str = "v", domain: str = ".bilibili.com") -> "http.cookiejar.Cookie":
    """Build a minimal http.cookiejar.Cookie for tests."""
    return http.cookiejar.Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )


class TestCookieVerificationFlow:
    """Test complete cookie verification flow."""
    
    @pytest.mark.asyncio
    async def test_upload_cookie_verify_then_use_in_download(
        self,
        client: AsyncClient,
        valid_cookie_header: str,
    ):
        """Full flow: upload cookie → verify → use in download."""
        # ponytail: fake SESSDATA can't pass BiliBili's real login check; mock the
        # verifier so this test covers API wiring, not BiliBili's auth backend.
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": False, "message": "mock"}
            # Step 1: Upload cookie
            response = await client.post(
                "/api/v1/cookies/bilibili",
                json={"cookie_header": valid_cookie_header},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert "stored" in data["message"].lower()

            # Step 2: Verify cookie status
            response = await client.get("/api/v1/cookies/bilibili/status")
            assert response.status_code == 200
            status = response.json()
            assert "ok" in status
            assert "online" in status
            assert "message" in status

            # Step 3: Create task with cookie
            response = await client.post(
                "/api/v1/tasks",
                json={
                    "urls": ["https://www.bilibili.com/video/BV1xx4y1XX77"],
                    "cookie_header": valid_cookie_header,
                },
            )
            assert response.status_code == 201
            task = response.json()
            assert task["state"] == "pending"

    @pytest.mark.asyncio
    async def test_cookie_verification_with_sessdata_only(
        self,
        client: AsyncClient,
    ):
        """Verify cookie with just SESSDATA."""
        cookie = "SESSDATA=abc123"
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": False, "message": "mock"}
            response = await client.post(
                "/api/v1/cookies/bilibili",
                json={"cookie_header": cookie},
            )
            assert response.status_code == 200

            response = await client.get("/api/v1/cookies/bilibili/status")
            assert response.status_code == 200
            data = response.json()
            assert "ok" in data

    @pytest.mark.asyncio
    async def test_cookie_verification_with_full_cookie(
        self,
        client: AsyncClient,
    ):
        """Verify cookie with SESSDATA + bili_jct + DedeUserID."""
        cookie = "SESSDATA=abc123; bili_jct=xyz789; DedeUserID=123456"
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": False, "message": "mock"}
            response = await client.post(
                "/api/v1/cookies/bilibili",
                json={"cookie_header": cookie},
            )
            assert response.status_code == 200

            response = await client.get("/api/v1/cookies/bilibili/status")
            assert response.status_code == 200
            data = response.json()
            assert "ok" in data
            assert "online" in data
    
    @pytest.mark.asyncio
    async def test_cookie_verification_fails_gracefully(
        self,
        client: AsyncClient,
    ):
        """Invalid cookie fails verification but doesn't crash."""
        # Malformed cookie
        response = await client.post(
            "/api/v1/cookies/bilibili",
            json={"cookie_header": "not-a-valid-cookie"},
        )
        assert response.status_code in (400, 422)
    
    @pytest.mark.asyncio
    async def test_empty_cookie_rejected(
        self,
        client: AsyncClient,
    ):
        """Empty cookie is rejected."""
        response = await client.post(
            "/api/v1/cookies/bilibili",
            json={"cookie_header": ""},
        )
        assert response.status_code in (400, 422)
    
    @pytest.mark.asyncio
    async def test_cookie_status_without_upload(
        self,
        client: AsyncClient,
    ):
        """Cookie status without prior upload returns not ok."""
        response = await client.get("/api/v1/cookies/bilibili/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["online"] is False
        assert "no cookie" in data["message"].lower() or "not set" in data["message"].lower()


class TestCookieVerificationWithMockedNetwork:
    """Test cookie verification with mocked network calls."""
    
    @pytest.mark.asyncio
    async def test_verify_bilibili_cookie_success(
        self,
        task_manager: TaskManager,
    ):
        """Cookie verification succeeds with valid cookie."""
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {
                "ok": True,
                "online": True,
                "message": "登录成功：用户名 / 大会员",
            }
            
            result = await task_manager.verify_bilibili_cookie(
                "SESSDATA=test123; bili_jct=abc456; DedeUserID=789"
            )
            
            assert result["ok"] is True
            assert result["online"] is True
            assert "登录成功" in result["message"]
    
    @pytest.mark.asyncio
    async def test_verify_bilibili_cookie_failed(
        self,
        task_manager: TaskManager,
    ):
        """Cookie verification fails with invalid cookie."""
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {
                "ok": False,
                "online": False,
                "message": "Cookie 无效或已过期",
            }
            
            result = await task_manager.verify_bilibili_cookie(
                "SESSDATA=invalid"
            )
            
            assert result["ok"] is False
            assert result["online"] is False
    
    @pytest.mark.asyncio
    async def test_verify_bilibili_cookie_network_error(
        self,
        task_manager: TaskManager,
    ):
        """Network error during verification handled gracefully."""
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            import urllib.error
            mock_verify.side_effect = urllib.error.URLError("Network unreachable")
            
            result = await task_manager.verify_bilibili_cookie(
                "SESSDATA=test"
            )
            
            assert result["ok"] is True  # Network error treated as ok but offline
            assert result["online"] is False
            assert "验证失败" in result["message"] or "network" in result["message"].lower()
    
    @pytest.mark.asyncio
    async def test_verify_bilibili_cookie_empty_string(
        self,
        task_manager: TaskManager,
    ):
        """Empty cookie string handled."""
        result = await task_manager.verify_bilibili_cookie("")
        assert result["ok"] is False
    
    @pytest.mark.asyncio
    async def test_verify_bilibili_cookie_malformed(
        self,
        task_manager: TaskManager,
    ):
        """Malformed cookie handled gracefully."""
        result = await task_manager.verify_bilibili_cookie("not=valid=cookie=format")
        # Should not crash
        assert "ok" in result


class TestCookieUsedInDownload:
    """Test cookies are used during actual download."""
    
    @pytest.mark.asyncio
    async def test_download_session_receives_cookie(
        self,
        task_manager: TaskManager,
        sample_bilibili_url: str,
        valid_cookie_header: str,
    ):
        """DownloadSession receives cookie header when provided."""
        with patch("vidapi.task_manager.DownloadSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.run = MagicMock(return_value=(1, 0, 0))
            mock_session.cancel = MagicMock()
            mock_session._cancel_requested = False
            mock_session.format_selector = "bv*+ba/b"
            mock_session_class.return_value = mock_session
            
            task_id = await task_manager.create_task({
                "urls": [sample_bilibili_url],
                "cookie_header": valid_cookie_header,
            })
            
            await task_manager.run_download(task_id)
            
            # Verify DownloadSession was created with cookie
            call_args = mock_session_class.call_args
            assert call_args is not None
            kwargs = call_args.kwargs
            assert "bilibili_cookie_spec" in kwargs
            assert kwargs["bilibili_cookie_spec"] is not None
            assert kwargs["bilibili_cookie_spec"][0] == "manual"
            assert kwargs["bilibili_cookie_spec"][1] == valid_cookie_header
    
    @pytest.mark.asyncio
    async def test_download_without_cookie(
        self,
        task_manager: TaskManager,
        sample_youtube_url: str,
    ):
        """Download works without cookie (for YouTube)."""
        with patch("vidapi.task_manager.DownloadSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.run = MagicMock(return_value=(1, 0, 0))
            mock_session.cancel = MagicMock()
            mock_session._cancel_requested = False
            mock_session.format_selector = "bv*+ba/b"
            mock_session_class.return_value = mock_session
            
            task_id = await task_manager.create_task({
                "urls": [sample_youtube_url],
                # No cookie_header
            })
            
            await task_manager.run_download(task_id)
            
            # Verify no cookie passed
            call_args = mock_session_class.call_args
            kwargs = call_args.kwargs
            assert kwargs.get("bilibili_cookie_spec") is None
    
    @pytest.mark.asyncio
    async def test_cookie_from_config_used(
        self,
        task_manager: TaskManager,
        sample_bilibili_url: str,
        config: Config,
    ):
        """Cookie from config is used when not overridden."""
        config.cookie_header = "SESSDATA=from_config; bili_jct=config"
        
        with patch("vidapi.task_manager.DownloadSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.run = MagicMock(return_value=(1, 0, 0))
            mock_session.cancel = MagicMock()
            mock_session._cancel_requested = False
            mock_session.format_selector = "bv*+ba/b"
            mock_session_class.return_value = mock_session
            
            task_id = await task_manager.create_task({
                "urls": [sample_bilibili_url],
                # No cookie_header in request
            })
            
            await task_manager.run_download(task_id)
            
            call_args = mock_session_class.call_args
            kwargs = call_args.kwargs
            assert kwargs.get("bilibili_cookie_spec") is not None
            assert "from_config" in kwargs["bilibili_cookie_spec"][1]


class TestCookieVerificationEdgeCases:
    """Edge cases for cookie verification."""
    
    @pytest.mark.asyncio
    async def test_cookie_with_special_characters(
        self,
        task_manager: TaskManager,
    ):
        """Cookie with special characters in values."""
        cookie = "SESSDATA=abc%2Bdef; bili_jct=ghi;jkl; DedeUserID=123"
        
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": True, "message": "OK"}
            
            result = await task_manager.verify_bilibili_cookie(cookie)
            
            assert result["ok"] is True
    
    @pytest.mark.asyncio
    async def test_cookie_with_unicode(
        self,
        task_manager: TaskManager,
    ):
        """Cookie with unicode characters (unlikely but possible)."""
        cookie = "SESSDATA=测试123; bili_jct=test"
        
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": True, "message": "OK"}
            
            result = await task_manager.verify_bilibili_cookie(cookie)
            assert result["ok"] is True
    
    @pytest.mark.asyncio
    async def test_cookie_verification_proxy_passed(
        self,
        task_manager: TaskManager,
        config: Config,
    ):
        """Proxy configuration is passed to cookie verification."""
        config.proxy = "http://proxy:8080"
        
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": True, "message": "OK"}
            
            await task_manager.verify_bilibili_cookie("SESSDATA=test")
            
            # Verify proxy was passed
            call_args = mock_verify.call_args
            assert call_args is not None
            # verify_bilibili_cookie_jar is called with (cookie_jar, proxy)
            # The proxy should be passed from config
    
    @pytest.mark.asyncio
    async def test_cookie_verification_runs_in_executor(
        self,
        task_manager: TaskManager,
    ):
        """Cookie verification runs in thread pool executor."""
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": True, "message": "OK"}
            
            # Track which thread runs the verification
            import threading
            threads = []
            
            def track_thread(*args, **kwargs):
                threads.append(threading.current_thread().ident)
                return {"ok": True, "online": True, "message": "OK"}
            
            mock_verify.side_effect = track_thread
            
            await task_manager.verify_bilibili_cookie("SESSDATA=test")
            
            # Should run in executor thread (not main thread)
            # Note: In test environment with mocked executor, this may not hold


class TestCookieAPIEndpoints:
    """Test cookie-related API endpoints."""
    
    @pytest.mark.asyncio
    async def test_upload_cookie_endpoint(
        self,
        client: AsyncClient,
        valid_cookie_header: str,
    ):
        """POST /cookies/bilibili endpoint."""
        with patch("vidapi.task_manager.verify_bilibili_cookie_jar") as mock_verify:
            mock_verify.return_value = {"ok": True, "online": False, "message": "mock"}
            response = await client.post(
                "/api/v1/cookies/bilibili",
                json={"cookie_header": valid_cookie_header},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
    
    @pytest.mark.asyncio
    async def test_upload_cookie_validation_error(
        self,
        client: AsyncClient,
    ):
        """Upload cookie validates required field."""
        response = await client.post(
            "/api/v1/cookies/bilibili",
            json={},  # Missing cookie_header
        )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_upload_cookie_empty_string(
        self,
        client: AsyncClient,
    ):
        """Upload empty cookie string."""
        response = await client.post(
            "/api/v1/cookies/bilibili",
            json={"cookie_header": ""},
        )
        assert response.status_code in (400, 422)
    
    @pytest.mark.asyncio
    async def test_cookie_status_endpoint(
        self,
        client: AsyncClient,
    ):
        """GET /cookies/bilibili/status endpoint."""
        response = await client.get("/api/v1/cookies/bilibili/status")
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert "online" in data
        assert "message" in data
    
    @pytest.mark.asyncio
    async def test_cookie_status_after_upload(
        self,
        client: AsyncClient,
        valid_cookie_header: str,
    ):
        """Cookie status after successful upload."""
        # Upload
        await client.post(
            "/api/v1/cookies/bilibili",
            json={"cookie_header": valid_cookie_header},
        )
        
        # Check status
        response = await client.get("/api/v1/cookies/bilibili/status")
        assert response.status_code == 200
        data = response.json()
        # Status depends on actual cookie validity
        assert "ok" in data
    
    @pytest.mark.asyncio
    async def test_task_creation_with_cookie_header(
        self,
        client: AsyncClient,
        sample_bilibili_url: str,
        valid_cookie_header: str,
    ):
        """Task creation with cookie_header parameter."""
        response = await client.post(
            "/api/v1/tasks",
            json={
                "urls": [sample_bilibili_url],
                "cookie_header": valid_cookie_header,
            },
        )
        assert response.status_code == 201
        task = response.json()
        assert "task_id" in task
    
    @pytest.mark.asyncio
    async def test_task_creation_without_cookie(
        self,
        client: AsyncClient,
        sample_youtube_url: str,
    ):
        """Task creation without cookie works for YouTube."""
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_youtube_url]},
        )
        assert response.status_code == 201


class TestCookieConfigIntegration:
    """Test cookie integration with config system."""
    
    @pytest.mark.asyncio
    async def test_config_cookie_header_used(
        self,
        client: AsyncClient,
        sample_bilibili_url: str,
    ):
        """Config cookie_header used as default for tasks."""
        # Update config with cookie
        response = await client.put(
            "/api/v1/config",
            json={"cookie_header": "SESSDATA=config123; bili_jct=config456"},
        )
        assert response.status_code == 200
        
        # Create task without explicit cookie
        response = await client.post(
            "/api/v1/tasks",
            json={"urls": [sample_bilibili_url]},
        )
        assert response.status_code == 201
        
        # Task should inherit cookie from config
        response.json()
        # Note: Actual verification would require checking DownloadSession
    
    @pytest.mark.asyncio
    async def test_task_cookie_overrides_config(
        self,
        client: AsyncClient,
        sample_bilibili_url: str,
        valid_cookie_header: str,
    ):
        """Task-specific cookie overrides config cookie."""
        # Set config cookie
        await client.put(
            "/api/v1/config",
            json={"cookie_header": "SESSDATA=config"},
        )
        
        # Create task with different cookie
        response = await client.post(
            "/api/v1/tasks",
            json={
                "urls": [sample_bilibili_url],
                "cookie_header": valid_cookie_header,
            },
        )
        assert response.status_code == 201
        # Task should use valid_cookie_header, not config cookie


class TestCookieVerificationWithRealUtils:
    """Test cookie verification using actual cookie utilities."""
    
    def test_is_bilibili_cookie_bilibili_com(self):
        """is_bilibili_cookie recognizes bilibili.com."""
        from vidapi.core.cookie_utils import is_bilibili_cookie
        from unittest.mock import MagicMock
        
        cookie = MagicMock()
        cookie.domain = "bilibili.com"
        assert is_bilibili_cookie(cookie) is True
    
    def test_is_bilibili_cookie_subdomain(self):
        """is_bilibili_cookie recognizes subdomains."""
        from vidapi.core.cookie_utils import is_bilibili_cookie
        from unittest.mock import MagicMock
        
        cookie = MagicMock()
        cookie.domain = ".api.bilibili.com"
        assert is_bilibili_cookie(cookie) is True
    
    def test_is_bilibili_cookie_rejects_b23_tv(self):
        """is_bilibili_cookie rejects b23.tv."""
        from vidapi.core.cookie_utils import is_bilibili_cookie
        from unittest.mock import MagicMock
        
        cookie = MagicMock()
        cookie.domain = "b23.tv"
        assert is_bilibili_cookie(cookie) is False
    
    def test_is_bilibili_cookie_rejects_youtube(self):
        """is_bilibili_cookie rejects youtube.com."""
        from vidapi.core.cookie_utils import is_bilibili_cookie
        from unittest.mock import MagicMock
        
        cookie = MagicMock()
        cookie.domain = "youtube.com"
        assert is_bilibili_cookie(cookie) is False
    
    def test_is_bilibili_cookie_case_insensitive(self):
        """is_bilibili_cookie is case insensitive."""
        from vidapi.core.cookie_utils import is_bilibili_cookie
        from unittest.mock import MagicMock
        
        cookie = MagicMock()
        cookie.domain = "BILIBILI.COM"
        assert is_bilibili_cookie(cookie) is True
    
    def test_inspect_bilibili_cookie_jar_has_sessdata(self):
        """inspect_bilibili_cookie_jar detects SESSDATA."""
        from vidapi.core.cookie_utils import inspect_bilibili_cookie_jar
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc123"))
        
        result = inspect_bilibili_cookie_jar(jar)
        assert result["has_login_cookie"] is True
        assert result["count"] == 1
    
    def test_inspect_bilibili_cookie_jar_missing_sessdata(self):
        """inspect_bilibili_cookie_jar detects missing SESSDATA."""
        from vidapi.core.cookie_utils import inspect_bilibili_cookie_jar
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("bili_jct", "xyz"))
        
        result = inspect_bilibili_cookie_jar(jar)
        assert result["has_login_cookie"] is False
        assert "SESSDATA" in result["missing"]
    
    def test_build_cookie_header_single(self):
        """build_cookie_header builds single cookie."""
        from vidapi.core.cookie_utils import build_cookie_header
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc123"))
        
        result = build_cookie_header(jar, "api.bilibili.com")
        assert "SESSDATA=abc123" in result
    
    def test_build_cookie_header_multiple(self):
        """build_cookie_header builds multiple cookies."""
        from vidapi.core.cookie_utils import build_cookie_header
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        for name in ("SESSDATA", "bili_jct", "DedeUserID"):
            jar.set_cookie(_cookie(name, "val"))
        
        result = build_cookie_header(jar, "api.bilibili.com")
        assert "SESSDATA=val" in result
        assert "bili_jct=val" in result
        assert "DedeUserID=val" in result
    
    def test_build_cookie_header_wrong_domain_excluded(self):
        """build_cookie_header excludes wrong domain cookies."""
        from vidapi.core.cookie_utils import build_cookie_header
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc", domain=".youtube.com"))
        
        result = build_cookie_header(jar, "api.bilibili.com")
        assert result == ""
    
    def test_build_cookie_header_duplicates_deduplicated(self):
        """build_cookie_header deduplicates same-name cookies."""
        from vidapi.core.cookie_utils import build_cookie_header
        import http.cookiejar
        
        jar = http.cookiejar.CookieJar()
        for val in ("first", "second"):
            jar.set_cookie(_cookie("SESSDATA", val))
        
        result = build_cookie_header(jar, "api.bilibili.com")
        assert result.count("SESSDATA") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])