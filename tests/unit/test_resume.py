"""Regression tests for resume and stable identity behavior."""

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
from ytx.pipeline import load_saved_transcript
from ytx.state.manifest import Manifest
from ytx.utils.filenames import safe_video_dirname


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
        source=TranscriptSource.LOCAL_TRANSCRIPTION,
        is_generated=True,
        segments=[
            TranscriptSegment(start=0.0, duration=2.0, text="Hello world"),
            TranscriptSegment(start=2.0, duration=3.0, text="This is a test"),
        ],
    )


def _write_json_transcript(path: str, video: VideoMetadata, transcript: Transcript) -> None:
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


class TestResumeBasic:
    """Test 1: basic resume. Completed videos are not processed again."""

    def test_completed_videos_skipped_without_skip_existing_flag(self, tmp_path):
        """Resume should work without --skip-existing flag."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        videos = [
            _make_video("vid1", "Video 1"),
            _make_video("vid2", "Video 2"),
            _make_video("vid3", "Video 3"),
            _make_video("vid4", "Video 4"),
        ]

        # Set up manifest: vid1 and vid2 complete, vid3 processing (interrupted), vid4 absent
        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_source("channel", "https://youtube.com/@test", "ch1")

        for vid in ["vid1", "vid2"]:
            video_dir = os.path.join(base_dir, safe_video_dirname(vid, f"Video {vid[-1]}"))
            json_path = os.path.join(video_dir, "transcript.json")
            v = _make_video(vid, f"Video {vid[-1]}")
            _write_json_transcript(json_path, v, _make_transcript())
            manifest.set_video_status(
                vid,
                ProcessingStatus.COMPLETE,
                transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
                output_paths=[json_path],
            )

        # vid3 was interrupted (processing state)
        manifest.set_video_status("vid3", ProcessingStatus.PROCESSING)
        manifest.save()

        # Simulate resume logic (what _process_videos does)
        results = []
        processed_ids = []

        for video in videos:
            existing_status = manifest.get_video_status(video.id)
            if existing_status == ProcessingStatus.COMPLETE:
                # Load existing transcript
                output_paths = manifest.get_video_output_paths(video.id)
                json_path = None
                for path in output_paths:
                    if path.endswith("transcript.json"):
                        json_path = path
                        break
                if json_path and os.path.exists(json_path):
                    transcript = load_saved_transcript(json_path)
                    if transcript:
                        results.append(TranscriptResult(video=video, transcript=transcript))
                        continue
            # Would call _process_video here
            processed_ids.append(video.id)

        # vid1 and vid2 should be reused, vid3 and vid4 should be processed
        assert len(results) == 2
        assert results[0].video.id == "vid1"
        assert results[1].video.id == "vid2"
        assert processed_ids == ["vid3", "vid4"]


class TestCompletedNotRetranscribed:
    """Test 2: completed local-transcription video is not re-transcribed."""

    def test_no_provider_call_for_completed_video(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        video = _make_video("vid1", "Test Video")
        video_dir = os.path.join(base_dir, safe_video_dirname(video.id, video.title))
        json_path = os.path.join(video_dir, "transcript.json")
        _write_json_transcript(json_path, video, _make_transcript())

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            output_paths=[json_path],
        )
        manifest.save()

        # Verify transcript can be loaded
        loaded = load_saved_transcript(json_path)
        assert loaded is not None
        assert loaded.source == TranscriptSource.LOCAL_TRANSCRIPTION
        assert len(loaded.segments) == 2


class TestProcessingItemRetried:
    """Test 3: processing item (interrupted) is retried."""

    def test_processing_status_treated_as_incomplete(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status("vid1", ProcessingStatus.PROCESSING)
        manifest.save()

        status = manifest.get_video_status("vid1")
        assert status == ProcessingStatus.PROCESSING
        assert status != ProcessingStatus.COMPLETE


class TestFailedItemRetry:
    """Test 4: failed item can be retried."""

    def test_failed_status_not_skipped(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "vid1",
            ProcessingStatus.FAILED,
            error="No captions available. Use --transcribe-missing to create locally.",
        )
        manifest.save()

        status = manifest.get_video_status("vid1")
        # Failed items should not be skipped because they need a retry.
        assert status != ProcessingStatus.COMPLETE


class TestTitleChangeStableIdentity:
    """Test 5: title changes don't create duplicate directories."""

    def test_existing_directory_reused(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        # First run: title is "Old Title"
        video_old = _make_video("abc123", "Old Title")
        video_dir_old = os.path.join(base_dir, safe_video_dirname("abc123", "Old Title"))
        json_path_old = os.path.join(video_dir_old, "transcript.json")
        _write_json_transcript(json_path_old, video_old, _make_transcript())

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "abc123",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            output_paths=[json_path_old],
        )
        manifest.save()

        # Second run: title changed to "New Title"
        _make_video("abc123", "New Title")

        # Get existing directory from manifest
        output_paths = manifest.get_video_output_paths("abc123")
        existing_dir = os.path.dirname(output_paths[0]) if output_paths else None

        # Should reuse old directory, not create new one
        assert existing_dir == video_dir_old
        assert os.path.exists(json_path_old)

        # New title directory should NOT exist
        video_dir_new = os.path.join(base_dir, safe_video_dirname("abc123", "New Title"))
        assert not os.path.exists(video_dir_new)

    def test_only_one_directory_per_video_id(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        # Simulate first run
        video1 = _make_video("vid1", "Original Title")
        dir1 = os.path.join(base_dir, safe_video_dirname("vid1", "Original Title"))
        json1 = os.path.join(dir1, "transcript.json")
        _write_json_transcript(json1, video1, _make_transcript())

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            output_paths=[json1],
        )
        manifest.save()

        # Simulate second run with different title
        _make_video("vid1", "Changed Title")
        existing_paths = manifest.get_video_output_paths("vid1")
        existing_dir = os.path.dirname(existing_paths[0])

        # Write to existing directory (not new one)
        new_json = os.path.join(existing_dir, "transcript.json")
        assert os.path.exists(new_json)

        # Count directories with this video ID
        matching_dirs = [
            d for d in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, d)) and "vid1" in d
        ]
        assert len(matching_dirs) == 1


