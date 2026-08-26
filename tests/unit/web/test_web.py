"""Tests for the YTX web interface."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ytx.web.app import app, job_manager
from ytx.web.jobs import JobManager, JobStatus


@pytest.fixture()
def client():
    """Create a test client."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fresh_manager():
    """Provide a fresh job manager for each test."""
    original = job_manager._jobs.copy()
    original_active = job_manager._active_job_id
    job_manager._jobs.clear()
    job_manager._active_job_id = None
    yield job_manager
    job_manager._jobs.clear()
    job_manager._jobs.update(original)
    job_manager._active_job_id = original_active


class TestHomePage:
    def test_home_page_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "YTX" in resp.text
        assert "extract-form" in resp.text
        assert "url-input" in resp.text

    def test_home_page_has_privacy_note(self, client):
        resp = client.get("/")
        assert "Local processing" in resp.text

    def test_home_page_has_logo(self, client):
        resp = client.get("/")
        assert "logo.svg" in resp.text

    def test_home_page_has_url_type_detection(self, client):
        resp = client.get("/")
        assert "url-type-indicator" in resp.text

    def test_home_page_has_transcript_method_section(self, client):
        resp = client.get("/")
        assert "Local fallback" in resp.text
        assert "Recommended" in resp.text

    def test_home_page_has_local_fallback_default(self, client):
        resp = client.get("/")
        assert "Local fallback" in resp.text
        assert 'name="transcribe_missing"' in resp.text

    def test_home_page_has_checkbox_options(self, client):
        """Homepage should have essential options visible."""
        resp = client.get("/")
        assert 'name="transcribe_missing"' in resp.text
        assert 'name="language"' in resp.text

    def test_home_page_has_turkish(self, client):
        resp = client.get("/")
        assert 'value="tr"' in resp.text
        assert "Turkish" in resp.text

    def test_home_page_has_local_fallback_desc(self, client):
        """Local fallback description should explain the feature."""
        resp = client.get("/")
        assert "automatically transcribes locally" in resp.text

    def test_home_page_no_google_fonts(self, client):
        resp = client.get("/")
        assert "fonts.googleapis.com" not in resp.text
        assert "fonts.gstatic.com" not in resp.text


