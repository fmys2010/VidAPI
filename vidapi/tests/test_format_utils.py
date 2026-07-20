"""Error tests for format utils: quality_to_height, build_format_selector, describe functions."""

from __future__ import annotations

import pytest

from vidapi.core.format_utils import (
    DOWNLOAD_MODE_AUDIO_ONLY,
    DOWNLOAD_MODE_AV,
    DOWNLOAD_MODE_VIDEO_ONLY,
    SUBTITLE_LANG_MAP,
    build_format_selector,
    build_subtitle_opts,
    quality_to_height,
    describe_format,
    describe_selected_formats,
    selected_video_height,
)
# ponytail: tests share the real SubtitleLanguage enum so drifting string
# literals (the bug class that broke subtitle download) trip a test, not a user.
from vidapi.models import SubtitleLanguage


class TestQualityToHeight:
    def test_best_returns_none(self):
        assert quality_to_height("最佳") is None

    def test_1080p(self):
        assert quality_to_height("1080p") == 1080

    def test_720p(self):
        assert quality_to_height("720p") == 720

    def test_4k_label(self):
        assert quality_to_height("2160p / 4K") == 2160

    def test_2k_label(self):
        assert quality_to_height("1440p / 2K") == 1440

    def test_360p(self):
        assert quality_to_height("360p") == 360

    def test_invalid_label_returns_none(self):
        assert quality_to_height("super_quality") is None

    def test_empty_string_returns_none(self):
        assert quality_to_height("") is None

    def test_chinese_label_returns_none(self):
        assert quality_to_height("高清") is None


class TestBuildFormatSelector:
    def test_audio_only_mode(self):
        result = build_format_selector(DOWNLOAD_MODE_AUDIO_ONLY, "1080p")
        assert result == "ba/bestaudio"

    def test_video_only_with_height(self):
        result = build_format_selector(DOWNLOAD_MODE_VIDEO_ONLY, "1080p")
        assert "height<=1080" in result

    def test_video_only_without_height(self):
        result = build_format_selector(DOWNLOAD_MODE_VIDEO_ONLY, "最佳")
        assert "acodec=none" in result

    def test_av_mode_with_height(self):
        result = build_format_selector(DOWNLOAD_MODE_AV, "720p")
        assert "height<=720" in result

    def test_av_mode_best(self):
        result = build_format_selector(DOWNLOAD_MODE_AV, "最佳")
        assert result == "bv*+ba/b"

    def test_unknown_mode_falls_through(self):
        # Unknown mode shouldn't crash
        result = build_format_selector("unknown_mode", "1080p")
        # Should fall through to default path
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_download_mode(self):
        result = build_format_selector("", "1080p")
        assert isinstance(result, str)

    def test_empty_quality_label(self):
        result = build_format_selector(DOWNLOAD_MODE_AV, "")
        assert isinstance(result, str)


class TestDescribeFormat:
    def test_minimal_format_dict(self):
        result = describe_format({})
        assert "?" in result  # format_id defaults to "?"

    def test_full_format_dict(self):
        fmt = {
            "format_id": "137",
            "ext": "mp4",
            "height": 1080,
            "fps": 30,
            "tbr": 5000,
            "vcodec": "avc1",
            "acodec": "none",
        }
        result = describe_format(fmt)
        assert "137" in result
        assert "mp4" in result
        assert "1080p" in result

    def test_none_vcodec(self):
        result = describe_format({"format_id": "1", "vcodec": None})
        assert "v:?" in result

    def test_none_acodec(self):
        result = describe_format({"format_id": "1", "acodec": None})
        assert "a:?" in result


class TestSelectedVideoHeight:
    def test_none_input(self):
        assert selected_video_height(None) is None

    def test_non_dict_input(self):
        assert selected_video_height("string") is None

    def test_dict_with_height(self):
        info = {"requested_formats": [{"height": 1080, "vcodec": "avc1"}]}
        assert selected_video_height(info) == 1080

    def test_dict_without_height(self):
        info = {"requested_formats": [{"format_id": "1"}]}
        assert selected_video_height(info) is None

    def test_dict_with_none_vcodec_filtered(self):
        info = {"requested_formats": [{"height": 720, "vcodec": None}]}
        assert selected_video_height(info) is None

    def test_multiple_formats_returns_max(self):
        info = {
            "requested_formats": [
                {"height": 360, "vcodec": "avc1"},
                {"height": 1080, "vcodec": "vp9"},
            ]
        }
        assert selected_video_height(info) == 1080

    def test_audio_only_format(self):
        info = {"requested_formats": [{"height": None, "vcodec": "none"}]}
        assert selected_video_height(info) is None


