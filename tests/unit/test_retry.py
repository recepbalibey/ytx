"""Tests for retry behavior in caption extraction."""

from unittest.mock import MagicMock, patch

from ytx.exceptions import CaptionAccessBlockedError
from ytx.transcripts.captions import _retry_with_backoff


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        func = MagicMock(return_value="result")
        result = _retry_with_backoff(func, "vid1")
        assert result == "result"
        assert func.call_count == 1

    def test_retries_on_request_blocked(self):
        from youtube_transcript_api._errors import RequestBlocked

        func = MagicMock(side_effect=[RequestBlocked("vid1"), "result"])
        with patch("ytx.transcripts.captions.time.sleep"):
            result = _retry_with_backoff(func, "vid1")
        assert result == "result"
        assert func.call_count == 2

    def test_raises_caption_access_blocked_after_max_retries(self):
        from youtube_transcript_api._errors import RequestBlocked

        func = MagicMock(side_effect=RequestBlocked("vid1"))
        with patch("ytx.transcripts.captions.time.sleep"):
            try:
                _retry_with_backoff(func, "vid1")
                raise AssertionError("Should have raised")
            except CaptionAccessBlockedError as e:
                assert e.video_id == "vid1"
                assert "blocked" in e.reason.lower() or "retrieve" in e.reason.lower()
        assert func.call_count == 3

    def test_raises_caption_access_blocked_on_ip_blocked(self):
        from youtube_transcript_api._errors import IpBlocked

        func = MagicMock(side_effect=IpBlocked("vid1"))
        with patch("ytx.transcripts.captions.time.sleep"):
            try:
                _retry_with_backoff(func, "vid1")
                raise AssertionError("Should have raised")
            except CaptionAccessBlockedError as e:
                assert e.video_id == "vid1"
        assert func.call_count == 3

    def test_non_retryable_exception_propagates(self):
        func = MagicMock(side_effect=ValueError("unexpected"))
        try:
            _retry_with_backoff(func, "vid1")
            raise AssertionError("Should have raised")
        except ValueError:
            pass
        assert func.call_count == 1