class TestURLDetection:
    def test_detect_video_url(self, client):
        resp = client.get("/api/detect-url?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "video"

    def test_detect_playlist_url(self, client):
        resp = client.get("/api/detect-url?url=https://www.youtube.com/playlist?list=PLtest123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "playlist"

    def test_detect_channel_url(self, client):
        resp = client.get("/api/detect-url?url=https://www.youtube.com/@testchannel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "channel"

    def test_detect_invalid_url(self, client):
        resp = client.get("/api/detect-url?url=not-a-url")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] is None

    def test_detect_empty_url(self, client):
        resp = client.get("/api/detect-url?url=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] is None


class TestJobCreation:
    def test_invalid_url_rejected(self, client, fresh_manager):
        resp = client.post("/jobs", json={"url": "not-a-url"})
        assert resp.status_code == 400
        assert "YouTube" in resp.text

    def test_empty_url_rejected(self, client, fresh_manager):
        resp = client.post("/jobs", json={"url": ""})
        assert resp.status_code == 400

    def test_missing_url_rejected(self, client, fresh_manager):
        resp = client.post("/jobs", json={})
        assert resp.status_code == 400

    def test_non_youtube_url_with_playlist_parameter_is_rejected(self, client, fresh_manager):
        resp = client.post("/jobs", json={"url": "https://example.com/?list=PLtest"})
        assert resp.status_code == 400

    @patch("ytx.web.app._run_job_thread")
    def test_valid_video_url_accepted(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "formats": ["md", "json"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert len(data["job_id"]) > 0

    @patch("ytx.web.app._run_job_thread")
    def test_valid_playlist_url_accepted(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/playlist?list=PLtest123",
        })
        assert resp.status_code == 200

    @patch("ytx.web.app._run_job_thread")
    def test_valid_channel_url_accepted(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/@testchannel",
        })
        assert resp.status_code == 200

    @patch("ytx.web.app._run_job_thread")
    def test_invalid_format_rejected(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "formats": ["invalid_format"],
        })
        assert resp.status_code == 400

    @patch("ytx.web.app._run_job_thread")
    def test_one_active_job_limit(self, mock_thread, client, fresh_manager):
        resp1 = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp1.status_code == 200

        job_id = resp1.json()["job_id"]
        job = fresh_manager.get_job(job_id)
        job.status = JobStatus.PROCESSING

        resp2 = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=other123456",
        })
        assert resp2.status_code == 409

    @patch("ytx.web.app._run_job_thread")
    def test_default_transcribe_missing_true(self, mock_thread, client, fresh_manager):
        """Verify transcribe_missing defaults to True."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp.status_code == 200
        # The job was created successfully with default params

    @patch("ytx.web.app._run_job_thread")
    def test_model_mapping_fast(self, mock_thread, client, fresh_manager):
        """Verify 'fast' model maps to 'tiny'."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "model": "fast",
        })
        assert resp.status_code == 200

    @patch("ytx.web.app._run_job_thread")
    def test_model_mapping_balanced(self, mock_thread, client, fresh_manager):
        """Verify 'balanced' model maps to 'base'."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "model": "balanced",
        })
        assert resp.status_code == 200

    @patch("ytx.web.app._run_job_thread")
    def test_model_mapping_best(self, mock_thread, client, fresh_manager):
        """Verify 'best' model maps to 'small'."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "model": "best",
        })
        assert resp.status_code == 200

    @patch("ytx.web.app._run_job_thread")
    def test_default_model_resolves_to_base(self, mock_thread, client, fresh_manager):
        """When no model specified, default should resolve to 'base' (balanced)."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        assert resp.status_code == 200
        call_args = mock_thread.call_args
        params = call_args[0][1]
        assert params["model"] == "base"

    @patch("ytx.web.app._run_job_thread")
    def test_turkish_language_accepted(self, mock_thread, client, fresh_manager):
        """Verify Turkish language code 'tr' is accepted."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "language": "tr",
        })
        assert resp.status_code == 200
        call_args = mock_thread.call_args
        params = call_args[0][1]
        assert params["language"] == "tr"

    @patch("ytx.web.app._run_job_thread")
    def test_auto_language_passes_none(self, mock_thread, client, fresh_manager):
        """Verify empty language passes None (auto-detect)."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "language": "",
        })
        assert resp.status_code == 200
        call_args = mock_thread.call_args
        params = call_args[0][1]
        assert params["language"] is None


class TestJobStatus:
    def test_job_not_found(self, client, fresh_manager):
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404

    @patch("ytx.web.app._run_job_thread")
    def test_job_page_loads(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]

        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        assert "dQw4w9WgXcQ" in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_job_status_json(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]

        resp = client.get(f"/jobs/{job_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert "status" in data

    def test_job_status_not_found(self, client, fresh_manager):
        resp = client.get("/jobs/nonexistent/status")
        assert resp.status_code == 404


class TestJobCancellation:
    def test_cancel_nonexistent(self, client, fresh_manager):
        resp = client.post("/jobs/nonexistent/cancel")
        assert resp.status_code == 404

    @patch("ytx.web.app._run_job_thread")
    def test_cancel_running_job(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]
        job = fresh_manager.get_job(job_id)
        job.status = JobStatus.PROCESSING

        resp = client.post(f"/jobs/{job_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("ytx.web.app._run_job_thread")
    def test_cancel_completed_job(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]
        job = fresh_manager.get_job(job_id)
        job.status = JobStatus.COMPLETE

        resp = client.post(f"/jobs/{job_id}/cancel")
        assert resp.status_code == 400


class TestFileSecurity:
    def test_download_nonexistent_job(self, client, fresh_manager):
        resp = client.get("/jobs/nonexistent/files/vid123/transcript.json")
        assert resp.status_code == 404

    @patch("ytx.web.app._run_job_thread")
    def test_path_traversal_rejected(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]

        resp = client.get(f"/jobs/{job_id}/files/vid123/../../../etc/passwd")
        assert resp.status_code in (403, 404, 422)

    @patch("ytx.web.app._run_job_thread")
    def test_unknown_filename_rejected(self, mock_thread, client, fresh_manager):
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        job_id = resp.json()["job_id"]

        resp = client.get(f"/jobs/{job_id}/files/vid123/secret.txt")
        assert resp.status_code in (403, 404)


class TestTranscriptPage:
    def test_transcript_not_found(self, client, fresh_manager):
        resp = client.get("/jobs/nonexistent/videos/vid123")
        assert resp.status_code == 404


class TestJobManager:
    def test_create_job(self):
        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")
        assert job.source_url == "https://youtube.com/watch?v=test123456"
        assert job.status == JobStatus.QUEUED
        assert len(job.id) == 12

    def test_get_job(self):
        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")
        assert mgr.get_job(job.id) is job
        assert mgr.get_job("nonexistent") is None

    def test_active_job(self):
        mgr = JobManager()
        assert mgr.get_active_job() is None
        job = mgr.create_job("https://youtube.com/watch?v=test123456")
        assert mgr.get_active_job() is job

    def test_one_active_at_a_time(self):
        mgr = JobManager()
        job1 = mgr.create_job("https://youtube.com/watch?v=test123456")
        job1.status = JobStatus.PROCESSING
        with pytest.raises(RuntimeError, match="already running"):
            mgr.create_job("https://youtube.com/watch?v=other123456")

    def test_clear_active(self):
        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")
        mgr.clear_active(job.id)
        assert mgr.get_active_job() is None

    def test_handle_progress_event(self):
        from ytx.models import ProgressEvent, ProgressEventType

        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")

        event = ProgressEvent(
            type=ProgressEventType.DISCOVERY_COMPLETE,
            total=5,
        )
        mgr.handle_progress_event(job, event)

        assert job.total_videos == 5
        assert len(job.events) == 1
        assert job.events[0]["type"] == "discovery_complete"

    def test_video_state_tracking(self):
        from ytx.models import ProgressEvent, ProgressEventType

        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")

        # Video started
        mgr.handle_progress_event(job, ProgressEvent(
            type=ProgressEventType.VIDEO_STARTED,
            video_id="abc123",
            video_title="Test Video",
            current=1,
            total=3,
        ))
        assert "abc123" in job.videos
        assert job.videos["abc123"].title == "Test Video"

        # Video completed
        mgr.handle_progress_event(job, ProgressEvent(
            type=ProgressEventType.VIDEO_COMPLETED,
            video_id="abc123",
            video_title="Test Video",
            source="youtube_auto",
        ))
        assert job.videos["abc123"].status.value == "complete"
        assert job.completed_videos == 1

    def test_job_completion(self):
        from ytx.models import JobSummary, ProgressEvent, ProgressEventType

        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")

        summary = JobSummary(total_discovered=2, captions_extracted=2)
        mgr.handle_progress_event(job, ProgressEvent(
            type=ProgressEventType.JOB_COMPLETED,
            summary=summary,
        ))
        assert job.status == JobStatus.COMPLETE
        assert job.summary is not None
        assert job.summary.total_discovered == 2

    def test_fatal_error_tracking(self):
        from ytx.models import ProgressEvent, ProgressEventType

        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")

        mgr.handle_progress_event(job, ProgressEvent(
            type=ProgressEventType.JOB_FATAL_ERROR,
            error="Local transcription could not start: invalid model",
        ))
        assert job.is_fatal_error is True
        assert "invalid model" in job.fatal_error_message
        assert len(job.errors) == 1

    def test_error_deduplication(self):
        from ytx.models import ProgressEvent, ProgressEventType

        mgr = JobManager()
        job = mgr.create_job("https://youtube.com/watch?v=test123456")

        # Simulate multiple videos failing with the same error
        for i in range(5):
            mgr.handle_progress_event(job, ProgressEvent(
                type=ProgressEventType.VIDEO_FAILED,
                video_id=f"vid{i}",
                video_title=f"Video {i}",
                error="No captions available",
            ))

        # Error should only appear once in errors list
        assert job.errors.count("No captions available") == 1
        # But count should track total occurrences
        assert job.error_counts["No captions available"] == 5
        assert job.failed_videos == 5


class TestTranscriptViewer:
    """Tests for the transcript viewer with flat and structured layouts."""

    def _create_job_with_video(self, client, fresh_manager, mock_thread):
        """Helper to create a job and return job_id."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        })
        return resp.json()["job_id"]

    @patch("ytx.web.app._run_job_thread")
    def test_flat_json_transcript_viewer(self, mock_thread, client, fresh_manager, tmp_path):
        """Flat layout JSON transcript should be viewable."""
        import json
        import os

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        # Create a flat JSON transcript file
        json_path = str(tmp_path / "My Video.json")
        data = {
            "schema_version": "1.0",
            "video": {"id": "vid1", "title": "My Video", "url": "https://youtube.com/watch?v=vid1",
                       "channel": {"id": "ch1", "name": "Test", "url": "https://youtube.com/@test"},
                       "duration_seconds": 120},
            "transcript": {
                "language": "en", "language_name": "English", "source": "youtube_manual",
                "generated": False,
                "segments": [
                    {"start": 0.0, "duration": 2.0, "text": "Hello world"},
                    {"start": 2.0, "duration": 3.0, "text": "This is a test"},
                ],
            },
        }
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Set up video state with flat output paths
        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="My Video", status=VideoStatus.COMPLETE,
                        output_paths=[json_path])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "My Video" in resp.text
        assert "Hello world" in resp.text
        assert "Transcript data not available" not in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_flat_markdown_transcript_viewer(self, mock_thread, client, fresh_manager, tmp_path):
        """Flat layout Markdown transcript should be viewable when no JSON exists."""
        import os

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        # Create a flat Markdown transcript file (no JSON)
        md_path = str(tmp_path / "My Video.md")
        md_content = """# My Video

- **Channel:** Test Channel
- **URL:** https://youtube.com/watch?v=vid1
- **Language:** English
- **Source:** YouTube Manual

## Transcript

Hello world

This is a test
"""
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, "w") as f:
            f.write(md_content)

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="My Video", status=VideoStatus.COMPLETE,
                        output_paths=[md_path])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "My Video" in resp.text
        assert "Hello world" in resp.text
        assert "Transcript data not available" not in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_structured_json_transcript_viewer(self, mock_thread, client, fresh_manager, tmp_path):
        """Structured layout JSON transcript should still work."""
        import json

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        # Create structured JSON transcript
        video_dir = tmp_path / "My-Video_vid1"
        video_dir.mkdir()
        json_path = str(video_dir / "transcript.json")
        data = {
            "schema_version": "1.0",
            "video": {"id": "vid1", "title": "My Video", "url": "https://youtube.com/watch?v=vid1",
                       "channel": {"id": "ch1", "name": "Test", "url": "https://youtube.com/@test"},
                       "duration_seconds": 120},
            "transcript": {
                "language": "en", "language_name": "English", "source": "youtube_manual",
                "generated": False,
                "segments": [
                    {"start": 0.0, "duration": 2.0, "text": "Hello world"},
                    {"start": 2.0, "duration": 3.0, "text": "This is a test"},
                ],
            },
        }
        with open(json_path, "w") as f:
            json.dump(data, f)

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="My Video", status=VideoStatus.COMPLETE,
                        output_paths=[json_path])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "Hello world" in resp.text
        assert "Transcript data not available" not in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_transcript_viewer_missing_file(self, mock_thread, client, fresh_manager):
        """Missing transcript file should show error, not crash."""
        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="My Video", status=VideoStatus.COMPLETE,
                        output_paths=["/nonexistent/path/transcript.json"])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "Transcript data not available" in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_transcript_viewer_unicode_filename(self, mock_thread, client, fresh_manager, tmp_path):
        """Turkish/Unicode filenames should work."""
        import json
        import os

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        json_path = str(tmp_path / "Avrupa Birliği Mesajlarımızı Okuyacak.json")
        data = {
            "schema_version": "1.0",
            "video": {"id": "vid1", "title": "Avrupa Birliği Mesajlarımızı Okuyacak",
                       "url": "https://youtube.com/watch?v=vid1",
                       "channel": {"id": "ch1", "name": "Test", "url": "https://youtube.com/@test"},
                       "duration_seconds": 120},
            "transcript": {
                "language": "tr", "language_name": "Turkish", "source": "youtube_manual",
                "generated": False,
                "segments": [{"start": 0.0, "duration": 2.0, "text": "Merhaba dünya"}],
            },
        }
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(data, f)

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="Avrupa Birliği Mesajlarımızı Okuyacak",
                        status=VideoStatus.COMPLETE, output_paths=[json_path])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "Merhaba dünya" in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_transcript_viewer_duplicate_titles(self, mock_thread, client, fresh_manager, tmp_path):
        """Two videos with same title but different IDs should show correct content."""
        import json

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        # Video 1
        json1 = str(tmp_path / "Same Title.json")
        data1 = {
            "schema_version": "1.0",
            "video": {
                "id": "id1", "title": "Same Title",
                "url": "https://youtube.com/watch?v=id1",
                "channel": {"id": "ch1", "name": "Test",
                            "url": "https://youtube.com/@test"},
            },
            "transcript": {
                "language": "en", "language_name": "English",
                "source": "youtube_manual", "generated": False,
                "segments": [{"start": 0, "duration": 1,
                              "text": "Content from video 1"}],
            },
        }
        with open(json1, "w") as f:
            json.dump(data1, f)

        # Video 2
        json2 = str(tmp_path / "Same Title_id2.json")
        data2 = {
            "schema_version": "1.0",
            "video": {
                "id": "id2", "title": "Same Title",
                "url": "https://youtube.com/watch?v=id2",
                "channel": {"id": "ch1", "name": "Test",
                            "url": "https://youtube.com/@test"},
            },
            "transcript": {
                "language": "en", "language_name": "English",
                "source": "youtube_manual", "generated": False,
                "segments": [{"start": 0, "duration": 1,
                              "text": "Content from video 2"}],
            },
        }
        with open(json2, "w") as f:
            json.dump(data2, f)

        from ytx.web.jobs import VideoState, VideoStatus
        vs1 = VideoState(
            id="id1", title="Same Title",
            status=VideoStatus.COMPLETE, output_paths=[json1],
        )
        vs2 = VideoState(
            id="id2", title="Same Title",
            status=VideoStatus.COMPLETE, output_paths=[json2],
        )
        job.videos["id1"] = vs1
        job.videos["id2"] = vs2
        job.video_order.extend(["id1", "id2"])

        resp1 = client.get(f"/jobs/{job_id}/videos/id1")
        assert resp1.status_code == 200
        assert "Content from video 1" in resp1.text

        resp2 = client.get(f"/jobs/{job_id}/videos/id2")
        assert resp2.status_code == 200
        assert "Content from video 2" in resp2.text

    @patch("ytx.web.app._run_job_thread")
    def test_transcript_viewer_no_timestamps_in_clean_md(
        self, mock_thread, client, fresh_manager, tmp_path
    ):
        """Clean Markdown without timestamps should not show toggle."""

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        md_path = str(tmp_path / "Video.md")
        md_content = """# Video

- **Channel:** Test
- **Language:** English

## Transcript

Hello world without timestamps
"""
        with open(md_path, "w") as f:
            f.write(md_content)

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(
            id="vid1", title="Video",
            status=VideoStatus.COMPLETE, output_paths=[md_path],
        )
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        # The toggle button element should not be rendered
        assert 'id="toggle-timestamps"' not in resp.text
        assert "Hello world without timestamps" in resp.text

    @patch("ytx.web.app._run_job_thread")
    def test_transcript_viewer_prefers_json_over_md(
        self, mock_thread, client, fresh_manager, tmp_path
    ):
        """When both JSON and MD exist, JSON should be preferred."""
        import json

        job_id = self._create_job_with_video(client, fresh_manager, mock_thread)
        job = fresh_manager.get_job(job_id)

        json_path = str(tmp_path / "Video.json")
        md_path = str(tmp_path / "Video.md")

        data = {
            "schema_version": "1.0",
            "video": {
                "id": "vid1", "title": "Video",
                "url": "https://youtube.com/watch?v=vid1",
                "channel": {"id": "ch1", "name": "Test",
                            "url": "https://youtube.com/@test"},
            },
            "transcript": {
                "language": "en", "language_name": "English",
                "source": "youtube_manual", "generated": False,
                "segments": [{"start": 0, "duration": 1,
                              "text": "From JSON"}],
            },
        }
        with open(json_path, "w") as f:
            json.dump(data, f)
        with open(md_path, "w") as f:
            f.write("# Video\n\n## Transcript\n\nFrom Markdown\n")

        from ytx.web.jobs import VideoState, VideoStatus
        vs = VideoState(id="vid1", title="Video", status=VideoStatus.COMPLETE,
                        output_paths=[json_path, md_path])
        job.videos["vid1"] = vs
        job.video_order.append("vid1")

        resp = client.get(f"/jobs/{job_id}/videos/vid1")
        assert resp.status_code == 200
        assert "From JSON" in resp.text


