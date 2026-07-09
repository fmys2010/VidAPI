"""URL parsing and site classification utilities."""

import logging
import re
from urllib.parse import ParseResult, urlparse

logger = logging.getLogger(__name__)


# Improved URL regex that handles:
# - IPv4 and IPv6 addresses
# - Internationalized domain names (IDN)
# - Unicode characters in paths
# - Proper handling of parentheses, brackets
# - Port numbers
URL_RE = re.compile(
    r"(?i)(?:https?://|www\.)"  # Scheme or www prefix
    r"(?:"  # Host alternatives
    r"(?:\[[0-9a-f:]+\])"  # IPv6 in brackets
    r"|"  # OR
    r"(?:\d{1,3}(?:\.\d{1,3}){3})"  # IPv4
    r"|"  # OR
    r"(?:[\w\u00A0-\uFFFF](?:[\w\u00A0-\uFFFF-]{0,61}[\w\u00A0-\uFFFF])?(?:\.[\w\u00A0-\uFFFF](?:[\w\u00A0-\uFFFF-]{0,61}[\w\u00A0-\uFFFF])?)*)"  # Domain with IDN support
    r")"
    r"(?::\d+)?"  # Optional port
    r"(?:[/?#][^\s]*)?"  # Path, query, fragment
)

TRAILING_PUNCTUATION = ".,;:!?，。；：！？、)]}>\"'"


# Known URL path prefixes for YouTube and BiliBili (used for concatenated URL splitting)
# Ordered by specificity - longer prefixes first to avoid partial matches
YOUTUBE_PATH_PREFIXES = (
    "youtube.com/watch?v=",
    "youtu.be/",
    "youtube-nocookie.com/",
    "music.youtube.com/",
    "youtube.com/shorts/",
    "youtube.com/live/",
    "youtube.com/playlist?list=",
)

BILIBILI_PATH_PREFIXES = (
    "b23.tv/",
    "bilibili.com/video/",
    "bilibili.com/bangumi/",
    "bilibili.com/live/",
    "bilibili.com/medialist/",
    "bilibili.com/read/",
)

# Combined regex for finding start positions of known video URLs
# Matches: https?:// or www. followed by known host + path prefix
CONCAT_URL_RE = re.compile(
    r"(?i)(?:https?://|www\.)"
    r"(?:"
    r"(?:youtube\.com/(?:watch\?v=|shorts/|live/|playlist\?list=))"
    r"|(?:youtu\.be/)"
    r"|(?:youtube-nocookie\.com/)"
    r"|(?:music\.youtube\.com/)"
    r"|(?:b23\.tv/)"
    r"|(?:bilibili\.com/(?:video/|bangumi/|live/|medialist/|read/))"
    r")"
)


def _normalize_url(raw: str) -> str:
    url = raw.strip().rstrip(TRAILING_PUNCTUATION)
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def normalize_url(raw: str) -> str:
    if len(raw) > 2048:
        return ""
    return _normalize_url(raw)


def extract_urls(text: str) -> list[str]:
    seen = set()
    urls: list[str] = []
    for match in URL_RE.finditer(text):
        url = normalize_url(match.group(0))
        if url and url not in seen:
            # Validate the URL actually parses correctly
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    seen.add(url)
                    urls.append(url)
            except ValueError:
                continue
    return urls


def extract_concatenated_urls(text: str) -> list[str]:
    """
    Extract YouTube and BiliBili URLs from text even when concatenated without separators.
    
    Uses known URL path prefixes for these sites to identify boundaries.
    """
    # Try standard extraction first - if it finds multiple URLs, use those
    std_urls = extract_urls(text)
    std_valid = [u for u in std_urls if classify_site(u)]
    if len(std_valid) > 1:
        return std_valid
    
    # Find all start positions of known video URL patterns
    matches = list(CONCAT_URL_RE.finditer(text))
    if not matches:
        return std_valid
    
    # Extract URLs from each match start to next match start (or end of string)
    extracted: list[str] = []
    seen: set[str] = set()
    
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        candidate = text[start:end]
        url = normalize_url(candidate)
        
        if url and url not in seen:
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    # Verify it's actually a YouTube or BiliBili URL
                    if classify_site(url):
                        seen.add(url)
                        extracted.append(url)
            except ValueError:
                continue
    
    # If concatenated extraction found more valid URLs, use that
    if len(extracted) >= len(std_valid):
        return extracted
    
    return std_valid


def classify_site(url: str) -> str | None:
    try:
        parsed: ParseResult = urlparse(url)
        host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        logger.debug("invalid URL for classify_site: %r", url)
        return None

    if host == "b23.tv" or host.endswith(".b23.tv") or host == "bilibili.com" or host.endswith(".bilibili.com"):
        return "BiliBili"

    youtube_hosts = (
        "youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "music.youtube.com",
    )
    if host in youtube_hosts or host.endswith(".youtube.com") or host.endswith(".youtube-nocookie.com"):
        return "Youtube"

    return None