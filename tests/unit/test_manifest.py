"""Tests for manifest state management."""

import json

from ytx.models import ProcessingMetrics, ProcessingStatus, TranscriptSource
from ytx.state.manifest import Manifest


class TestManifest:
    def test_create_new(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        assert m.video_ids == []

    def test_set_source(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        m.set_source("channel", "https://youtube.com/@test", "UC123")
        m.save()

        with open(path) as f:
            data = json.load(f)
        assert data["source"]["type"] == "channel"
        assert data["source"]["url"] == "https://youtube.com/@test"

    def test_video_status_lifecycle(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)

        # Initially None
        assert m.get_video_status("vid1") is None

        # Set to processing
        m.set_video_status("vid1", ProcessingStatus.PROCESSING)
        assert m.get_video_status("vid1") == ProcessingStatus.PROCESSING

        # Set to complete
        m.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.YOUTUBE_AUTO,
        )
        assert m.get_video_status("vid1") == ProcessingStatus.COMPLETE

    def test_counts(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        m.set_video_status("v1", ProcessingStatus.COMPLETE)
        m.set_video_status("v2", ProcessingStatus.COMPLETE)
        m.set_video_status("v3", ProcessingStatus.FAILED, error="test")
        m.set_video_status("v4", ProcessingStatus.PENDING)

        counts = m.get_counts()
        assert counts.get("complete") == 2
        assert counts.get("failed") == 1
        assert counts.get("pending") == 1

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m1 = Manifest(path)
        m1.set_source("playlist", "url", "id1")
        m1.set_video_status("vid1", ProcessingStatus.COMPLETE)
        m1.save()

        m2 = Manifest(path)
        assert m2.get_video_status("vid1") == ProcessingStatus.COMPLETE

    def test_pending_video_ids(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        m.set_video_status("v1", ProcessingStatus.COMPLETE)
        m.set_video_status("v2", ProcessingStatus.FAILED)
        m.set_video_status("v3", ProcessingStatus.PENDING)

        pending = m.pending_video_ids()
        assert "v1" not in pending
        assert "v2" in pending
        assert "v3" in pending

    def test_schema_version(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        m.save()

        with open(path) as f:
            data = json.load(f)
        assert data["schema_version"] == 1

    def test_metrics_storage(self, tmp_path):
        """Metrics should persist in manifest."""
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        metrics = ProcessingMetrics(
            video_duration_seconds=1122.0,
            transcription_elapsed_seconds=185.0,
            transcription_model="base",
            segment_count=460,
            transcription_speed_x=6.06,
        )
        m.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            metrics=metrics,
        )
        m.save()

        with open(path) as f:
            data = json.load(f)
        assert "metrics" in data["videos"]["vid1"]
        assert data["videos"]["vid1"]["metrics"]["segment_count"] == 460

    def test_metrics_load(self, tmp_path):
        """Metrics should load from manifest."""
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        metrics = ProcessingMetrics(
            video_duration_seconds=1122.0,
            segment_count=460,
        )
        m.set_video_status("vid1", ProcessingStatus.COMPLETE, metrics=metrics)
        m.save()

        m2 = Manifest(path)
        loaded = m2.get_video_metrics("vid1")
        assert loaded is not None
        assert loaded.video_duration_seconds == 1122.0
        assert loaded.segment_count == 460

    def test_metrics_none_for_missing(self, tmp_path):
        """get_video_metrics returns None for video without metrics."""
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        m.set_video_status("vid1", ProcessingStatus.COMPLETE)
        assert m.get_video_metrics("vid1") is None

    def test_old_manifest_compatibility(self, tmp_path):
        """Old manifests without metrics should still load."""
        path = str(tmp_path / "manifest.json")
        # Write an old-format manifest
        with open(path, "w") as f:
            json.dump({
                "schema_version": 1,
                "source": {"type": "playlist", "url": "url", "id": "id1"},
                "videos": {
                    "vid1": {
                        "status": "complete",
                        "transcript_source": "youtube_auto",
                        "output_paths": ["/tmp/transcript.json"],
                    }
                },
            }, f)

        m = Manifest(path)
        assert m.get_video_status("vid1") == ProcessingStatus.COMPLETE
        assert m.get_video_output_paths("vid1") == ["/tmp/transcript.json"]
        assert m.get_video_metrics("vid1") is None
