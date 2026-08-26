"""Tests for transcript normalization."""

from ytx.models import Transcript, TranscriptSegment, TranscriptSource
from ytx.transcripts.normalize import normalize_transcript, normalize_whitespace


class TestNormalizeWhitespace:
    def test_single_spaces(self):
        assert normalize_whitespace("hello world") == "hello world"

    def test_multiple_spaces(self):
        assert normalize_whitespace("hello  world") == "hello world"

    def test_tabs_and_newlines(self):
        assert normalize_whitespace("hello\t\nworld") == "hello world"

    def test_leading_trailing(self):
        assert normalize_whitespace("  hello  ") == "hello"


class TestNormalizeTranscript:
    def test_normalizes_whitespace(self):
        transcript = Transcript(
            language="en",
            language_name="English",
            source=TranscriptSource.YOUTUBE_AUTO,
            is_generated=True,
            segments=[
                TranscriptSegment(start=0.0, duration=1.0, text="  hello  "),
                TranscriptSegment(start=1.0, duration=1.0, text="world  "),
            ],
        )
        result = normalize_transcript(transcript)
        assert result.segments[0].text == "hello"
        assert result.segments[1].text == "world"

    def test_removes_empty_segments(self):
        transcript = Transcript(
            language="en",
            language_name="English",
            source=TranscriptSource.YOUTUBE_AUTO,
            is_generated=True,
            segments=[
                TranscriptSegment(start=0.0, duration=1.0, text="hello"),
                TranscriptSegment(start=1.0, duration=1.0, text="  "),
                TranscriptSegment(start=2.0, duration=1.0, text="world"),
            ],
        )
        result = normalize_transcript(transcript)
        assert len(result.segments) == 2
        assert result.segments[0].text == "hello"
        assert result.segments[1].text == "world"

    def test_preserves_metadata(self):
        transcript = Transcript(
            language="de",
            language_name="German",
            source=TranscriptSource.YOUTUBE_MANUAL,
            is_generated=False,
            segments=[TranscriptSegment(start=0.0, duration=1.0, text="hallo")],
        )
        result = normalize_transcript(transcript)
        assert result.language == "de"
        assert result.language_name == "German"
        assert result.source == TranscriptSource.YOUTUBE_MANUAL
        assert result.is_generated is False
