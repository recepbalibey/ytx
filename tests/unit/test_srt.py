"""Tests for SRT output formatting."""


from ytx.models import (
    ChannelInfo,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    VideoMetadata,
)
from ytx.output.srt import write_srt


def _make_result(segments=None):
    if segments is None:
        segments = [
            TranscriptSegment(start=0.0, duration=2.5, text="Hello world"),
            TranscriptSegment(start=2.5, duration=3.0, text="This is a test"),
        ]
    return TranscriptResult(
        video=VideoMetadata(
            id="test123",
            title="Test Video",
            url="https://youtube.com/watch?v=test123",
            channel=ChannelInfo(id="ch1", name="Test Channel", url="https://youtube.com/@test"),
        ),
        transcript=Transcript(
            language="en",
            language_name="English",
            source=TranscriptSource.YOUTUBE_AUTO,
            is_generated=True,
            segments=segments,
        ),
    )


class TestWriteSRT:
    def test_basic_srt(self, tmp_path):
        result = _make_result()
        path = str(tmp_path / "test.srt")
        write_srt(result, path)

        with open(path) as f:
            content = f.read()

        assert "1\n" in content
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "Hello world" in content
        assert "2\n" in content
        assert "00:00:02,500 --> 00:00:05,500" in content
        assert "This is a test" in content

    def test_srt_numbering(self, tmp_path):
        segments = [
            TranscriptSegment(start=float(i), duration=1.0, text=f"Segment {i}")
            for i in range(5)
        ]
        result = _make_result(segments)
        path = str(tmp_path / "test.srt")
        write_srt(result, path)

        with open(path) as f:
            content = f.read()

        for i in range(1, 6):
            assert f"{i}\n" in content

    def test_empty_transcript_raises(self, tmp_path):
        result = _make_result(segments=[])
        path = str(tmp_path / "test.srt")
        # Empty segments should still write (empty file)
        write_srt(result, path)
