"""Tests for manual video selection and output.md features."""

from __future__ import annotations

import os

import pytest

from ytx.models import (
    ChannelInfo,
    DurationSummary,
    OutputLayout,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    VideoMetadata,
)
from ytx.output.combined import write_output_md
from ytx.pipeline import Pipeline


def _make_video(video_id: str, title: str, duration: int | None = 120) -> VideoMetadata:
    return VideoMetadata(
        id=video_id,
        title=title,
        url=f"https://youtube.com/watch?v={video_id}",
        channel=ChannelInfo(id="ch1", name="Test Channel", url="https://youtube.com/@test"),
        duration_seconds=duration,
    )


def _make_transcript(text: str = "Hello world") -> Transcript:
    return Transcript(
        language="en",
        language_name="English",
        source=TranscriptSource.LOCAL_TRANSCRIPTION,
        is_generated=True,
        segments=[
            TranscriptSegment(start=0.0, duration=2.0, text=text),
        ],
    )


class TestFilterSelectedVideos:
    def test_no_selection_returns_all(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=None,
        )
        videos = [_make_video("a", "A"), _make_video("b", "B"), _make_video("c", "C")]
        result = pipeline._filter_selected_videos(videos)
        assert len(result) == 3

    def test_empty_selection_returns_none(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=[],
        )
        videos = [_make_video("a", "A"), _make_video("b", "B")]
        result = pipeline._filter_selected_videos(videos)
        assert len(result) == 0

    def test_filters_to_selected_ids(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=["a", "c"],
        )
        videos = [_make_video("a", "A"), _make_video("b", "B"), _make_video("c", "C")]
        result = pipeline._filter_selected_videos(videos)
        assert len(result) == 2
        assert [v.id for v in result] == ["a", "c"]

    def test_preserves_order(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=["c", "a"],
        )
        videos = [_make_video("a", "A"), _make_video("b", "B"), _make_video("c", "C")]
        result = pipeline._filter_selected_videos(videos)
        assert [v.id for v in result] == ["a", "c"]

    def test_nonexistent_ids_ignored(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=["a", "nonexistent", "c"],
        )
        videos = [_make_video("a", "A"), _make_video("b", "B"), _make_video("c", "C")]
        result = pipeline._filter_selected_videos(videos)
        assert len(result) == 2
        assert [v.id for v in result] == ["a", "c"]


class TestSelectedVideoIdsInPipeline:
    def test_stores_selected_ids(self, tmp_path):
        ids = ["vid1", "vid2", "vid3"]
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            selected_video_ids=ids,
        )
        assert pipeline.selected_video_ids == ids

    def test_default_none(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
        )
        assert pipeline.selected_video_ids is None


class TestOutputMd:
    def test_basic_output_md(self, tmp_path):
        videos = [_make_video("a", "Video A"), _make_video("b", "Video B")]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript(f"Text for {v.id}"))
            for v in videos
        ]
        out_path = str(tmp_path / "output.md")
        write_output_md(results, out_path)

        with open(out_path) as f:
            content = f.read()
        assert "# YouTube Transcript Collection" in content
        assert "Videos: 2" in content
        assert "## 1. Video A" in content
        assert "## 2. Video B" in content
        assert "Text for a" in content
        assert "Text for b" in content

    def test_output_md_includes_metadata(self, tmp_path):
        video = _make_video("a", "Test Video")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]
        out_path = str(tmp_path / "output.md")
        write_output_md(results, out_path)

        with open(out_path) as f:
            content = f.read()
        assert "URL: https://youtube.com/watch?v=a" in content
        assert "Language: English" in content
        assert "Transcript source: Local Transcription" in content

    def test_output_md_skips_none_transcripts(self, tmp_path):
        videos = [_make_video("a", "A"), _make_video("b", "B")]
        results = [
            TranscriptResult(video=videos[0], transcript=_make_transcript("Good")),
            TranscriptResult(video=videos[1], transcript=None),
        ]
        out_path = str(tmp_path / "output.md")
        write_output_md(results, out_path)

        with open(out_path) as f:
            content = f.read()
        assert "Videos: 1" in content
        assert "## 1. A" in content
        assert "## 2." not in content

    def test_output_md_no_timestamps(self, tmp_path):
        video = _make_video("a", "Test")
        transcript = _make_transcript("Plain text only")
        results = [TranscriptResult(video=video, transcript=transcript)]
        out_path = str(tmp_path / "output.md")
        write_output_md(results, out_path)

        with open(out_path) as f:
            content = f.read()
        assert "00:00" not in content

    def test_output_md_atomic_write(self, tmp_path):
        video = _make_video("a", "Test")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]
        out_path = str(tmp_path / "output.md")
        write_output_md(results, out_path)

        files = os.listdir(str(tmp_path))
        tmp_files = [f for f in files if f.startswith(".tmp_")]
        assert len(tmp_files) == 0


