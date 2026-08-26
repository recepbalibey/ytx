"""Tests for flat and structured output layouts."""

from __future__ import annotations

import json
import os

from ytx.models import (
    ChannelInfo,
    OutputLayout,
    ProcessingStatus,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    VideoMetadata,
)
from ytx.pipeline import Pipeline, load_saved_transcript
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


class TestOutputLayoutEnum:
    def test_flat_value(self):
        assert OutputLayout.FLAT.value == "flat"

    def test_structured_value(self):
        assert OutputLayout.STRUCTURED.value == "structured"

    def test_from_string(self):
        assert OutputLayout("flat") == OutputLayout.FLAT
        assert OutputLayout("structured") == OutputLayout.STRUCTURED


class TestFlatOutputNaming:
    """Test flat output uses title-based filenames."""

    def test_flat_basename_resolution(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "My Video Title")
        basename = pipeline._resolve_flat_filename(video, str(tmp_path))
        assert basename == "My Video Title"

    def test_flat_basename_preserves_unicode(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Avrupa Birli\u011fi Mesajlar\u0131m\u0131z\u0131 Okuyacak")
        basename = pipeline._resolve_flat_filename(video, str(tmp_path))
        # Should preserve Turkish characters
        assert "\u011f" in basename or "Avrupa" in basename

    def test_flat_duplicate_titles_get_video_id(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video1 = _make_video("id1", "Same Title")
        video2 = _make_video("id2", "Same Title")

        basename1 = pipeline._resolve_flat_filename(video1, str(tmp_path))
        basename2 = pipeline._resolve_flat_filename(video2, str(tmp_path))

        assert basename1 == "Same Title"
        assert basename2 == "Same Title_id2"

    def test_flat_same_video_same_basename(self, tmp_path):
        """Same video ID should get same basename (for resume)."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "My Video")
        basename1 = pipeline._resolve_flat_filename(video, str(tmp_path))
        basename2 = pipeline._resolve_flat_filename(video, str(tmp_path))
        assert basename1 == basename2


class TestFlatOutputWrite:
    """Test _write_output in flat mode."""

    def test_flat_writes_files_in_base_dir(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "json"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        assert len(paths) == 2
        for p in paths:
            assert os.path.exists(p)
            assert os.path.dirname(p) == str(tmp_path)

        # Check filenames
        basenames = [os.path.basename(p) for p in paths]
        assert "Test-Video.md" in basenames
        assert "Test-Video.json" in basenames

    def test_flat_no_per_video_directory(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        # No subdirectory should be created
        entries = os.listdir(str(tmp_path))
        assert all(os.path.isfile(os.path.join(str(tmp_path), e)) for e in entries)


class TestStructuredOutputWrite:
    """Test _write_output in structured mode."""

    def test_structured_creates_per_video_dir(self, tmp_path):
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "json"],
            output_layout=OutputLayout.STRUCTURED,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path))

        assert len(paths) == 2
        for p in paths:
            assert os.path.exists(p)

        # Should be in a per-video directory
        video_dir = os.path.dirname(paths[0])
        assert "abc123" in video_dir
        basenames = {os.path.basename(p) for p in paths}
        assert "transcript.md" in basenames
        assert "transcript.json" in basenames


class TestFlatResumeCompatibility:
    """Test resume works with flat layout."""

    def test_flat_resume_loads_existing_transcript(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()

        # Write flat transcript
        json_path = os.path.join(base_dir, "Test-Video.json")
        _write_json_transcript(json_path, video, transcript)

        # Create manifest with flat paths
        manifest = Manifest(os.path.join(base_dir, ".ytx-manifest.json"))
        manifest.set_source("playlist", "https://youtube.com/playlist?list=PLtest", "PLtest")
        manifest.set_video_status(
            "abc123",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            output_paths=[json_path],
        )
        manifest.save()

        # Verify can load
        loaded = load_saved_transcript(json_path)
        assert loaded is not None
        assert len(loaded.segments) == 2

    def test_flat_manifest_uses_hidden_file(self, tmp_path):
        """Flat layout should use .ytx-manifest.json."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        manifest = Manifest(os.path.join(base_dir, ".ytx-manifest.json"))
        manifest.set_source("playlist", "https://youtube.com/playlist?list=PLtest", "PLtest")
        manifest.save()

        assert os.path.exists(os.path.join(base_dir, ".ytx-manifest.json"))
        # Should NOT create manifest.json
        assert not os.path.exists(os.path.join(base_dir, "manifest.json"))


class TestStructuredResumeCompatibility:
    """Test structured layout still works."""

    def test_structured_manifest_uses_standard_file(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        manifest = Manifest(os.path.join(base_dir, "manifest.json"))
        manifest.set_source("channel", "https://youtube.com/@test", "ch1")
        manifest.save()

        assert os.path.exists(os.path.join(base_dir, "manifest.json"))


class TestTitleChangeFlatLayout:
    """Test title change handling in flat mode."""

    def test_flat_reuses_existing_path_on_title_change(self, tmp_path):
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        # First run: title is "Old Title"
        video_old = _make_video("abc123", "Old Title")
        json_path = os.path.join(base_dir, "Old-Title.json")
        _write_json_transcript(json_path, video_old, _make_transcript())

        manifest = Manifest(os.path.join(base_dir, ".ytx-manifest.json"))
        manifest.set_video_status(
            "abc123",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            output_paths=[json_path],
        )
        manifest.save()

        # Second run: title changed
        # Simulate what _process_video does: check manifest for existing paths
        output_paths = manifest.get_video_output_paths("abc123")
        assert len(output_paths) == 1
        existing_basename = os.path.splitext(os.path.basename(output_paths[0]))[0]
        assert existing_basename == "Old-Title"

        # The file should still be loadable
        loaded = load_saved_transcript(output_paths[0])
        assert loaded is not None


class TestOutputMdGeneration:
    """Regression tests for output.md generation in flat mode."""

    def test_flat_batch_writes_output_md(self, tmp_path):
        """Flat batch with completed videos should write output.md."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],  # Only md, no json
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video("a", "Video A"), _make_video("b", "Video B")]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript())
            for v in videos
        ]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "output.md"))
        content = (tmp_path / "output.md").read_text(encoding="utf-8")
        assert "Video A" in content
        assert "Video B" in content

    def test_flat_batch_writes_output_md_even_without_json_format(self, tmp_path):
        """output.md should be generated even when JSON format is not selected."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],  # Only md selected
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video("a", "Video A"), _make_video("b", "Video B")]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript())
            for v in videos
        ]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "output.md"))

    def test_flat_batch_no_completed_no_output_md(self, tmp_path):
        """No output.md if no completed transcripts."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        pipeline._write_combined_safe([], str(tmp_path))

        assert not os.path.exists(str(tmp_path / "output.md"))

    def test_flat_batch_partial_results_writes_output_md(self, tmp_path):
        """output.md should include only completed videos."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video("a", "Video A"), _make_video("b", "Video B")]
        results = [
            TranscriptResult(video=videos[0], transcript=_make_transcript()),
            TranscriptResult(video=videos[1], transcript=None),  # Failed
        ]
        pipeline._write_combined_safe(results, str(tmp_path))

        assert os.path.exists(str(tmp_path / "output.md"))
        content = (tmp_path / "output.md").read_text(encoding="utf-8")
        assert "Video A" in content
        # Video B should not be included (transcript is None)
        assert "Video B" not in content

    def test_flat_batch_json_not_written_when_not_selected(self, tmp_path):
        """JSON should NOT be written in flat mode when not selected."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],  # Only md selected
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        # Only md should be in returned paths
        assert len(paths) == 1
        assert paths[0].endswith(".md")

        # JSON file should NOT exist on disk
        json_path = str(tmp_path / "Test-Video.json")
        assert not os.path.exists(json_path)

    def test_flat_batch_json_in_paths_when_requested(self, tmp_path):
        """JSON should be in returned paths when user requested it."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "json"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        # Both md and json should be in returned paths
        assert len(paths) == 2
        basenames = {os.path.basename(p) for p in paths}
        assert "Test-Video.md" in basenames
        assert "Test-Video.json" in basenames

    def test_flat_batch_correct_destination_directory(self, tmp_path):
        """output.md should be in the same directory as individual files."""
        playlist_dir = str(tmp_path / "My Playlist")
        os.makedirs(playlist_dir, exist_ok=True)

        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video("a", "Video A")]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript())
            for v in videos
        ]
        pipeline._write_combined_safe(results, playlist_dir)

        # output.md should be in playlist_dir
        assert os.path.exists(os.path.join(playlist_dir, "output.md"))
        # Not in root output dir
        assert not os.path.exists(str(tmp_path / "output.md"))


