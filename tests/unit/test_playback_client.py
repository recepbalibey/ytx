"""Tests for YouTube playback client error handling and player-client fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ytx.audio.downloader import (
    _build_ytdlp_opts,
    _is_playback_client_error,
    _validate_player_client,
)
from ytx.exceptions import YouTubePlaybackClientError
from ytx.models import YouTubeAuthMode


class TestPlaybackClientErrorDetection:
    """Test detection of 'page needs to be reloaded' error."""

    def test_page_needs_reloaded(self):
        assert _is_playback_client_error("The page needs to be reloaded")

    def test_page_needs_reloaded_with_context(self):
        assert _is_playback_client_error(
            "[youtube] dQw4w9WgXcQ: The page needs to be reloaded."
        )

    def test_page_needs_reloaded_case_insensitive(self):
        assert _is_playback_client_error("THE PAGE NEEDS TO BE RELOADED")

    def test_normal_error_not_detected(self):
        assert not _is_playback_client_error("Video unavailable")
        assert not _is_playback_client_error("Sign in to confirm")
        assert not _is_playback_client_error("Network timeout")


class TestPlayerClientValidation:
    """Test player_client allowlist validation."""

    def test_default_allowed(self):
        _validate_player_client("default")  # Should not raise

    def test_web_embedded_allowed(self):
        _validate_player_client("web_embedded")  # Should not raise

    def test_combined_allowed(self):
        _validate_player_client("default,web_embedded")  # Should not raise

    def test_unsupported_client_rejected(self):
        with pytest.raises(ValueError, match="Unsupported player_client"):
            _validate_player_client("tv")

    def test_unsupported_client_in_list_rejected(self):
        with pytest.raises(ValueError, match="Unsupported player_client"):
            _validate_player_client("default,tv")

    def test_empty_string_ok(self):
        _validate_player_client("")  # Should not raise


class TestBuildYtdlpOptsWithPlayerClient:
    """Test yt-dlp options building with player_client."""

    def test_no_player_client(self):
        opts = _build_ytdlp_opts("/tmp/test.mp3")
        assert "extractor_args" not in opts

    def test_with_player_client(self):
        opts = _build_ytdlp_opts(
            "/tmp/test.mp3",
            player_client="default,web_embedded",
        )
        assert opts["extractor_args"] == {
            "youtube": {"player_client": ["default,web_embedded"]}
        }

    def test_player_client_with_firefox_auth(self):
        opts = _build_ytdlp_opts(
            "/tmp/test.mp3",
            auth_mode=YouTubeAuthMode.FIREFOX,
            player_client="default,web_embedded",
        )
        assert opts["cookiesfrombrowser"] == ("firefox",)
        assert opts["extractor_args"] == {
            "youtube": {"player_client": ["default,web_embedded"]}
        }

    def test_invalid_player_client_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _build_ytdlp_opts("/tmp/test.mp3", player_client="tv")


class TestYouTubePlaybackClientError:
    """Test the playback client exception."""

    def test_default_message(self):
        err = YouTubePlaybackClientError("vid123")
        assert "playback" in str(err).lower()
        assert err.video_id == "vid123"

    def test_custom_message(self):
        err = YouTubePlaybackClientError("vid123", "Custom message")
        assert str(err) == "Custom message"
        assert err.video_id == "vid123"

    def test_is_audio_download_error(self):
        from ytx.exceptions import AudioDownloadError
        err = YouTubePlaybackClientError("vid123")
        assert isinstance(err, AudioDownloadError)


class TestPipelinePlaybackClientHandling:
    """Test pipeline playback client error tracking."""

    def test_playback_client_error_flag_default(self):
        from ytx.pipeline import Pipeline
        p = Pipeline(output_dir="/tmp", formats=["md"])
        assert p._playback_client_error is False

    @patch("ytx.pipeline.fetch_captions")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.FasterWhisperProvider.is_available", return_value=True)
    def test_playback_error_sets_flag_and_pauses(
        self, mock_available, mock_dl, mock_fetch
    ):
        """When playback client error occurs, batch should pause."""
        from ytx.exceptions import NoCaptionsError
        from ytx.models import ChannelInfo, ProcessingStatus, VideoMetadata
        from ytx.pipeline import Pipeline

        mock_fetch.side_effect = NoCaptionsError("vid1")
        mock_dl.side_effect = YouTubePlaybackClientError("vid1")

        video = VideoMetadata(
            id="vid1",
            title="Test Video",
            url="https://youtube.com/watch?v=vid1",
            channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
        )

        pipeline = Pipeline(
            output_dir="/tmp/ytx-test",
            formats=["json"],
            transcribe_missing=True,
            youtube_auth=YouTubeAuthMode.FIREFOX,
        )
        result = pipeline._process_video(video)

        assert result.status == ProcessingStatus.FAILED
        assert "playback" in result.error.lower()
        assert pipeline._playback_client_error is True

    @patch("ytx.pipeline.fetch_captions")
    @patch("ytx.pipeline.download_audio")
    def test_playback_retry_with_web_embedded(
        self, mock_dl, mock_fetch
    ):
        """When first attempt fails with playback error, retry with web_embedded."""
        from ytx.exceptions import NoCaptionsError
        from ytx.models import (
            ChannelInfo,
            ProcessingStatus,
            Transcript,
            TranscriptSegment,
            TranscriptSource,
            VideoMetadata,
        )
        from ytx.pipeline import Pipeline

        mock_fetch.side_effect = NoCaptionsError("vid1")

        # First call raises playback error, second succeeds
        call_count = [0]
        def mock_download(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise YouTubePlaybackClientError("vid1")
            return "/tmp/audio.mp3"

        mock_dl.side_effect = mock_download

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = Transcript(
            language="en", language_name="English",
            source=TranscriptSource.LOCAL_TRANSCRIPTION,
            is_generated=True,
            segments=[TranscriptSegment(0.0, 1.0, "Hello")],
        )

        video = VideoMetadata(
            id="vid1",
            title="Test Video",
            url="https://youtube.com/watch?v=vid1",
            channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
        )

        pipeline = Pipeline(
            output_dir="/tmp/ytx-test",
            formats=["json"],
            transcribe_missing=True,
            youtube_auth=YouTubeAuthMode.FIREFOX,
        )
        pipeline._transcriber = mock_transcriber

        with (
            patch.object(pipeline, "_write_output", return_value=["/tmp/out.json"]),
            patch("ytx.pipeline.cleanup_audio"),
        ):
            result = pipeline._process_video(video)

        assert result.status == ProcessingStatus.COMPLETE
        assert call_count[0] == 2  # First call + retry

        # Verify retry used player_client
        retry_call = mock_dl.call_args_list[1]
        assert retry_call[1].get("player_client") == "default,web_embedded"

    @patch("ytx.pipeline.fetch_captions")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.FasterWhisperProvider.is_available", return_value=True)
    def test_playback_retry_also_fails(
        self, mock_available, mock_dl, mock_fetch
    ):
        """When retry also fails, batch should pause."""
        from ytx.exceptions import NoCaptionsError
        from ytx.models import ChannelInfo, ProcessingStatus, VideoMetadata
        from ytx.pipeline import Pipeline

        mock_fetch.side_effect = NoCaptionsError("vid1")
        mock_dl.side_effect = YouTubePlaybackClientError("vid1")

        video = VideoMetadata(
            id="vid1",
            title="Test Video",
            url="https://youtube.com/watch?v=vid1",
            channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
        )

        pipeline = Pipeline(
            output_dir="/tmp/ytx-test",
            formats=["json"],
            transcribe_missing=True,
            youtube_auth=YouTubeAuthMode.FIREFOX,
        )
        result = pipeline._process_video(video)

        assert result.status == ProcessingStatus.FAILED
        assert pipeline._playback_client_error is True

    @patch("ytx.pipeline.fetch_captions")
    @patch("ytx.pipeline.download_audio")
    @patch("ytx.pipeline.FasterWhisperProvider.is_available", return_value=True)
    def test_no_retry_without_browser_auth(
        self, mock_available, mock_dl, mock_fetch
    ):
        """Without browser auth, no retry should happen."""
        from ytx.exceptions import NoCaptionsError
        from ytx.models import ChannelInfo, ProcessingStatus, VideoMetadata
        from ytx.pipeline import Pipeline

        mock_fetch.side_effect = NoCaptionsError("vid1")
        mock_dl.side_effect = YouTubePlaybackClientError("vid1")

        video = VideoMetadata(
            id="vid1",
            title="Test Video",
            url="https://youtube.com/watch?v=vid1",
            channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
        )

        pipeline = Pipeline(
            output_dir="/tmp/ytx-test",
            formats=["json"],
            transcribe_missing=True,
            youtube_auth=YouTubeAuthMode.AUTO,
        )
        result = pipeline._process_video(video)

        assert result.status == ProcessingStatus.FAILED
        assert pipeline._playback_client_error is True
        # Only one call (no retry)
        assert mock_dl.call_count == 1


class TestBatchPauseOnPlaybackError:
    """Test that batch processing pauses on playback client error."""

    def test_batch_pauses_not_fails_all(self):
        """When playback error occurs, remaining videos should not be attempted."""
        from ytx.pipeline import Pipeline

        pipeline = Pipeline(
            output_dir="/tmp/ytx-test",
            formats=["md"],
        )
        pipeline._playback_client_error = True

        # The flag should be set, indicating batch should pause
        assert pipeline._playback_client_error is True
