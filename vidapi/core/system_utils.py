"""Cross-platform system utilities for Video Downloader.

No project imports — only stdlib + imageio_ffmpeg.
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path
import sys
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_downloads_folder() -> Path:
    """Return the user's Downloads folder, cross-platform.

    On Windows, uses SHGetKnownFolderPath with FOLDERID_Downloads
    to correctly handle localized folder names (e.g. "下载", "Descargas").
    Falls back to ~/Downloads if the API fails.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
            FOLDERID_Downloads = ctypes.GUID(
                0x374DE290, 0x123F, 0x4565, 0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B
            )

            SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            SHGetKnownFolderPath.argtypes = [
                ctypes.POINTER(ctypes.GUID),  # rfid
                wintypes.DWORD,               # dwFlags
                wintypes.HANDLE,              # hToken
                ctypes.POINTER(wintypes.LPWSTR)  # ppszPath
            ]
            SHGetKnownFolderPath.restype = wintypes.HRESULT

            KF_FLAG_DEFAULT = 0x00000000
            path_ptr = wintypes.LPWSTR()
            hr = SHGetKnownFolderPath(
                ctypes.byref(FOLDERID_Downloads),
                KF_FLAG_DEFAULT,
                None,
                ctypes.byref(path_ptr)
            )
            if hr == 0:  # S_OK
                path = Path(path_ptr.value)
                # CoTaskMemFree the returned string
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                return path
            else:
                logger.debug("SHGetKnownFolderPath failed with HRESULT: 0x%08X", hr)
        except Exception as e:
            logger.debug("Failed to get Downloads folder via WinAPI: %s", e)

    # Fallback for non-Windows or if WinAPI fails
    return Path.home() / "Downloads"


def _validate_proxy_url(proxy: str) -> str | None:
    """Validate proxy URL to prevent SSRF.

    Only allows http/https/socks schemes. Rejects file://, ftp://, etc.
    Blocks internal IPs (localhost, link-local, private ranges) unless explicitly allowed.
    """
    try:
        parsed = urlparse(proxy)

        # urlparse treats "host:port" as scheme="host", path="port"
        # Detect this by checking if "scheme" contains dots (looks like a hostname)
        scheme = parsed.scheme.lower()
        if "." in scheme and not any(scheme.startswith(s) for s in ("http", "https", "socks4", "socks5", "socks4a", "socks5h")):
            # No scheme detected, prepend http://
            proxy = f"http://{proxy}"
            parsed = urlparse(proxy)

        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https", "socks4", "socks5", "socks4a", "socks5h"):
            logger.warning("Rejected proxy with invalid scheme: %s", scheme)
            return None

        hostname = parsed.hostname or ""
        if not hostname:
            logger.warning("Rejected proxy with empty hostname")
            return None

        # Reject unbracketed IPv6 in URL (e.g. http://fe80::1:8080)
        # urlparse is lenient with IPv6, but RFC 3986 requires brackets.
        # Netloc with >1 colon and no brackets = unbracketed IPv6.
        netloc = parsed.netloc
        if netloc.count(":") > 1 and "[" not in netloc:
            logger.warning("Rejected proxy with unbracketed IPv6: %s", proxy)
            return None

        # Block localhost and internal IPs (SSRF protection)
        # Allow override via environment variable for legitimate internal proxies
        import os
        if os.environ.get("VIDEO_DOWNLOADER_ALLOW_INTERNAL_PROXY") != "1":
            blocked_patterns = [
                r"^127\.",           # 127.0.0.0/8
                r"^10\.",            # 10.0.0.0/8
                r"^172\.(1[6-9]|2[0-9]|3[0-1])\.",  # 172.16.0.0/12
                r"^192\.168\.",      # 192.168.0.0/16
                r"^169\.254\.",      # 169.254.0.0/16 (link-local)
                r"^::1$",            # IPv6 localhost
                r"^fe80::",          # IPv6 link-local
                r"^localhost$",      # localhost
            ]
            for pattern in blocked_patterns:
                if re.match(pattern, hostname, re.IGNORECASE):
                    logger.warning("Blocked internal proxy destination: %s", hostname)
                    return None

        return proxy
    except Exception as e:
        logger.debug("Proxy validation failed: %s", e)
        return None


def detect_system_proxy() -> str | None:
    """
    Python's urllib.request.getproxies() reads environment proxies and,
    on Windows, the current user's Internet Settings registry keys.

    yt-dlp accepts one proxy URL for all traffic. Prefer HTTPS, then HTTP.
    """
    proxies = urllib.request.getproxies()
    for key in ("https", "http", "all", "socks"):
        proxy = proxies.get(key)
        if proxy:
            proxy = proxy.strip()
            if "://" not in proxy:
                proxy = "http://" + proxy
            # Validate proxy URL to prevent SSRF
            validated = _validate_proxy_url(proxy)
            if validated:
                return validated
            # If validation fails, continue to next proxy
    return None


def get_ffmpeg_location() -> tuple[str | None, str | None]:
    """
    Use imageio-ffmpeg's bundled ffmpeg when available.
    If it is missing, yt-dlp will still try ffmpeg from PATH.

    Returns:
        tuple: (ffmpeg_path, error_message)
               error_message is None on success, or a user-friendly message on failure
    """
    try:
        import imageio_ffmpeg  # noqa: F811
        return imageio_ffmpeg.get_ffmpeg_exe(), None
    except ModuleNotFoundError:
        return None, "imageio-ffmpeg not installed. Run: pip install imageio-ffmpeg"
    except (AttributeError, OSError) as e:
        return None, f"imageio-ffmpeg error: {e}"


def format_bytes(num: float | int | None) -> str:
    if not num:
        return "-"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def format_eta(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "-"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"