"""Tests for skip-existing with combined output."""

from __future__ import annotations

import json
import os

from ytx.models import (
    ChannelInfo,
    ProcessingStatus,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    VideoMetadata,
)
from ytx.output.combined import write_combined_jsonl, write_combined_markdown
from ytx.pipeline import load_saved_transcript
from ytx.state.manifest import Manifest


def _make_video(video_id: str, title: str) -> VideoMetadata:
    return VideoMetadata(
        id=video_id,
        title=title,
        url=f"https://youtube.com/watch?v={video_id}",
        channel=ChannelInfo(id="ch1", name="Test Channel", url="https://youtube.com/@test"),
    )


def _make_transcript() -> Transcript:
    return Transcript(
        language="en",
        language_name="English",
        source=TranscriptSource.YOUTUBE_AUTO,
        is_generated=True,
        segments=[
            TranscriptSegment(start=0.0, duration=2.0, text="Hello world"),
            TranscriptSegment(start=2.0, duration=3.0, text="This is a test"),
        ],
    )


def _write_json_transcript(path: str, video: VideoMetadata, transcript: Transcript) -> None:
    """Write a transcript JSON file in the expected schema."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "schema_version": "1.0",
        "video": {
            "id": video.id,
            "title": video.title,
            "url": video.url,
            "channel": {
                "id": video.channel.id,
                "name": video.channel.name,
                "url": video.channel.url,
            },
            "published_at": None,
            "duration_seconds": 120,
        },
        "transcript": {
            "language": transcript.language,
            "language_name": transcript.language_name,
            "requested_language": transcript.requested_language,
            "source": transcript.source.value,
            "generated": transcript.is_generated,
            "segments": [
                {"start": s.start, "duration": s.duration, "text": s.text}
                for s in transcript.segments
            ],
        },
        "generated_by": {"tool": "ytx", "version": "0.1.0"},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class TestLoadSavedTranscript:
    def test_load_valid_json(self, tmp_path):
        video = _make_video("vid1", "Test Video")
        transcript = _make_transcript()
        path = str(tmp_path / "transcript.json")
        _write_json_transcript(path, video, transcript)

        loaded = load_saved_transcript(path)
        assert loaded is not None
        assert loaded.language == "en"
        assert loaded.source == TranscriptSource.YOUTUBE_AUTO
        assert len(loaded.segments) == 2
        assert loaded.segments[0].text == "Hello world"

    def test_load_missing_file(self, tmp_path):
        loaded = load_saved_transcript(str(tmp_path / "nonexistent.json"))
        assert loaded is None

    def test_load_invalid_json(self, tmp_path):
        path = str(tmp_path / "transcript.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")
        loaded = load_saved_transcript(path)
        assert loaded is None

    def test_load_missing_transcript_key(self, tmp_path):
        path = str(tmp_path / "transcript.json")
        with open(path, "w") as f:
            json.dump({"schema_version": "1.0"}, f)
        loaded = load_saved_transcript(path)
        assert loaded is None


class TestCombinedWithSkipExisting:
    def test_three_completed_videos_combined(self, tmp_path):
        """All 3 videos completed, skip-existing should still produce combined output."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        videos = [
            _make_video("vid1", "Video 1"),
            _make_video("vid2", "Video 2"),
            _make_video("vid3", "Video 3"),
        ]

        # Write transcript JSON for each video
        for video in videos:
            video_dir = os.path.join(base_dir, f"{video.title}_{video.id}")
            path = os.path.join(video_dir, "transcript.json")
            _write_json_transcript(path, video, _make_transcript())

        # Create manifest marking all as complete
        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_source("channel", "https://youtube.com/@test", "ch1")
        for video in videos:
            video_dir = os.path.join(base_dir, f"{video.title}_{video.id}")
            manifest.set_video_status(
                video.id,
                ProcessingStatus.COMPLETE,
                transcript_source=TranscriptSource.YOUTUBE_AUTO,
                output_paths=[os.path.join(video_dir, "transcript.json")],
            )
        manifest.save()

        # Simulate loading existing transcripts (what skip-existing should do)
        results = []
        for video in videos:
            if manifest.get_video_status(video.id) == ProcessingStatus.COMPLETE:
                output_paths = manifest.get_video_output_paths(video.id)
                json_path = next(
                    (p for p in output_paths if p.endswith("transcript.json")), None
                )
                if json_path and os.path.exists(json_path):
                    transcript = load_saved_transcript(json_path)
                    if transcript:
                        results.append(TranscriptResult(video=video, transcript=transcript))

        assert len(results) == 3

        # Write combined output
        write_combined_jsonl(results, os.path.join(base_dir, "combined.jsonl"))
        write_combined_markdown(results, os.path.join(base_dir, "combined.md"))

        # Verify JSONL
        jsonl_path = os.path.join(base_dir, "combined.jsonl")
        assert os.path.exists(jsonl_path)
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "video_id" in data
            assert "segments" in data

        # Verify combined MD
        md_path = os.path.join(base_dir, "combined.md")
        assert os.path.exists(md_path)
        with open(md_path) as f:
            content = f.read()
        assert "Video 1" in content
        assert "Video 2" in content
        assert "Video 3" in content

    def test_mixed_new_and_skipped(self, tmp_path):
        """Mix of newly processed and skipped videos in combined output."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        video1 = _make_video("vid1", "Existing Video")
        video2 = _make_video("vid2", "New Video")
        video3 = _make_video("vid3", "Another Existing")

        # Write existing transcripts for vid1 and vid3
        for video in [video1, video3]:
            video_dir = os.path.join(base_dir, f"{video.title}_{video.id}")
            _write_json_transcript(
                os.path.join(video_dir, "transcript.json"), video, _make_transcript()
            )

        # Simulate: vid1 skipped, vid2 newly processed, vid3 skipped
        results = []

        # vid1: skipped, load from disk
        video1_dir = os.path.join(base_dir, f"{video1.title}_{video1.id}")
        t1 = load_saved_transcript(os.path.join(video1_dir, "transcript.json"))
        results.append(TranscriptResult(video=video1, transcript=t1))

        # vid2: newly processed
        results.append(TranscriptResult(video=video2, transcript=_make_transcript()))

        # vid3: skipped, load from disk
        video3_dir = os.path.join(base_dir, f"{video3.title}_{video3.id}")
        t3 = load_saved_transcript(os.path.join(video3_dir, "transcript.json"))
        results.append(TranscriptResult(video=video3, transcript=t3))

        assert len(results) == 3

        # Write combined
        jsonl_path = os.path.join(base_dir, "combined.jsonl")
        write_combined_jsonl(results, jsonl_path)

        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 3
        ids = [json.loads(line)["video_id"] for line in lines]
        assert ids == ["vid1", "vid2", "vid3"]

    def test_combined_respects_selection_not_all_files(self, tmp_path):
        """Combined output contains only selected videos, not all on disk."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        # Create 10 video transcripts on disk
        all_videos = []
        for i in range(10):
            video = _make_video(f"vid{i}", f"Video {i}")
            all_videos.append(video)
            video_dir = os.path.join(base_dir, f"{video.title}_{video.id}")
            _write_json_transcript(
                os.path.join(video_dir, "transcript.json"), video, _make_transcript()
            )

        # But only select 3 (simulating --latest 3)
        selected = all_videos[:3]
        results = []
        for video in selected:
            video_dir = os.path.join(base_dir, f"{video.title}_{video.id}")
            t = load_saved_transcript(os.path.join(video_dir, "transcript.json"))
            results.append(TranscriptResult(video=video, transcript=t))

        jsonl_path = os.path.join(base_dir, "combined.jsonl")
        write_combined_jsonl(results, jsonl_path)

        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 3
        ids = [json.loads(line)["video_id"] for line in lines]
        assert ids == ["vid0", "vid1", "vid2"]

    def test_corrupt_json_not_included(self, tmp_path):
        """Corrupt JSON should result in None, not a crash."""
        path = str(tmp_path / "transcript.json")
        with open(path, "w") as f:
            f.write('{"schema_version": "1.0", "transcript": CORRUPT}')

        result = load_saved_transcript(path)
        assert result is None

    def test_jsonl_valid_parsing(self, tmp_path):
        """Every line in JSONL must be valid JSON."""
        videos = [_make_video(f"vid{i}", f"Video {i}") for i in range(5)]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript()) for v in videos
        ]

        jsonl_path = str(tmp_path / "combined.jsonl")
        write_combined_jsonl(results, jsonl_path)

        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                data = json.loads(line)
                assert data["video_id"] == f"vid{i}"
                assert len(data["segments"]) == 2

    def test_combined_markdown_content(self, tmp_path):
        """Combined Markdown contains video titles and transcript text."""
        videos = [
            _make_video("vid1", "First Video"),
            _make_video("vid2", "Second Video"),
        ]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript()) for v in videos
        ]

        md_path = str(tmp_path / "combined.md")
        write_combined_markdown(results, md_path)

        with open(md_path) as f:
            content = f.read()
        assert "First Video" in content
        assert "Second Video" in content
        assert "Hello world" in content
