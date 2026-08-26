"""Tests for YouTube Firefox authentication support."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ytx.audio.downloader import (
    _build_ytdlp_opts,
    _is_auth_required,
    _sanitize_error,
)
from ytx.exceptions import YouTubeAuthenticationRequiredError
from ytx.models import YouTubeAuthMode


class TestAuthRequiredDetection:
    """Test detection of authentication-required error messages."""

    def test_sign_in_to_confirm(self):
        assert _is_auth_required("Sign in to confirm you're not a bot")

    def test_not_a_bot(self):
        assert _is_auth_required("Use --cookies-from-browser to confirm you are not a bot")

    def test_cookies_from_browser(self):
        assert _is_auth_required("Use cookies-from-browser option")

    def test_login_required(self):
        assert _is_auth_required("Login required to access this video")

    def test_authentication_required(self):
        assert _is_auth_required("Authentication is required")

    def test_normal_error_not_detected(self):
        assert not _is_auth_required("Video unavailable")
        assert not _is_auth_required("Private video")
        assert not _is_auth_required("Network timeout")


class TestErrorSanitization:
    """Test that sensitive data is removed from error messages."""

    def test_cookie_header_redacted(self):
        msg = "Error: Cookie: SID=abc123; HSID=xyz"
        sanitized = _sanitize_error(msg)
        assert "abc123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_set_cookie_redacted(self):
        msg = "Set-Cookie: SID=abc123; path=/"
        sanitized = _sanitize_error(msg)
        assert "abc123" not in sanitized

    def test_authorization_redacted(self):
        msg = "Authorization: Bearer secret_token_12345"
        sanitized = _sanitize_error(msg)
        assert "secret_token_12345" not in sanitized

    def test_sapisid_redacted(self):
        msg = "Error with SAPISID=abc123xyz"
        sanitized = _sanitize_error(msg)
        assert "abc123xyz" not in sanitized

    def test_hsid_redacted(self):
        msg = "HSID=secret_value_here"
        sanitized = _sanitize_error(msg)
        assert "secret_value_here" not in sanitized

    def test_normal_error_unchanged(self):
        msg = "Video unavailable or private"
        sanitized = _sanitize_error(msg)
        assert sanitized == msg


class TestBuildYtdlpOpts:
    """Test yt-dlp options building."""

    def test_default_opts_no_auth(self):
        opts = _build_ytdlp_opts("/tmp/test.mp3")
        assert "cookiesfrombrowser" not in opts
        assert opts["format"] == "bestaudio/best"
        assert opts["quiet"] is True

    def test_firefox_auth_mode(self):
        opts = _build_ytdlp_opts("/tmp/test.mp3", auth_mode=YouTubeAuthMode.FIREFOX)
        assert opts["cookiesfrombrowser"] == ("firefox",)

    def test_auto_auth_mode_no_cookies(self):
        opts = _build_ytdlp_opts("/tmp/test.mp3", auth_mode=YouTubeAuthMode.AUTO)
        assert "cookiesfrombrowser" not in opts

    def test_force_firefox_auth(self):
        opts = _build_ytdlp_opts("/tmp/test.mp3", use_firefox_auth=True)
        assert opts["cookiesfrombrowser"] == ("firefox",)

    def test_firefox_auth_overrides_auto(self):
        opts = _build_ytdlp_opts(
            "/tmp/test.mp3",
            auth_mode=YouTubeAuthMode.AUTO,
            use_firefox_auth=True,
        )
        assert opts["cookiesfrombrowser"] == ("firefox",)


class TestYouTubeAuthMode:
    """Test YouTubeAuthMode enum."""

    def test_auto_value(self):
        assert YouTubeAuthMode.AUTO.value == "auto"

    def test_firefox_value(self):
        assert YouTubeAuthMode.FIREFOX.value == "firefox"

    def test_from_string(self):
        assert YouTubeAuthMode("auto") == YouTubeAuthMode.AUTO
        assert YouTubeAuthMode("firefox") == YouTubeAuthMode.FIREFOX


class TestYouTubeAuthenticationRequiredError:
    """Test the auth-required exception."""

    def test_default_message(self):
        err = YouTubeAuthenticationRequiredError("vid123")
        assert "sign-in" in str(err).lower() or "sign in" in str(err).lower()
        assert err.video_id == "vid123"

    def test_custom_message(self):
        err = YouTubeAuthenticationRequiredError("vid123", "Custom message")
        assert str(err) == "Custom message"
        assert err.video_id == "vid123"

    def test_is_audio_download_error(self):
        from ytx.exceptions import AudioDownloadError
        err = YouTubeAuthenticationRequiredError("vid123")
        assert isinstance(err, AudioDownloadError)


class TestPipelineAuthMode:
    """Test pipeline auth mode configuration."""

    def test_default_auth_mode(self):
        from ytx.pipeline import Pipeline
        p = Pipeline(output_dir="/tmp", formats=["md"])
        assert p.youtube_auth == YouTubeAuthMode.AUTO

    def test_firefox_auth_mode(self):
        from ytx.pipeline import Pipeline
        p = Pipeline(output_dir="/tmp", formats=["md"], youtube_auth=YouTubeAuthMode.FIREFOX)
        assert p.youtube_auth == YouTubeAuthMode.FIREFOX

    def test_auth_required_flag_default(self):
        from ytx.pipeline import Pipeline
        p = Pipeline(output_dir="/tmp", formats=["md"])
        assert p._auth_required is False

    def test_firefox_retry_flag_default(self):
        from ytx.pipeline import Pipeline
        p = Pipeline(output_dir="/tmp", formats=["md"])
        assert p._firefox_retry_attempted is False


class TestManifestNoAuthMaterial:
    """Verify manifests contain no authentication material."""

    def test_manifest_has_no_auth_fields(self):
        import tempfile

        from ytx.models import ProcessingStatus
        from ytx.state.manifest import Manifest

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manifest.json")
            m = Manifest(path)
            m.set_source("video", "https://youtube.com/watch?v=test", "test")
            m.set_video_status("test", ProcessingStatus.COMPLETE)
            m.save()

            with open(path) as f:
                content = f.read()

            # No auth material in manifest
            assert "cookie" not in content.lower()
            assert "firefox" not in content.lower()
            assert "SID" not in content
            assert "HSID" not in content
            assert "SAPISID" not in content


class TestTranscriptNoAuthMaterial:
    """Verify transcript output contains no authentication material."""

    def test_json_output_no_auth(self):
        import tempfile

        from ytx.models import (
            ChannelInfo,
            Transcript,
            TranscriptResult,
            TranscriptSegment,
            TranscriptSource,
            VideoMetadata,
        )
        from ytx.output.json_writer import write_json

        with tempfile.TemporaryDirectory() as tmp:
            video = VideoMetadata(
                id="test", title="Test", url="https://youtube.com/watch?v=test",
                channel=ChannelInfo(id="ch1", name="Test", url=""),
            )
            transcript = Transcript(
                language="en", language_name="English",
                source=TranscriptSource.YOUTUBE_AUTO, is_generated=True,
                segments=[TranscriptSegment(start=0.0, duration=1.0, text="Hello")],
            )
            result = TranscriptResult(video=video, transcript=transcript)
            path = os.path.join(tmp, "test.json")
            write_json(result, path)

            with open(path) as f:
                content = f.read()

            assert "cookie" not in content.lower()
            assert "firefox" not in content.lower()
            assert "SID" not in content


class TestWebApiNoAuthMaterial:
    """Verify web API responses contain no authentication material."""

    def test_job_status_no_auth(self, client, fresh_manager):

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=test1234567",
                "youtube_auth": "firefox",
            })
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]

            resp = client.get(f"/jobs/{job_id}/status")
            data = resp.json()

            # Auth mode should not appear in job status
            assert "youtube_auth" not in data
            assert "cookies" not in str(data).lower()
            assert "firefox" not in str(data).lower()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from ytx.web.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fresh_manager():
    from ytx.web.app import job_manager
    original = job_manager._jobs.copy()
    original_active = job_manager._active_job_id
    job_manager._jobs.clear()
    job_manager._active_job_id = None
    yield job_manager
    job_manager._jobs.clear()
    job_manager._jobs.update(original)
    job_manager._active_job_id = original_active