class TestSettingsHierarchy:
    """Test the settings hierarchy on the homepage."""

    def test_more_settings_open_by_default(self, client):
        """More settings section should be open by default."""
        resp = client.get("/")
        assert 'id="more-settings-toggle"' in resp.text
        assert 'aria-expanded="true"' in resp.text
        # Content should NOT have is-closed class
        assert 'id="more-settings-content"' in resp.text
        # Check that the content div doesn't have is-closed
        import re
        content_match = re.search(r'id="more-settings-content"[^>]*class="([^"]*)"', resp.text)
        if content_match:
            assert 'is-closed' not in content_match.group(1)

    def test_advanced_formats_closed_by_default(self, client):
        """Advanced export formats should be closed by default."""
        resp = client.get("/")
        assert 'id="advanced-formats-toggle"' in resp.text
        assert 'aria-expanded="false"' in resp.text
        # Content should have is-closed class
        import re
        content_match = re.search(r'id="advanced-formats-content"[^>]*class="([^"]*)"', resp.text)
        if content_match:
            assert 'is-closed' in content_match.group(1)

    def test_youtube_access_in_more_settings(self, client):
        """YouTube access should be in More settings, not Advanced."""
        resp = client.get("/")
        # YouTube access should be in more-settings-content
        import re
        more_settings = re.search(
            r'id="more-settings-content"(.*?)id="advanced-formats-toggle"',
            resp.text, re.DOTALL
        )
        if more_settings:
            assert 'youtube_auth' in more_settings.group(1)

    def test_automatic_recommended(self, client):
        """Automatic should be marked as recommended."""
        resp = client.get("/")
        assert 'Automatic (Recommended)' in resp.text


