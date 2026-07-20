"""yt-dlp format selector and description utilities."""

import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────

DOWNLOAD_MODE_AV = "完整视频（画面+声音）"
DOWNLOAD_MODE_VIDEO_ONLY = "仅视频（无声音）"
DOWNLOAD_MODE_AUDIO_ONLY = "仅音频"
DOWNLOAD_MODE_OPTIONS = [
    DOWNLOAD_MODE_AV,
    DOWNLOAD_MODE_VIDEO_ONLY,
    DOWNLOAD_MODE_AUDIO_ONLY,
]

QUALITY_OPTIONS = [
    "最佳",
    "2160p / 4K",
    "1440p / 2K",
    "1080p",
    "720p",
    "480p",
    "360p",
]

# Subtitle options
SUBTITLE_LANG_ZH = "zh"  # Chinese (native)
SUBTITLE_LANG_EN = "en"  # English (native)
SUBTITLE_LANG_ZH_HANS = "zh-Hans"  # Chinese Simplified
SUBTITLE_LANG_ZH_HANT = "zh-Hant"  # Chinese Traditional

# Map UI labels (Chinese) to yt-dlp language codes
# "中英双语" = Chinese + English native subtitles (no auto-generated)
# "中文" = Chinese native subtitles
# "英文" = English native subtitles
SUBTITLE_LANG_MAP = {
    "中英双语": [SUBTITLE_LANG_ZH_HANS, SUBTITLE_LANG_ZH, SUBTITLE_LANG_EN],
    "中文": [SUBTITLE_LANG_ZH_HANS, SUBTITLE_LANG_ZH],
    "英文": [SUBTITLE_LANG_EN],
}


# ── Helpers ──────────────────────────────────────────────────────────


def quality_to_height(quality_label: str) -> int | None:
    if quality_label == "最佳":
        return None
    match = re.search(r"(\d+)p", quality_label)
    return int(match.group(1)) if match else None


def build_format_selector(download_mode: str, quality_label: str) -> str:
    """
    Map UI choices to yt-dlp format selectors.

    Notes:
    - height<=N means "use this resolution or lower", so 1080p will not pick 4K.
    - Audio-only ignores the quality option.
    - Video-only prefers streams with no audio.
    """
    height = quality_to_height(quality_label)

    if download_mode == DOWNLOAD_MODE_AUDIO_ONLY:
        return "ba/bestaudio"

    if download_mode == DOWNLOAD_MODE_VIDEO_ONLY:
        if height:
            return f"bv*[acodec=none][height<={height}]/bestvideo[height<={height}]/bv*[height<={height}]"
        return "bv*[acodec=none]/bestvideo/bv*"

    if download_mode != DOWNLOAD_MODE_AV:
        logger.warning(
            "Unknown download_mode: %r, falling back to %r", download_mode, DOWNLOAD_MODE_AV
        )

    # Default: complete video, merge best video + best audio when needed.
    if height:
        return f"bv*[height<={height}]+ba/b[height<={height}]/best[height<={height}]"
    return "bv*+ba/b"


def build_subtitle_opts(subtitle_language: str, embed_subtitles: bool) -> dict[str, Any]:
    """
    Build yt-dlp subtitle options.

    yt-dlp subtitle pool (YoutubeDL._process_subtitles):
      available = manual_subs + (automatic_subs if writeautomaticsub else [])
    then subtitleslangs filters that pool. So if writeautomaticsub is False,
    YouTube auto-translated tracks are NEVER in the pool — a request for
    "zh-Hans" on an English-native video yields no file even though YouTube
    can auto-translate. That was the user-reported "no subtitles downloaded"
    bug: the prior code hardcoded writeautomaticsub=False for every real
    SubtitleLanguage value.

    Fix: always enable writeautomaticsub. yt-dlp writes manual + auto as
    separate sidecars when both exist for the same lang; players pick one
    track, so the duplicate-track concern is a ux preference, not a defect,
    and beats silently dropping the user's chosen language.
    """
    lang_codes = SUBTITLE_LANG_MAP.get(subtitle_language, [])

    opts: dict[str, Any] = {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "srt",
    }

    if lang_codes:
        opts["subtitleslangs"] = lang_codes
    else:
        # Unknown/GUI-missing language: pull everything yt-dlp can.
        opts["subtitleslangs"] = ["all"]

    if embed_subtitles:
        opts["embedsubtitles"] = True
        opts["merge_output_format"] = "mp4"

    return opts


# ── Describe / introspect yt-dlp info dicts ───────────────────────────

FormatDict = dict[str, Any]


def describe_format(format_info: FormatDict) -> str:
    format_id = format_info.get("format_id") or "?"
    ext = format_info.get("ext") or "?"
    note = format_info.get("format_note") or ""
    resolution = format_info.get("resolution") or ""
    height = format_info.get("height")
    fps = format_info.get("fps")
    tbr = format_info.get("tbr")
    vcodec = format_info.get("vcodec") or "?"
    acodec = format_info.get("acodec") or "?"

    if not resolution and height:
        resolution = f"{height}p"
    if fps:
        resolution = (resolution + f"{fps:g}fps").strip()

    bits = [str(format_id), ext]
    if resolution:
        bits.append(str(resolution))
    if note:
        bits.append(str(note))
    if tbr:
        bits.append(f"{tbr:g}k")
    bits.append(f"v:{vcodec}")
    bits.append(f"a:{acodec}")
    return " / ".join(bits)


def selected_video_height(info: FormatDict | None) -> int | None:
    if not isinstance(info, dict):
        return None
    formats = info.get("requested_formats") or [info]
    heights: list[int] = [
        h
        for f in formats
        if isinstance(f, dict) and f.get("vcodec") not in (None, "none")
        for h in (f.get("height"),)
        if isinstance(h, int)
    ]
    return max(heights) if heights else None


def describe_selected_formats(info: FormatDict | None) -> str | None:
    if not isinstance(info, dict):
        return None

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        return f"播放列表/合集任务，条目数: {len(entries)}"

    requested_formats = info.get("requested_formats")
    if requested_formats:
        return "实际下载格式: " + " + ".join(
            describe_format(f) for f in requested_formats if isinstance(f, dict)
        )

    return "实际下载格式: " + describe_format(info)
