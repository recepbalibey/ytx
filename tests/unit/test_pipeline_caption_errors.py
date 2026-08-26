"""Tests for pipeline handling of caption errors with --transcribe-missing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ytx.exceptions import (
    CaptionAccessBlockedError,
    CaptionRetrievalError,
    NoCaptionsError,
)
from ytx.models import ProcessingStatus, TranscriptSource
from ytx.pipeline import Pipeline


def _make_pipeline(transcribe_missing=False, **kwargs):
    """Create a Pipeline with minimal required params."""
    return Pipeline(
        output_dir="/tmp/ytx-test",
        formats=["json"],
        transcribe_missing=transcribe_missing,
        **kwargs,
    )


def _make_video():
    from ytx.models import ChannelInfo, VideoMetadata
    return VideoMetadata(
        id="vid1",
        title="Test Video",
        url="https://youtube.com/watch?v=vid1",
        channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
    )


class TestPipelineCaptionErrors:
    @patch("ytx.pipeline.fetch_captions")
    def test_no_captions_without_flag(self, mock_fetch):
        """NoCaptionsError without --transcribe-missing returns FAILED."""
        mock_fetch.side_effect = NoCaptionsError("vid1")
        pipeline = _make_pipeline(transcribe_missing=False)
        result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.FAILED
        assert "No captions available" in result.error

    @patch("ytx.pipeline.fetch_captions")
    def test_blocked_without_flag(self, mock_fetch):
        """CaptionAccessBlockedError without --transcribe-missing returns FAILED."""
        mock_fetch.side_effect = CaptionAccessBlockedError("vid1", "IP blocked")
        pipeline = _make_pipeline(transcribe_missing=False)
        result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.FAILED
        assert "blocked" in result.error.lower()

    @patch("ytx.pipeline.fetch_captions")
    def test_retrieval_error_without_flag(self, mock_fetch):
        """CaptionRetrievalError without --transcribe-missing returns FAILED."""
        mock_fetch.side_effect = CaptionRetrievalError("vid1", "timeout")
        pipeline = _make_pipeline(transcribe_missing=False)
        result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.FAILED
        assert "Failed to retrieve captions" in result.error

    @patch("ytx.pipeline.cleanup_audio")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.fetch_captions")
    def test_blocked_falls_back_to_local(self, mock_fetch, mock_dl, mock_clean):
        """Blocked error with --transcribe-missing falls back to local."""
        mock_fetch.side_effect = CaptionAccessBlockedError("vid1", "blocked")
        mock_dl.return_value = "/tmp/audio.mp3"
        mock_transcriber = MagicMock()
        from ytx.models import Transcript, TranscriptSegment
        mock_transcriber.transcribe.return_value = Transcript(
            language="en", language_name="English",
            source=TranscriptSource.LOCAL_TRANSCRIPTION,
            is_generated=True,
            segments=[TranscriptSegment(0.0, 1.0, "Hello")],
        )
        pipeline = _make_pipeline(transcribe_missing=True)
        pipeline._transcriber = mock_transcriber
        with patch.object(pipeline, "_write_output", return_value=["/tmp/out.json"]):
            result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.COMPLETE
        assert result.transcript_source == TranscriptSource.LOCAL_TRANSCRIPTION
        mock_dl.assert_called_once()
        mock_clean.assert_called_once()

    @patch("ytx.pipeline.cleanup_audio")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.fetch_captions")
    def test_no_captions_falls_back_to_local(self, mock_fetch, mock_dl, mock_clean):
        """NoCaptionsError with --transcribe-missing falls back to local."""
        mock_fetch.side_effect = NoCaptionsError("vid1")
        mock_dl.return_value = "/tmp/audio.mp3"
        mock_transcriber = MagicMock()
        from ytx.models import Transcript, TranscriptSegment
        mock_transcriber.transcribe.return_value = Transcript(
            language="en", language_name="English",
            source=TranscriptSource.LOCAL_TRANSCRIPTION,
            is_generated=True,
            segments=[TranscriptSegment(0.0, 1.0, "Hello")],
        )
        pipeline = _make_pipeline(transcribe_missing=True)
        pipeline._transcriber = mock_transcriber
        with patch.object(pipeline, "_write_output", return_value=["/tmp/out.json"]):
            result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.COMPLETE
        assert result.transcript_source == TranscriptSource.LOCAL_TRANSCRIPTION

    @patch("ytx.pipeline.cleanup_audio")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.fetch_captions")
    def test_retrieval_error_falls_back_to_local(self, mock_fetch, mock_dl, mock_clean):
        """CaptionRetrievalError with --transcribe-missing falls back to local."""
        mock_fetch.side_effect = CaptionRetrievalError("vid1", "network error")
        mock_dl.return_value = "/tmp/audio.mp3"
        mock_transcriber = MagicMock()
        from ytx.models import Transcript, TranscriptSegment
        mock_transcriber.transcribe.return_value = Transcript(
            language="en", language_name="English",
            source=TranscriptSource.LOCAL_TRANSCRIPTION,
            is_generated=True,
            segments=[TranscriptSegment(0.0, 1.0, "Hello")],
        )
        pipeline = _make_pipeline(transcribe_missing=True)
        pipeline._transcriber = mock_transcriber
        with patch.object(pipeline, "_write_output", return_value=["/tmp/out.json"]):
            result = pipeline._process_video(_make_video())
        assert result.status == ProcessingStatus.COMPLETE
        assert result.transcript_source == TranscriptSource.LOCAL_TRANSCRIPTION