class TestDescribeSelectedFormats:
    def test_none_input(self):
        assert describe_selected_formats(None) is None

    def test_non_dict_input(self):
        assert describe_selected_formats("x") is None

    def test_playlist_info(self):
        info = {"_type": "playlist", "entries": [1, 2, 3]}
        result = describe_selected_formats(info)
        assert "3" in result  # item count

    def test_requested_formats(self):
        info = {
            "requested_formats": [
                {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "aac"},
            ]
        }
        result = describe_selected_formats(info)
        assert "实际下载格式" in result

    def test_simple_info(self):
        info = {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "mp4a"}
        result = describe_selected_formats(info)
        assert "实际下载格式" in result


class TestBuildSubtitleOptsRegression:
    """Lock the subtitle-download contract. The original bug: GUI picked
    ``SubtitleLanguage.ZH_EN`` ("中英双语"), but the target YouTube video had
    only English native subtitles (no zh-Hans native). The opts produced by
    build_subtitle_opts requested ONLY native subs (writeautomaticsub=False),
    so no Chinese subtitle file ever landed on disk. These tests pin the
    contract for every value in SubtitleLanguage so a future drift fails
    here rather than silently dropping subtitles again."""

    @pytest.mark.parametrize("lang_enum", list(SubtitleLanguage))
    def test_writesubtitles_always_true(self, lang_enum: SubtitleLanguage):
        opts = build_subtitle_opts(lang_enum.value, embed_subtitles=False)
        assert opts.get("writesubtitles") is True, (lang_enum, opts)

    @pytest.mark.parametrize("lang_enum", list(SubtitleLanguage))
    def test_subtitleslangs_is_real_lang_code_not_ghost_string(self, lang_enum: SubtitleLanguage):
        """Regression: the GUI default and TaskManager default used to be
        "原生" / "中英双语（优先原生字幕）" — strings absent from SUBTITLE_LANG_MAP,
        causing the else-branch to request subtitleslangs=["all"] which on
        YouTube silently yields no sidecar for videos whose native lang is
        not in the auto list. Every enum value MUST hit a real SUBTITLE_LANG_MAP
        entry so the user gets the language they picked."""
        opts = build_subtitle_opts(lang_enum.value, embed_subtitles=False)
        langs = opts.get("subtitleslangs")
        assert langs and langs != ["all"], (lang_enum, opts)
        assert lang_enum.value in SUBTITLE_LANG_MAP, (
            f"SubtitleLanguage.{lang_enum.name}='{lang_enum.value}' has no "
            f"SUBTITLE_LANG_MAP entry — build_subtitle_opts will fall through "
            f"to the ['all'] branch and drop subtitles"
        )

    def test_zh_en_requests_auto_translated_zh_for_en_native_video(self):
        """The reported bug. For "中英双语" the opts must enable automatic
        subtitle download so an English-native YouTube video still yields a
        Chinese subtitle sidecar (auto-translated by YouTube), not only the
        English native one. Without writeautomaticsub=True, yt-dlp finds no
        zh-Hans native sub and writes nothing for that language."""
        opts = build_subtitle_opts(SubtitleLanguage.ZH_EN.value, embed_subtitles=False)
        assert opts.get("writeautomaticsub") is True, opts
        assert "zh-Hans" in opts.get("subtitleslangs", [])
        assert "en" in opts.get("subtitleslangs", [])

    @pytest.mark.parametrize("lang_enum", list(SubtitleLanguage))
    def test_no_ghost_string_default_leaks_in(self, lang_enum: SubtitleLanguage):
        """Regression guard: the in-source ghost strings
        "自动（视频默认语言）" and "中英双语（优先原生字幕）" appeared as default
        arg values and branch comparisons but were never valid enum values.
        Building opts for every real enum value must never produce the
        else-branch ["all"] marker, which is the silent-drop signature."""
        opts = build_subtitle_opts(lang_enum.value, embed_subtitles=True)
        assert opts.get("subtitleslangs") != ["all"], (lang_enum, opts)
        assert "自动（视频默认语言）" not in opts.values()
        assert "中英双语（优先原生字幕）" not in opts.values()
