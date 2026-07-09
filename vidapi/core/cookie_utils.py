"""Cross-platform BiliBili browser cookie extraction utilities.

Extracted from app.py. No yt-dlp import at module level — lazy-imported
inside functions that need it.
"""

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BILIBILI_COOKIE_CANDIDATES: list[tuple[str, str, str | None]] = [
    ("Edge", "edge", None),
    ("Chrome", "chrome", None),
    ("Firefox", "firefox", None),
    ("Brave", "brave", None),
    ("Chromium", "chromium", None),
    ("Opera", "opera", None),
    ("Vivaldi", "vivaldi", None),
]

BILIBILI_LOGIN_COOKIE_NAMES: set[str] = {"SESSDATA"}

BILIBILI_NAV_API: str = "https://api.bilibili.com/x/web-interface/nav"


# ---------------------------------------------------------------------------
# Internal helpers — profile directory discovery
# ---------------------------------------------------------------------------

def _existing_unique_dirs(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            logger.debug("cannot resolve path: %s", path, exc_info=True)
            resolved = path.expanduser()
        key = str(resolved).lower()
        if key not in seen and resolved.exists() and resolved.is_dir():
            seen.add(key)
            result.append(resolved)
    return result


def _firefox_like_profile_dirs(profile_roots: list[Path]) -> list[Path]:
    profiles: list[Path] = []
    for root in _existing_unique_dirs(profile_roots):
        if (root / "cookies.sqlite").exists():
            profiles.append(root)
        for pattern in ("*", "Profiles/*"):
            try:
                for child in root.glob(pattern):
                    if child.is_dir() and (child / "cookies.sqlite").exists():
                        profiles.append(child)
            except OSError:
                logger.debug("cannot glob profile dir: %s", root, exc_info=True)
    return _existing_unique_dirs(profiles)


def _chromium_profile_dirs(user_data_roots: list[Path]) -> list[Path]:
    profiles: list[Path] = []
    for root in _existing_unique_dirs(user_data_roots):
        try:
            children = list(root.iterdir())
        except OSError:
            logger.debug("cannot iterate browser dir: %s", root, exc_info=True)
            children = []

        for child in children:
            if not child.is_dir():
                continue
            if (child / "Network" / "Cookies").exists() or (child / "Cookies").exists():
                profiles.append(child)

    return _existing_unique_dirs(profiles)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_bilibili_cookie_candidates() -> list[tuple[str, str, str | None]]:
    """Return standard browser cookie candidates (no Zen/Arc)."""
    return list(BILIBILI_COOKIE_CANDIDATES)


def cookie_candidate_to_spec(browser_name: str, profile: str | None) -> tuple[str, ...]:
    """Convert a (name, browser, profile) candidate to a yt-dlp spec tuple."""
    return (browser_name, profile) if profile else (browser_name,)


def is_bilibili_cookie(cookie) -> bool:
    """Return True if *cookie* belongs to the bilibili.com domain."""
    domain = (getattr(cookie, "domain", "") or "").lower().lstrip(".")
    return domain == "bilibili.com" or domain.endswith(".bilibili.com")


def inspect_bilibili_cookie_jar(cookie_jar) -> dict:
    """Inspect a cookie jar for BiliBili cookies without exposing values.

    Returns a dict with keys: count, names, missing, has_login_cookie, expires_at.
    """
    cookies = [cookie for cookie in cookie_jar if is_bilibili_cookie(cookie)]
    names = {cookie.name for cookie in cookies}
    missing = sorted(BILIBILI_LOGIN_COOKIE_NAMES - names)
    expires_values = [
        int(cookie.expires)
        for cookie in cookies
        if cookie.name in BILIBILI_LOGIN_COOKIE_NAMES and getattr(cookie, "expires", None)
    ]
    expires_at = min(expires_values) if expires_values else None
    return {
        "count": len(cookies),
        "names": names,
        "missing": missing,
        "has_login_cookie": not missing,
        "expires_at": expires_at,
    }


def build_cookie_header(cookie_jar, host: str) -> str:
    """Build a ``Cookie:`` header string from *cookie_jar* for *host*."""
    host = host.lower()
    parts: list[str] = []
    seen: set[str] = set()
    for cookie in cookie_jar:
        domain = (getattr(cookie, "domain", "") or "").lower().lstrip(".")
        if not domain:
            continue
        if host != domain and not host.endswith("." + domain):
            continue
        if cookie.name in seen:
            continue
        seen.add(cookie.name)
        parts.append(f"{cookie.name}={cookie.value}")
    return "; ".join(parts)


def verify_bilibili_cookie_jar(cookie_jar, proxy: str | None = None, timeout: int = 10) -> dict:
    """Test BiliBili login state without exposing raw cookie values.

    Returns a dict: ok (bool), online (bool), message (str).
    """
    local = inspect_bilibili_cookie_jar(cookie_jar)
    if not local["has_login_cookie"]:
        return {
            "ok": False,
            "online": False,
            "message": f"未发现完整 B 站登录 Cookies，缺少: {', '.join(local['missing'])}",
        }

    cookie_header = build_cookie_header(cookie_jar, "api.bilibili.com")
    if not cookie_header:
        return {"ok": False, "online": False, "message": "未能生成 B 站 Cookie 请求头"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
        "Cookie": cookie_header,
    }

    try:
        opener_args = []
        if proxy:
            opener_args.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*opener_args)
        req = urllib.request.Request(BILIBILI_NAV_API, headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError) as exc:
        logger.debug("bilibili nav API test failed: %s", exc)
        return {
            "ok": True,
            "online": False,
            "message": f"本地 Cookies 看起来完整，但在线测试失败: {exc}",
        }

    data = payload.get("data") or {}
    if payload.get("code") == 0 and data.get("isLogin"):
        uname = data.get("uname") or "已登录账号"
        vip_label = "大会员" if (data.get("vipStatus") or data.get("vip", {}).get("status")) else "普通账号"
        return {"ok": True, "online": True, "message": f"在线测试成功：{uname} / {vip_label}"}

    code = payload.get("code")
    msg = payload.get("message") or payload.get("msg") or "未登录"
    return {"ok": False, "online": True, "message": f"在线测试未登录：code={code}, message={msg}"}