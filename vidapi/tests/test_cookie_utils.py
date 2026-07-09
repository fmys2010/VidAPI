"""Error tests for cookie utils: inspect, verify, build_header, is_bilibili_cookie."""

from __future__ import annotations

import http.cookiejar
from unittest.mock import MagicMock, patch

import pytest

from vidapi.core.cookie_utils import (
    BILIBILI_COOKIE_CANDIDATES,
    BILIBILI_LOGIN_COOKIE_NAMES,
    build_cookie_header,
    inspect_bilibili_cookie_jar,
    is_bilibili_cookie,
    verify_bilibili_cookie_jar,
    cookie_candidate_to_spec,
)


def _cookie(name, value, domain=".bilibili.com", expires=None):
    """Create a Cookie compatible with Python 3.13+."""
    return http.cookiejar.Cookie(
        version=0, name=name, value=value, port=None,
        port_specified=False, domain=domain, domain_specified=True,
        domain_initial_dot=True, path="/", path_specified=True,
        secure=True, expires=expires, discard=True,
        comment="", comment_url="", rest={}, rfc2109=False,
    )


class TestIsBilibiliCookie:
    def test_bilibili_com(self):
        cookie = MagicMock()
        cookie.domain = "bilibili.com"
        assert is_bilibili_cookie(cookie) is True

    def test_subdomain_bilibili(self):
        cookie = MagicMock()
        cookie.domain = ".api.bilibili.com"
        assert is_bilibili_cookie(cookie) is True

    def test_b23_tv(self):
        cookie = MagicMock()
        cookie.domain = "b23.tv"
        assert is_bilibili_cookie(cookie) is False

    def test_youtube(self):
        cookie = MagicMock()
        cookie.domain = "youtube.com"
        assert is_bilibili_cookie(cookie) is False

    def test_missing_domain_attr(self):
        cookie = MagicMock(spec=[])
        assert is_bilibili_cookie(cookie) is False

    def test_none_domain(self):
        cookie = MagicMock()
        cookie.domain = None
        assert is_bilibili_cookie(cookie) is False

    def test_empty_domain(self):
        cookie = MagicMock()
        cookie.domain = ""
        assert is_bilibili_cookie(cookie) is False

    def test_case_insensitive(self):
        cookie = MagicMock()
        cookie.domain = "BILIBILI.COM"
        assert is_bilibili_cookie(cookie) is True


