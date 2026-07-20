"""Error tests for URL utils: extract_urls, classify_site, normalize_url, extract_concatenated_urls."""

from __future__ import annotations


from vidapi.core.url_utils import (
    classify_site,
    extract_concatenated_urls,
    extract_urls,
    normalize_url,
)


class TestNormalizeUrl:
    def test_trims_whitespace(self):
        assert normalize_url("  https://youtube.com/watch?v=x  ") == "https://youtube.com/watch?v=x"

    def test_strips_trailing_punctuation(self):
        assert normalize_url("https://youtube.com/watch?v=x,") == "https://youtube.com/watch?v=x"
        assert normalize_url("https://youtube.com/watch?v.x)") == "https://youtube.com/watch?v.x"

    def test_prepends_https_to_www(self):
        assert normalize_url("www.youtube.com/watch?v=x") == "https://www.youtube.com/watch?v=x"

    def test_empty_string(self):
        assert normalize_url("") == ""

    def test_over_2048_chars_returns_empty(self):
        long = "https://example.com/" + "a" * 3000
        assert normalize_url(long) == ""

    def test_unicode_domain(self):
        result = normalize_url("https://münchen.example.com/video")
        assert result != ""


class TestExtractUrls:
    def test_single_youtube_url(self):
        urls = extract_urls("Check this out: https://www.youtube.com/watch?v=dQw4w9WgXcQ cool")
        assert len(urls) == 1
        assert "youtube.com" in urls[0]

    def test_single_bilibili_url(self):
        urls = extract_urls("https://www.bilibili.com/video/BV1xx4y1XX77")
        assert len(urls) == 1

    def test_short_bilibili_url(self):
        urls = extract_urls("https://b23.tv/abc123")
        assert len(urls) == 1

    def test_multiple_urls(self):
        text = "https://www.youtube.com/watch?v=111 and https://www.bilibili.com/video/BV222"
        urls = extract_urls(text)
        assert len(urls) == 2

    def test_no_url_in_text(self):
        assert extract_urls("Hello world, no urls here!") == []

    def test_malformed_url_missing_scheme(self):
        # www. prefix should be handled
        urls = extract_urls("www.youtube.com/watch?v=abc")
        assert len(urls) == 1

    def test_url_with_special_chars_in_path(self):
        urls = extract_urls("https://www.bilibili.com/bangumi/play/ep12345")
        assert len(urls) == 1

    def test_url_truncated_by_punctuation(self):
        urls = extract_urls("Visit https://www.youtube.com/watch?v=abc.)")
        assert len(urls) == 1
        assert urls[0].endswith("abc")

    def test_duplicate_urls_only_one(self):
        urls = extract_urls("https://youtube.com/watch?v=x https://youtube.com/watch?v=x")
        assert len(urls) == 1

    def test_ipv6_url(self):
        urls = extract_urls("http://[::1]:8000/video")
        assert len(urls) == 1

    def test_url_with_fragment(self):
        urls = extract_urls("https://www.youtube.com/watch?v=abc&t=10#section")
        assert len(urls) == 1

    def test_empty_input(self):
        assert extract_urls("") == []


class TestClassifySite:
    def test_youtube_watch(self):
        assert classify_site("https://www.youtube.com/watch?v=abc") == "Youtube"

    def test_youtu_be(self):
        assert classify_site("https://youtu.be/abc123") == "Youtube"

    def test_youtube_short(self):
        assert classify_site("https://www.youtube.com/shorts/abc") == "Youtube"

    def test_youtube_live(self):
        assert classify_site("https://www.youtube.com/live/abc") == "Youtube"

    def test_youtube_playlist(self):
        assert classify_site("https://www.youtube.com/playlist?list=abc") == "Youtube"

    def test_youtube_nocookie(self):
        assert classify_site("https://www.youtube-nocookie.com/embed/abc") == "Youtube"

    def test_music_youtube(self):
        assert classify_site("https://music.youtube.com/watch?v=abc") == "Youtube"

    def test_subdomain_youtube(self):
        assert classify_site("https://gaming.youtube.com/watch?v=abc") == "Youtube"

    def test_bilibili_video(self):
        assert classify_site("https://www.bilibili.com/video/BV1xx") == "BiliBili"

    def test_bilibili_bangumi(self):
        assert classify_site("https://www.bilibili.com/bangumi/play/abc") == "BiliBili"

    def test_bilibili_short(self):
        assert classify_site("https://b23.tv/xyz") == "BiliBili"

    def test_bilibili_live(self):
        assert classify_site("https://www.bilibili.com/live/abc") == "BiliBili"

    def test_unknown_site_returns_none(self):
        assert classify_site("https://www.vimeo.com/12345") is None

    def test_random_string_returns_none(self):
        assert classify_site("not a url") is None

    def test_empty_string_returns_none(self):
        assert classify_site("") is None

    def test_http_vs_https(self):
        assert classify_site("http://www.youtube.com/watch?v=abc") == "Youtube"
        assert classify_site("http://www.bilibili.com/video/BV1xx") == "BiliBili"

    def test_url_with_auth(self):
        # URL with embedded credentials
        assert classify_site("https://user:pass@www.youtube.com/watch?v=abc") == "Youtube"

    def test_invalid_url_raises_nothing(self):
        # Should not throw
        result = classify_site("<<<invalid>>>")
        assert result is None


class TestExtractConcatenatedUrls:
    def test_two_youtube_urls_concatenated(self):
        text = "https://www.youtube.com/watch?v=aaahttps://www.youtube.com/watch?v=bbb"
        urls = extract_concatenated_urls(text)
        assert len(urls) >= 1

    def test_youtube_and_bilibili_concatenated(self):
        text = "https://www.youtube.com/watch?v=aaahttps://www.bilibili.com/video/BV1xx"
        urls = extract_concatenated_urls(text)
        assert len(urls) >= 1

    def test_normal_separated_urls(self):
        text = "https://www.youtube.com/watch?v=aaa and https://www.bilibili.com/video/BV1xx"
        urls = extract_concatenated_urls(text)
        assert len(urls) == 2

    def test_no_valid_urls(self):
        assert extract_concatenated_urls("hello world") == []

    def test_single_url(self):
        text = "https://www.youtube.com/watch?v=aaa"
        urls = extract_concatenated_urls(text)
        assert len(urls) == 1