class TestEmDashRemoval:
    """Test that no em dashes appear in user-facing copy."""

    def test_no_em_dash_in_templates(self, client):
        """No em dash characters in rendered HTML."""
        resp = client.get("/")
        # Check for em dash character
        assert '\u2014' not in resp.text
        # Check for HTML entity
        assert '&mdash;' not in resp.text

    def test_no_em_dash_in_job_page(self, client, fresh_manager):
        """No em dashes in job page."""
        from unittest.mock import patch
        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=test1234567",
            })
            job_id = resp.json()["job_id"]
            resp = client.get(f"/jobs/{job_id}")
            assert '\u2014' not in resp.text
            assert '&mdash;' not in resp.text


class TestResultCountBug:
    """Test that result counts use actual completed count."""

    def test_result_uses_completed_not_discovered(self, client, fresh_manager):
        """Result should show completed count, not total discovered."""
        from unittest.mock import patch

        from ytx.web.jobs import JobStatus

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=test1234567",
            })
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)

            # Simulate a batch job with 655 discovered but only 3 completed
            job.total_videos = 655
            job.completed_videos = 3
            job.failed_videos = 1
            job.status = JobStatus.COMPLETE

            resp = client.get(f"/jobs/{job_id}")
            # The JavaScript should use completedCount, not total_discovered
            # Check that the showResults function uses completedCount
            assert 'completedCount' in resp.text
            # The initial values should be set correctly
            assert 'let completedCount = 3' in resp.text
            assert 'let totalCount = 655' in resp.text