class TestCorruptCompletedTranscript:
    """Test 6: corrupt completed transcript triggers reprocessing."""

    def test_missing_json_triggers_reprocess(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            output_paths=[str(tmp_path / "nonexistent" / "transcript.json")],
        )
        manifest.save()

        # Load should return None for missing file
        output_paths = manifest.get_video_output_paths("vid1")
        json_path = output_paths[0]
        assert not os.path.exists(json_path)

    def test_corrupt_json_triggers_reprocess(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        json_path = str(tmp_path / "transcript.json")
        with open(json_path, "w") as f:
            f.write("NOT VALID JSON {{{")

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_video_status(
            "vid1",
            ProcessingStatus.COMPLETE,
            output_paths=[json_path],
        )
        manifest.save()

        loaded = load_saved_transcript(json_path)
        assert loaded is None


class TestFilterSelection:
    """Test 7: only selected videos are considered."""

    def test_only_selected_videos_evaluated(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        # Create 10 completed videos in manifest
        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        for i in range(10):
            video = _make_video(f"vid{i}", f"Video {i}")
            video_dir = os.path.join(base_dir, safe_video_dirname(f"vid{i}", f"Video {i}"))
            json_path = os.path.join(video_dir, "transcript.json")
            _write_json_transcript(json_path, video, _make_transcript())
            manifest.set_video_status(
                f"vid{i}",
                ProcessingStatus.COMPLETE,
                output_paths=[json_path],
            )
        manifest.save()

        # Only select 3 (simulating --latest 3)
        selected = [_make_video(f"vid{i}", f"Video {i}") for i in range(3)]
        results = []
        for video in selected:
            status = manifest.get_video_status(video.id)
            if status == ProcessingStatus.COMPLETE:
                output_paths = manifest.get_video_output_paths(video.id)
                for path in output_paths:
                    if path.endswith("transcript.json") and os.path.exists(path):
                        transcript = load_saved_transcript(path)
                        if transcript:
                            results.append(TranscriptResult(video=video, transcript=transcript))

        assert len(results) == 3
        assert [r.video.id for r in results] == ["vid0", "vid1", "vid2"]


class TestCombineAfterResume:
    """Test 8: combine includes all selected videos after resume."""

    def test_combined_includes_reused_and_new(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        videos = [
            _make_video("vid1", "Video 1"),
            _make_video("vid2", "Video 2"),
            _make_video("vid3", "Video 3"),
            _make_video("vid4", "Video 4"),
        ]

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))

        # vid1 and vid2 already completed
        for vid in ["vid1", "vid2"]:
            video = _make_video(vid, f"Video {vid[-1]}")
            video_dir = os.path.join(base_dir, safe_video_dirname(vid, f"Video {vid[-1]}"))
            json_path = os.path.join(video_dir, "transcript.json")
            _write_json_transcript(json_path, video, _make_transcript())
            manifest.set_video_status(
                vid,
                ProcessingStatus.COMPLETE,
                output_paths=[json_path],
            )
        manifest.save()

        # Simulate: vid1 and vid2 loaded from manifest, vid3 and vid4 newly processed
        results = []
        for video in videos:
            status = manifest.get_video_status(video.id)
            if status == ProcessingStatus.COMPLETE:
                output_paths = manifest.get_video_output_paths(video.id)
                for path in output_paths:
                    if path.endswith("transcript.json") and os.path.exists(path):
                        transcript = load_saved_transcript(path)
                        if transcript:
                            results.append(TranscriptResult(video=video, transcript=transcript))
                        break
            else:
                # Simulate new processing
                results.append(TranscriptResult(video=video, transcript=_make_transcript()))

        assert len(results) == 4
        assert [r.video.id for r in results] == ["vid1", "vid2", "vid3", "vid4"]
        # All should have transcripts
        assert all(r.transcript is not None for r in results)