class TestInspectBilibiliCookieJar:
    def test_has_sessdata(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc123"))
        result = inspect_bilibili_cookie_jar(jar)
        assert result["has_login_cookie"] is True
        assert result["count"] == 1

    def test_missing_sessdata(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("bili_jct", "xyz"))
        result = inspect_bilibili_cookie_jar(jar)
        assert result["has_login_cookie"] is False
        assert "SESSDATA" in result["missing"]

    def test_empty_jar(self):
        jar = http.cookiejar.CookieJar()
        result = inspect_bilibili_cookie_jar(jar)
        assert result["has_login_cookie"] is False
        assert result["count"] == 0
        assert "SESSDATA" in result["missing"]

    def test_expires_at_extraction(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc", expires=1700000000))
        result = inspect_bilibili_cookie_jar(jar)
        assert result["expires_at"] == 1700000000

    def test_no_expires(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc"))
        result = inspect_bilibili_cookie_jar(jar)
        assert result["expires_at"] is None

    def test_non_bilibili_cookies_ignored(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc", domain=".youtube.com"))
        result = inspect_bilibili_cookie_jar(jar)
        assert result["count"] == 0


class TestBuildCookieHeader:
    def test_single_cookie(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc123"))
        result = build_cookie_header(jar, "api.bilibili.com")
        assert "SESSDATA=abc123" in result

    def test_multiple_cookies(self):
        jar = http.cookiejar.CookieJar()
        for name in ("SESSDATA", "bili_jct", "DedeUserID"):
            jar.set_cookie(_cookie(name, "val"))
        result = build_cookie_header(jar, "api.bilibili.com")
        assert "SESSDATA=val" in result
        assert "bili_jct=val" in result
        assert "DedeUserID=val" in result

    def test_wrong_domain_excluded(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc", domain=".youtube.com"))
        result = build_cookie_header(jar, "api.bilibili.com")
        assert result == ""

    def test_duplicate_names_deduplicated(self):
        jar = http.cookiejar.CookieJar()
        for val in ("first", "second"):
            jar.set_cookie(_cookie("SESSDATA", val))
        result = build_cookie_header(jar, "api.bilibili.com")
        assert result.count("SESSDATA") == 1

    def test_missing_domain_attr(self):
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(http.cookiejar.Cookie(
            version=0, name="SESSDATA", value="abc", port=None,
            port_specified=False, domain="", domain_specified=False,
            domain_initial_dot=False, path="/", path_specified=True,
            secure=True, expires=None, discard=True,
            comment="", comment_url="", rest={}, rfc2109=False,
        ))
        result = build_cookie_header(jar, "api.bilibili.com")
        assert result == ""


class TestVerifyBilibiliCookieJar:
    @patch("vidapi.core.cookie_utils.inspect_bilibili_cookie_jar")
    def test_missing_login_cookie(self, mock_inspect):
        mock_inspect.return_value = {"has_login_cookie": False, "missing": ["SESSDATA"]}
        jar = http.cookiejar.CookieJar()
        result = verify_bilibili_cookie_jar(jar, proxy=None)
        assert result["ok"] is False
        assert result["online"] is False
        assert "缺少" in result["message"]

    @patch("vidapi.core.cookie_utils.inspect_bilibili_cookie_jar")
    @patch("vidapi.core.cookie_utils.build_cookie_header")
    def test_empty_header_generated(self, mock_build, mock_inspect):
        mock_inspect.return_value = {"has_login_cookie": True, "missing": []}
        mock_build.return_value = ""
        jar = http.cookiejar.CookieJar()
        jar.set_cookie(_cookie("SESSDATA", "abc", domain=".youtube.com"))
        result = verify_bilibili_cookie_jar(jar, proxy=None)
        assert result["ok"] is False
        assert "未能生成" in result["message"]

    @patch("vidapi.core.cookie_utils.inspect_bilibili_cookie_jar")
    @patch("vidapi.core.cookie_utils.build_cookie_header")
    def test_network_error_during_verify(self, mock_build, mock_inspect):
        mock_inspect.return_value = {"has_login_cookie": True, "missing": []}
        mock_build.return_value = "SESSDATA=test"
        with patch("vidapi.core.cookie_utils.urllib.request.build_opener") as mock_bo:
            mock_opener = MagicMock()
            import urllib.error
            mock_opener.open.side_effect = urllib.error.URLError("Network unreachable")
            mock_bo.return_value = mock_opener
            jar = http.cookiejar.CookieJar()
            jar.set_cookie(_cookie("SESSDATA", "test"))
            result = verify_bilibili_cookie_jar(jar, proxy=None)
            assert result["ok"] is True
            assert result["online"] is False

    @patch("vidapi.core.cookie_utils.verify_bilibili_cookie_jar")
    def test_proxy_passed_to_verify(self, mock_verify):
        mock_verify.return_value = {"ok": True, "online": True, "message": "ok"}
        jar = http.cookiejar.CookieJar()
        verify_bilibili_cookie_jar(jar, proxy="http://proxy:8080")
        # Just verify it doesn't crash with proxy arg


class TestCookieCandidateToSpec:
    def test_no_profile(self):
        assert cookie_candidate_to_spec("chrome", None) == ("chrome",)

    def test_with_profile(self):
        assert cookie_candidate_to_spec("chrome", "Default") == ("chrome", "Default")

    def test_firefox_no_profile(self):
        assert cookie_candidate_to_spec("firefox", None) == ("firefox",)