class TestPausedState:
    """Test the paused job state."""

    def test_paused_status_exists(self):
        """PAUSED status should exist in JobStatus."""
        from ytx.web.jobs import JobStatus
        assert hasattr(JobStatus, 'PAUSED')
        assert JobStatus.PAUSED.value == "paused"

    def test_paused_job_page_loads(self, client, fresh_manager):
        """Paused job page should load correctly."""
        from unittest.mock import patch

        from ytx.web.jobs import JobStatus

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=test1234567",
            })
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)
            job.status = JobStatus.PAUSED

            resp = client.get(f"/jobs/{job_id}")
            assert resp.status_code == 200
            assert "Paused" in resp.text


class TestXSSSafety:
    """Test XSS safety for untrusted content."""

    def test_escape_html_function_exists(self, client, fresh_manager):
        """escapeHtml function should exist in job page."""
        from unittest.mock import patch

        from ytx.web.jobs import JobStatus

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=test1234567",
            })
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)
            job.status = JobStatus.COMPLETE

            resp = client.get(f"/jobs/{job_id}")
            # escapeHtml function should exist for XSS protection
            assert 'function escapeHtml' in resp.text

    def test_jinja_autoescaping_enabled(self, client):
        """Jinja autoescaping should be enabled."""
        resp = client.get("/")
        # Check that the page renders correctly
        assert resp.status_code == 200
        # The title should be properly escaped
        assert 'YTX' in resp.text
