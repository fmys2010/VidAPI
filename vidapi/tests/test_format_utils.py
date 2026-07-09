"""Error tests for format utils: quality_to_height, build_format_selector, describe functions."""

from __future__ import annotations

import pytest

from vidapi.core.format_utils import (
    DOWNLOAD_MODE_AUDIO_ONLY,
    DOWNLOAD_MODE_AV,
    DOWNLOAD_MODE_VIDEO_ONLY,
    build_format_selector,
    quality_to_height,
    describe_format,
    describe_selected_formats,
    selected_video_height,
)


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