class TestCombinedSafeOutputMd:
    def test_flat_mode_writes_output_md(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("a", "Test")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "output.md"))
        assert not os.path.exists(str(tmp_path / "combined.md"))

    def test_structured_mode_writes_combined_md(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.STRUCTURED,
        )
        video = _make_video("a", "Test")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "combined.md"))
        assert not os.path.exists(str(tmp_path / "output.md"))

    def test_flat_mode_jsonl_still_works(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
            combine_jsonl=True,
        )
        video = _make_video("a", "Test")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "output.md"))
        assert os.path.exists(str(tmp_path / "combined.jsonl"))

    def test_empty_results_no_file(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        pipeline._write_combined_safe([], str(tmp_path))

        assert not os.path.exists(str(tmp_path / "output.md"))


class TestDurationSummarySelection:
    def test_basic_summary(self):
        videos = [
            _make_video("a", "A", 100),
            _make_video("b", "B", 200),
            _make_video("c", "C", 300),
        ]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 3
        assert dur.missing_count == 0
        assert dur.total_seconds == 600.0
        assert dur.shortest_seconds == 100.0
        assert dur.longest_seconds == 300.0

    def test_missing_durations(self):
        videos = [
            _make_video("a", "A", 100),
            _make_video("b", "B", None),
            _make_video("c", "C", 0),
        ]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 1
        assert dur.missing_count == 2

    def test_empty_list(self):
        dur = DurationSummary.from_videos([])
        assert dur.known_count == 0
        assert dur.total_seconds == 0.0


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


class TestManualSelectionWebAPI:
    def test_discover_endpoint_requires_url(self, client):
        resp = client.get("/api/discover")
        assert resp.status_code == 400

    def test_discover_endpoint_rejects_video_url(self, client):
        resp = client.get("/api/discover?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert resp.status_code == 400

    def test_detect_url_endpoint(self, client):
        resp = client.get("/api/detect-url?url=https://www.youtube.com/playlist?list=PLtest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "playlist"

    def test_detect_url_empty(self, client):
        resp = client.get("/api/detect-url")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] is None


class TestManualSelectionJobParams:
    def test_job_accepts_selected_video_ids(self, client, fresh_manager):
        from unittest.mock import patch

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/playlist?list=PLtest",
                "selected_video_ids": ["vid1", "vid2"],
            })
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)
            assert job.selected_video_ids == ["vid1", "vid2"]

    def test_job_without_selected_video_ids(self, client, fresh_manager):
        from unittest.mock import patch

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/playlist?list=PLtest",
            })
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)
            assert job.selected_video_ids is None


class TestCombinedFileDetection:
    def test_output_md_detected(self, client, fresh_manager, tmp_path):
        from unittest.mock import patch

        with patch("ytx.web.app._run_job_thread"):
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/playlist?list=PLtest",
            })
            job_id = resp.json()["job_id"]
            job = fresh_manager.get_job(job_id)

            output_dir = str(tmp_path / "output")
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "output.md"), "w") as f:
                f.write("# Test")

            job.output_directory = output_dir

            resp = client.get(f"/jobs/{job_id}/status")
            data = resp.json()
            assert "output.md" in data["combined_files"]