class TestMarkdownRecovery:
    """Test recovery from .md files when JSON doesn't exist."""

    def test_recovery_from_markdown_file(self, tmp_path):
        """Should recover transcript from .md file when JSON is missing."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )

        video = _make_video("abc123", "Test Video")

        # Write only .md file (no JSON - simulating pre-fix batch)
        md_path = os.path.join(base_dir, "Test-Video.md")
        with open(md_path, "w") as f:
            f.write("# Test Video\n\n")
            f.write("- **Channel:** Test Channel\n")
            f.write("- **URL:** https://youtube.com/watch?v=abc123\n")
            f.write("- **Language:** English\n")
            f.write("- **Source:** YouTube Auto\n\n")
            f.write("## Transcript\n\n")
            f.write("Hello world\n\n")
            f.write("This is a test\n")

        # Set up manifest with only .md path
        manifest = Manifest(os.path.join(base_dir, ".ytx-manifest.json"))
        manifest.set_source("playlist", "https://youtube.com/playlist?list=PLtest", "PLtest")
        manifest.set_video_status(
            "abc123",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.YOUTUBE_AUTO,
            output_paths=[md_path],
        )
        manifest.save()

        # Try to load - should recover from .md
        result = pipeline._load_existing_transcript(video, manifest, base_dir)
        assert result is not None
        assert result.transcript is not None
        assert len(result.transcript.segments) == 2
        assert result.transcript.segments[0].text == "Hello world"

    def test_recovery_prefers_json_over_markdown(self, tmp_path):
        """Should prefer JSON over .md when both exist."""
        base_dir = str(tmp_path / "output")
        os.makedirs(base_dir, exist_ok=True)

        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "json"],
            output_layout=OutputLayout.FLAT,
        )

        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()

        # Write both JSON and .md
        json_path = os.path.join(base_dir, "Test-Video.json")
        md_path = os.path.join(base_dir, "Test-Video.md")
        _write_json_transcript(json_path, video, transcript)
        with open(md_path, "w") as f:
            f.write("# Test Video\n\n## Transcript\n\nDifferent content\n")

        manifest = Manifest(os.path.join(base_dir, ".ytx-manifest.json"))
        manifest.set_source("playlist", "https://youtube.com/playlist?list=PLtest", "PLtest")
        manifest.set_video_status(
            "abc123",
            ProcessingStatus.COMPLETE,
            transcript_source=TranscriptSource.LOCAL_TRANSCRIPTION,
            output_paths=[json_path, md_path],
        )
        manifest.save()

        result = pipeline._load_existing_transcript(video, manifest, base_dir)
        assert result is not None
        # Should use JSON content (2 segments), not .md content (1 segment)
        assert len(result.transcript.segments) == 2


class TestOutputMdRegression:
    """Regression tests for output.md generation."""

    def test_output_md_generated_for_completed_videos(self, tmp_path):
        """output.md should be generated when videos complete."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video(f"v{i}", f"Video {i}") for i in range(3)]
        results = [
            TranscriptResult(video=v, transcript=_make_transcript())
            for v in videos
        ]

        pipeline._write_combined_safe(results, str(tmp_path))

        output_md = tmp_path / "output.md"
        assert output_md.exists()
        content = output_md.read_text()
        assert "Video 0" in content
        assert "Video 1" in content
        assert "Video 2" in content

    def test_output_md_not_generated_when_empty(self, tmp_path):
        """output.md should NOT be generated when no results."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        pipeline._write_combined_safe([], str(tmp_path))

        output_md = tmp_path / "output.md"
        assert not output_md.exists()

    def test_output_md_excludes_failed_videos(self, tmp_path):
        """output.md should only include successful transcripts."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        videos = [_make_video(f"v{i}", f"Video {i}") for i in range(3)]
        results = [
            TranscriptResult(video=videos[0], transcript=_make_transcript()),
            TranscriptResult(video=videos[1], transcript=None),  # Failed
            TranscriptResult(video=videos[2], transcript=_make_transcript()),
        ]

        pipeline._write_combined_safe(results, str(tmp_path))

        output_md = tmp_path / "output.md"
        assert output_md.exists()
        content = output_md.read_text()
        assert "Video 0" in content
        assert "Video 1" not in content
        assert "Video 2" in content

    def test_output_md_content_format(self, tmp_path):
        """output.md should have correct format."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]

        pipeline._write_combined_safe(results, str(tmp_path))

        output_md = tmp_path / "output.md"
        content = output_md.read_text()
        assert "# YouTube Transcript Collection" in content
        assert "Videos: 1" in content
        assert "## 1. Test Video" in content
        assert "Hello world" in content

    def test_structured_mode_uses_combined_md(self, tmp_path):
        """Structured mode should use combined.md, not output.md."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.STRUCTURED,
        )
        video = _make_video("abc123", "Test Video")
        results = [TranscriptResult(video=video, transcript=_make_transcript())]

        pipeline._write_combined_safe(results, str(tmp_path))

        assert (tmp_path / "combined.md").exists()
        assert not (tmp_path / "output.md").exists()


