"""Tests for JSON output."""

import json

from ytx.models import (
    ChannelInfo,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    VideoMetadata,
)
from ytx.output.json_writer import write_json


def _make_result():
    return TranscriptResult(
        video=VideoMetadata(
            id="abc123",
            title="Test Video",
            url="https://youtube.com/watch?v=abc123",
            channel=ChannelInfo(id="ch1", name="Test Channel", url="https://youtube.com/@test"),
            duration_seconds=120,
        ),
        transcript=Transcript(
            language="en",
            language_name="English",
            source=TranscriptSource.YOUTUBE_AUTO,
            is_generated=True,
            segments=[
                TranscriptSegment(start=0.0, duration=2.5, text="Hello world"),
                TranscriptSegment(start=2.5, duration=3.0, text="This is a test"),
            ],
        ),
    )


class TestWriteJSON:
    def test_valid_json(self, tmp_path):
        result = _make_result()
        path = str(tmp_path / "test.json")
        write_json(result, path)

        with open(path) as f:
            data = json.load(f)

        assert data["schema_version"] == "1.0"
        assert data["video"]["id"] == "abc123"
        assert data["video"]["title"] == "Test Video"
        assert data["video"]["channel"]["name"] == "Test Channel"
        assert data["video"]["duration_seconds"] == 120
        assert data["transcript"]["language"] == "en"
        assert data["transcript"]["source"] == "youtube_auto"
        assert len(data["transcript"]["segments"]) == 2
        assert data["transcript"]["segments"][0]["text"] == "Hello world"
        assert data["transcript"]["segments"][0]["start"] == 0.0
        assert "generated_by" in data
        assert data["generated_by"]["tool"] == "ytx"

    def test_segment_precision(self, tmp_path):
        result = _make_result()
        result.transcript.segments = [
            TranscriptSegment(start=1.234567, duration=2.345678, text="test"),
        ]
        path = str(tmp_path / "test.json")
        write_json(result, path)

        with open(path) as f:
            data = json.load(f)

        seg = data["transcript"]["segments"][0]
        assert seg["start"] == 1.235
        assert seg["duration"] == 2.346

    def test_requested_language_in_output(self, tmp_path):
        result = _make_result()
        result.transcript.requested_language = "de"
        path = str(tmp_path / "test.json")
        write_json(result, path)

        with open(path) as f:
            data = json.load(f)

        assert data["transcript"]["requested_language"] == "de"
        assert data["transcript"]["language"] == "en"

    def test_requested_language_none(self, tmp_path):
        result = _make_result()
        path = str(tmp_path / "test.json")
        write_json(result, path)

        with open(path) as f:
            data = json.load(f)

        assert data["transcript"]["requested_language"] is None
