"""vidapi.core - Core download engine modules."""

from .url_utils import extract_urls, classify_site, normalize_url, extract_concatenated_urls
from .format_utils import (
    build_format_selector,
    quality_to_height,
    describe_selected_formats,
    selected_video_height,
    build_subtitle_opts,
    DOWNLOAD_MODE_AV,
    DOWNLOAD_MODE_VIDEO_ONLY,
    DOWNLOAD_MODE_AUDIO_ONLY,
    DOWNLOAD_MODE_OPTIONS,
    QUALITY_OPTIONS,
)
from .cookie_utils import (
    get_bilibili_cookie_candidates,
    cookie_candidate_to_spec,
    inspect_bilibili_cookie_jar,
    verify_bilibili_cookie_jar,
    build_cookie_header,
    is_bilibili_cookie,
    BILIBILI_COOKIE_CANDIDATES,
)
from .system_utils import (
    get_downloads_folder,
    get_platform_config_dir,
    detect_system_proxy,
    get_ffmpeg_location,
    format_bytes,
    format_eta,
)
from .config import Config, get_config
from .workers import DownloadSession, CookieSession, QueueLogger
from .thread_runner import AsyncThreadRunner, SessionThreadRunner

__all__ = [
    # url_utils
    "extract_urls",
    "classify_site",
    "normalize_url",
    "extract_concatenated_urls",
    # format_utils
    "build_format_selector",
    "quality_to_height",
    "describe_selected_formats",
    "selected_video_height",
    "build_subtitle_opts",
    "DOWNLOAD_MODE_AV",
    "DOWNLOAD_MODE_VIDEO_ONLY",
    "DOWNLOAD_MODE_AUDIO_ONLY",
    "DOWNLOAD_MODE_OPTIONS",
    "QUALITY_OPTIONS",
    # cookie_utils
    "get_bilibili_cookie_candidates",
    "cookie_candidate_to_spec",
    "inspect_bilibili_cookie_jar",
    "verify_bilibili_cookie_jar",
    "build_cookie_header",
    "is_bilibili_cookie",
    "BILIBILI_COOKIE_CANDIDATES",
    # system_utils
    "get_downloads_folder",
    "get_platform_config_dir",
    "detect_system_proxy",
    "get_ffmpeg_location",
    "format_bytes",
    "format_eta",
    # config
    "Config",
    "get_config",
    # workers
    "DownloadSession",
    "CookieSession",
    "QueueLogger",
    # thread_runner
    "AsyncThreadRunner",
    "SessionThreadRunner",
]