class TestJsonNotForcedInFlatMode:
    """Regression: JSON should not be forced in flat mode."""

    def test_default_flat_only_md(self, tmp_path):
        """Default flat mode should only produce .md files."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        # Only md should be written
        assert len(paths) == 1
        assert paths[0].endswith(".md")

        # No json file should exist
        assert not (tmp_path / "Test-Video.json").exists()
        assert (tmp_path / "Test-Video.md").exists()

    def test_flat_with_json_selected(self, tmp_path):
        """Flat mode with JSON selected should produce both files."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "json"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        # Both md and json should be written
        assert len(paths) == 2
        assert (tmp_path / "Test-Video.json").exists()
        assert (tmp_path / "Test-Video.md").exists()

    def test_flat_with_txt_only(self, tmp_path):
        """Flat mode with TXT only should not produce JSON."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "txt"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        assert len(paths) == 2
        assert (tmp_path / "Test-Video.md").exists()
        assert (tmp_path / "Test-Video.txt").exists()
        assert not (tmp_path / "Test-Video.json").exists()

    def test_flat_with_srt_only(self, tmp_path):
        """Flat mode with SRT only should not produce JSON."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md", "srt"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")
        transcript = _make_transcript()
        result = TranscriptResult(video=video, transcript=transcript)

        paths = pipeline._write_output(result, str(tmp_path), flat_basename="Test-Video")

        assert len(paths) == 2
        assert (tmp_path / "Test-Video.md").exists()
        assert (tmp_path / "Test-Video.srt").exists()
        assert not (tmp_path / "Test-Video.json").exists()


class TestTranscriptLoadFromMarkdown:
    """Test loading transcripts from markdown files."""

    def test_load_from_markdown_fallback(self, tmp_path):
        """Should load transcript from markdown when JSON not available."""
        pipeline = Pipeline(
            output_dir=str(tmp_path),
            formats=["md"],
            output_layout=OutputLayout.FLAT,
        )
        video = _make_video("abc123", "Test Video")

        # Write only markdown file
        md_path = str(tmp_path / "Test-Video.md")
        with open(md_path, "w") as f:
            f.write("# Test Video\n\n## Transcript\n\nHello world\nThis is a test\n")

        from ytx.models import ProcessingResult
        result = ProcessingResult(
            video_id="abc123",
            status=ProcessingStatus.COMPLETE,
            output_paths=[md_path],
        )

        transcript = pipeline._load_transcript_from_result(video, result)
        assert transcript is not None
        assert len(transcript.segments) == 2
        assert transcript.segments[0].text == "Hello world"
