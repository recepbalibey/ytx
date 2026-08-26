"""Tests for URL detection and normalization."""

import pytest

from ytx.exceptions import URLError
from ytx.models import URLType
from ytx.youtube.urls import detect_url_type, extract_video_id


class TestDetectURLType:
    """Test URL type detection."""

    def test_bare_video_id(self):
        url_type, video_id = detect_url_type("dQw4w9WgXcQ")
        assert url_type == URLType.VIDEO
        assert video_id == "dQw4w9WgXcQ"

    def test_standard_watch_url(self):
        url_type, video_id = detect_url_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert url_type == URLType.VIDEO
        assert video_id == "dQw4w9WgXcQ"

    def test_short_url(self):
        url_type, video_id = detect_url_type("https://youtu.be/dQw4w9WgXcQ")
        assert url_type == URLType.VIDEO
        assert video_id == "dQw4w9WgXcQ"

    def test_embed_url(self):
        url_type, video_id = detect_url_type("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assert url_type == URLType.VIDEO
        assert video_id == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        url_type, video_id = detect_url_type(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        )
        # Has list param, so detected as playlist
        assert url_type == URLType.PLAYLIST

    def test_playlist_url(self):
        url_type, playlist_id = detect_url_type(
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        )
        assert url_type == URLType.PLAYLIST
        assert playlist_id == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"

    def test_channel_handle(self):
        url_type, handle = detect_url_type("https://www.youtube.com/@Computerphile")
        assert url_type == URLType.CHANNEL
        assert handle == "Computerphile"

    def test_channel_handle_no_www(self):
        url_type, handle = detect_url_type("https://youtube.com/@Computerphile")
        assert url_type == URLType.CHANNEL
        assert handle == "Computerphile"

    def test_channel_id_url(self):
        url_type, channel_id = detect_url_type(
            "https://www.youtube.com/channel/UC9-y-6csu5WGm29I7JiwpnA"
        )
        assert url_type == URLType.CHANNEL
        assert channel_id == "UC9-y-6csu5WGm29I7JiwpnA"

    def test_channel_custom_url(self):
        url_type, handle = detect_url_type("https://www.youtube.com/c/Computerphile")
        assert url_type == URLType.CHANNEL
        assert handle == "Computerphile"

    def test_invalid_url_raises(self):
        with pytest.raises(URLError):
            detect_url_type("https://example.com/not-youtube")

    @pytest.mark.parametrize(
        "url",
        [
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://example.com/playlist?list=PLtest",
            "https://youtu.be.evil.example/dQw4w9WgXcQ",
        ],
    )
    def test_lookalike_or_non_youtube_host_is_rejected(self, url):
        with pytest.raises(URLError, match="YouTube"):
            detect_url_type(url)

    def test_empty_url_raises(self):
        with pytest.raises(URLError):
            detect_url_type("")


class TestExtractVideoId:
    """Test video ID extraction."""

    def test_extract_from_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_from_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_from_playlist_returns_none(self):
        assert extract_video_id("https://www.youtube.com/playlist?list=PLtest") is None

    def test_extract_from_channel_returns_none(self):
        assert extract_video_id("https://www.youtube.com/@test") is None
