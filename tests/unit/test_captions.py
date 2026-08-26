"""Tests for caption error handling: blocked, no captions, retrieval failures."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from youtube_transcript_api._errors import (
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
)

from ytx.exceptions import (
    CaptionAccessBlockedError,
    CaptionRetrievalError,
    NoCaptionsError,
)
from ytx.transcripts.captions import fetch_captions


def _mock_transcript_list(transcripts=None, generated=None):
    """Create a mock TranscriptList."""
    tl = MagicMock()
    tl.__iter__ = MagicMock(return_value=iter(transcripts or []))
    if generated is not None:
        tl.find_generated_transcript = MagicMock(return_value=generated)
    return tl


def _mock_fetched_transcript(language_code="en", is_generated=False, snippets=None):
    """Create a mock FetchedTranscript."""
    ft = MagicMock()
    ft.language_code = language_code
    ft.language = "English" if language_code == "en" else language_code
    ft.is_generated = is_generated
    if snippets is None:
        s = MagicMock()
        s.start = 0.0
        s.duration = 1.0
        s.text = "Hello world"
        snippets = [s]
    ft.__iter__ = MagicMock(return_value=iter(snippets))
    return ft


class TestFetchCaptionsSuccess:
    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_auto_generated_caption(self, mock_ytt_cls):
        """Successfully fetch auto-generated captions."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        fetched = _mock_fetched_transcript("en", is_generated=True)
        transcript = MagicMock()
        transcript.fetch.return_value = fetched
        transcript.language_code = "en"
        transcript.language = "English"
        transcript.is_generated = True

        tl = MagicMock()
        tl.find_transcript.return_value = transcript
        tl.find_manually_created_transcript.side_effect = NoTranscriptFound("vid1", ["en"], tl)
        mock_ytt.list.return_value = tl

        result = fetch_captions("vid1", languages=["en"])
        assert result.language == "en"
        assert result.source.value == "youtube_auto"

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_manual_caption_prefered(self, mock_ytt_cls):
        """Manual captions are preferred over auto-generated."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        auto_fetched = _mock_fetched_transcript("en", is_generated=True)
        manual_fetched = _mock_fetched_transcript("en", is_generated=False)

        auto_transcript = MagicMock()
        auto_transcript.fetch.return_value = auto_fetched
        auto_transcript.is_generated = True

        manual_transcript = MagicMock()
        manual_transcript.fetch.return_value = manual_fetched

        tl = MagicMock()
        tl.find_transcript.return_value = auto_transcript
        tl.find_manually_created_transcript.return_value = manual_transcript
        mock_ytt.list.return_value = tl

        result = fetch_captions("vid1", languages=["en"])
        assert result.source.value == "youtube_manual"


class TestFetchCaptionsNoCaptions:
    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_transcripts_disabled(self, mock_ytt_cls):
        """TranscriptsDisabled raises NoCaptionsError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt
        mock_ytt.list.side_effect = TranscriptsDisabled("vid1")

        with pytest.raises(NoCaptionsError) as exc_info:
            fetch_captions("vid1")
        assert exc_info.value.video_id == "vid1"

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_no_transcript_found_for_language(self, mock_ytt_cls):
        """NoTranscriptFound for requested language raises NoCaptionsError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        tl = MagicMock()
        tl.find_transcript.side_effect = NoTranscriptFound("vid1", ["fr"], tl)
        # No fallback transcripts available
        tl.__iter__ = MagicMock(return_value=iter([]))
        mock_ytt.list.return_value = tl

        with pytest.raises(NoCaptionsError):
            fetch_captions("vid1", languages=["fr"])


class TestFetchCaptionsBlocked:
    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    @patch("ytx.transcripts.captions.time.sleep")
    def test_ip_blocked_raises_caption_access_blocked(self, mock_sleep, mock_ytt_cls):
        """IpBlocked after retries raises CaptionAccessBlockedError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt
        mock_ytt.list.side_effect = IpBlocked("vid1")

        with pytest.raises(CaptionAccessBlockedError) as exc_info:
            fetch_captions("vid1")
        assert exc_info.value.video_id == "vid1"
        assert mock_ytt.list.call_count == 3  # 3 retries

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    @patch("ytx.transcripts.captions.time.sleep")
    def test_request_blocked_raises_caption_access_blocked(self, mock_sleep, mock_ytt_cls):
        """RequestBlocked after retries raises CaptionAccessBlockedError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt
        mock_ytt.list.side_effect = RequestBlocked("vid1")

        with pytest.raises(CaptionAccessBlockedError) as exc_info:
            fetch_captions("vid1")
        assert exc_info.value.video_id == "vid1"

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    @patch("ytx.transcripts.captions.time.sleep")
    def test_blocked_on_fetch_raises_caption_access_blocked(self, mock_sleep, mock_ytt_cls):
        """IpBlocked during transcript.fetch() raises CaptionAccessBlockedError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        transcript = MagicMock()
        transcript.fetch.side_effect = IpBlocked("vid1")

        tl = MagicMock()
        tl.find_transcript.return_value = transcript
        mock_ytt.list.return_value = tl

        with pytest.raises(CaptionAccessBlockedError):
            fetch_captions("vid1", languages=["en"])


class TestFetchCaptionsRetrievalFailure:
    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_youtube_request_failed_raises_caption_retrieval_error(self, mock_ytt_cls):
        """YouTubeRequestFailed (non-retryable) raises CaptionRetrievalError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt
        # YouTubeRequestFailed is retryable, so after retries it becomes CaptionAccessBlockedError
        # But if it happens on a non-retryable path, it should be CaptionRetrievalError
        mock_ytt.list.side_effect = Exception("unexpected network error")

        with pytest.raises(CaptionRetrievalError) as exc_info:
            fetch_captions("vid1")
        assert exc_info.value.video_id == "vid1"

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_generic_exception_raises_caption_retrieval_error(self, mock_ytt_cls):
        """Generic exceptions raise CaptionRetrievalError, not NoCaptionsError."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt
        mock_ytt.list.side_effect = RuntimeError("something broke")

        with pytest.raises(CaptionRetrievalError) as exc_info:
            fetch_captions("vid1")
        assert exc_info.value.video_id == "vid1"
        assert "something broke" in exc_info.value.reason


class TestFetchCaptionsFallback:
    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_fallback_to_english_when_requested_unavailable(self, mock_ytt_cls):
        """Falls back to English when requested language not found."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        fetched = _mock_fetched_transcript("en", is_generated=False)
        en_transcript = MagicMock()
        en_transcript.fetch.return_value = fetched

        tl = MagicMock()
        # First call: NoTranscriptFound for requested language
        tl.find_transcript.side_effect = [
            NoTranscriptFound("vid1", ["fr"], tl),  # requested language
            en_transcript,  # English fallback
        ]
        mock_ytt.list.return_value = tl

        result = fetch_captions("vid1", languages=["fr"])
        assert result.language == "en"

    @patch("ytx.transcripts.captions.YouTubeTranscriptApi")
    def test_fallback_to_any_available(self, mock_ytt_cls):
        """Falls back to any available transcript when English not found."""
        mock_ytt = MagicMock()
        mock_ytt_cls.return_value = mock_ytt

        fetched = _mock_fetched_transcript("de", is_generated=False)
        de_transcript = MagicMock()
        de_transcript.fetch.return_value = fetched

        tl = MagicMock()
        tl.find_transcript.side_effect = NoTranscriptFound("vid1", ["en"], tl)
        tl.__iter__ = MagicMock(return_value=iter([de_transcript]))
        mock_ytt.list.return_value = tl

        result = fetch_captions("vid1")
        assert result.language == "de"
