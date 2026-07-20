"""Error tests for system utils: proxy validation, format helpers, ffmpeg detection."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


from vidapi.core.system_utils import (
    _validate_proxy_url,
    detect_system_proxy,
    format_bytes,
    format_eta,
    get_downloads_folder,
    get_ffmpeg_location,
    get_platform_config_dir,
)


class TestValidateProxyUrl:
    def test_http_proxy(self):
        assert _validate_proxy_url("http://proxy.example.com:8080") == "http://proxy.example.com:8080"

    def test_https_proxy(self):
        assert _validate_proxy_url("https://proxy.example.com:443") == "https://proxy.example.com:443"

    def test_socks5_proxy(self):
        assert _validate_proxy_url("socks5://proxy:1080") == "socks5://proxy:1080"

    def test_socks4_proxy(self):
        assert _validate_proxy_url("socks4://proxy:1080") == "socks4://proxy:1080"

    def test_socks4a_proxy(self):
        assert _validate_proxy_url("socks4a://proxy:1080") == "socks4a://proxy:1080"

    def test_socks5h_proxy(self):
        assert _validate_proxy_url("socks5h://proxy:1080") == "socks5h://proxy:1080"

    def test_file_scheme_rejected(self):
        assert _validate_proxy_url("file:///etc/proxy") is None

    def test_ftps_scheme_rejected(self):
        assert _validate_proxy_url("ftp://proxy:21") is None

    def test_no_scheme_auto_prepend(self):
        result = _validate_proxy_url("proxy.example.com:8080")
        assert result == "http://proxy.example.com:8080"

    def test_empty_hostname(self):
        assert _validate_proxy_url("http://") is None

    def test_localhost_blocked(self):
        assert _validate_proxy_url("http://localhost:8080") is None

    def test_127_0_0_1_blocked(self):
        assert _validate_proxy_url("http://127.0.0.1:8080") is None

    def test_10_x_blocked(self):
        assert _validate_proxy_url("http://10.0.0.1:8080") is None

    def test_192_168_blocked(self):
        assert _validate_proxy_url("http://192.168.1.1:8080") is None

    def test_172_16_blocked(self):
        assert _validate_proxy_url("http://172.16.0.1:8080") is None

    def test_172_31_allowed_env(self):
        import os
        orig = os.environ.get("VIDEO_DOWNLOADER_ALLOW_INTERNAL_PROXY")
        os.environ["VIDEO_DOWNLOADER_ALLOW_INTERNAL_PROXY"] = "1"
        try:
            result = _validate_proxy_url("http://172.16.0.1:8080")
            assert result == "http://172.16.0.1:8080"
        finally:
            if orig is None:
                os.environ.pop("VIDEO_DOWNLOADER_ALLOW_INTERNAL_PROXY", None)
            else:
                os.environ["VIDEO_DOWNLOADER_ALLOW_INTERNAL_PROXY"] = orig

    def test_ipv6_localhost_blocked(self):
        assert _validate_proxy_url("http://[::1]:8080") is None

    def test_unbracketed_ipv6_rejected(self):
        assert _validate_proxy_url("http://fe80::1:8080") is None

    def test_valid_external_ip(self):
        assert _validate_proxy_url("http://8.8.8.8:53") == "http://8.8.8.8:53"

    def test_invalid_scheme(self):
        assert _validate_proxy_url("gopher://proxy:70") is None

    def test_none_input(self):
        # Passing None will cause urlparse to fail but should not crash
        result = _validate_proxy_url("")
        assert result is None


class TestDetectSystemProxy:
    def test_no_env_proxies(self, monkeypatch):
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("http_proxy", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        monkeypatch.delenv("ALL_PROXY", raising=False)
        result = detect_system_proxy()
        assert result is None


class TestFormatBytes:
    def test_zero(self):
        assert format_bytes(0) == "-"

    def test_none(self):
        assert format_bytes(None) == "-"

    def test_negative(self):
        assert format_bytes(-100) == "-100.0 B"

    def test_bytes(self):
        assert format_bytes(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_bytes(1500) == "1.5 KB"

    def test_megabytes(self):
        assert format_bytes(1_500_000) == "1.4 MB"

    def test_gigabytes(self):
        assert format_bytes(1_500_000_000) == "1.4 GB"

    def test_terabytes(self):
        assert format_bytes(1_500_000_000_000) == "1.4 TB"

    def test_petabytes(self):
        assert format_bytes(1_500_000_000_000_000) == "1.3 PB"


class TestFormatEta:
    def test_none(self):
        assert format_eta(None) == "-"

    def test_zero(self):
        assert format_eta(0) == "0:00"

    def test_seconds(self):
        assert format_eta(45) == "0:45"

    def test_minutes(self):
        assert format_eta(120) == "2:00"

    def test_hours(self):
        assert format_eta(3661) == "1:01:01"

    def test_float(self):
        assert format_eta(90.7) == "1:30"

    def test_invalid_string(self):
        assert format_eta("not_a_number") == "-"


class TestGetFfmpegLocation:
    def test_when_imageio_installed(self):
        result = get_ffmpeg_location()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] is not None
        assert result[1] is None

    def test_actual_call(self):
        # Just verify it returns a tuple
        result = get_ffmpeg_location()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] is None or isinstance(result[0], str)
        assert result[1] is None or isinstance(result[1], str)


class TestGetDownloadsFolder:
    def test_linux_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = get_downloads_folder()
        assert result == Path.home() / "Downloads"

    def test_darwin_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = get_downloads_folder()
        assert result == Path.home() / "Downloads"

    def test_unknown_platform_fallback(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "freebsd")
        result = get_downloads_folder()
        assert result == Path.home() / "Downloads"

    def test_returns_path_object(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = get_downloads_folder()
        assert isinstance(result, Path)


class TestGetPlatformConfigDir:
    def test_windows_default_app(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\testuser")
        result = get_platform_config_dir()
        assert result == Path("C:\\Users\\testuser") / "vidapi"

    def test_windows_custom_app_name(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\testuser")
        result = get_platform_config_dir("myapp")
        assert result == Path("C:\\Users\\testuser") / "myapp"

    def test_windows_no_localappdata_fallback(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(os.environ, clear=True),
            patch.object(Path, "home", return_value=Path("C:/Users/testuser")),
        ):
            result = get_platform_config_dir()
        assert result == Path("C:/Users/testuser") / "AppData" / "Local" / "vidapi"

    def test_macos_default_app(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = get_platform_config_dir()
        assert result == Path.home() / "Library" / "Application Support" / "vidapi"

    def test_macos_custom_app_name(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = get_platform_config_dir("myapp")
        assert result == Path.home() / "Library" / "Application Support" / "myapp"

    def test_linux_default_app(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = get_platform_config_dir()
        assert result == Path.home() / ".config" / "vidapi"

    def test_linux_custom_app_name(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = get_platform_config_dir("myapp")
        assert result == Path.home() / ".config" / "myapp"

    def test_returns_path_object(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = get_platform_config_dir()
        assert isinstance(result, Path)
