"""Tests for processing metrics and text utilities."""

from __future__ import annotations

from ytx.models import DurationSummary, ProcessingMetrics, VideoMetadata
from ytx.utils.text import (
    format_duration_human,
    format_duration_seconds,
    format_speed_x,
    pluralize,
)


class TestPluralize:
    def test_singular(self):
        assert pluralize(1, "video") == "1 video"

    def test_plural(self):
        assert pluralize(5, "video") == "5 videos"

    def test_zero(self):
        assert pluralize(0, "video") == "0 videos"

    def test_custom_plural(self):
        assert pluralize(0, "failure", "failures") == "0 failures"

    def test_custom_plural_singular(self):
        assert pluralize(1, "failure", "failures") == "1 failure"

    def test_transcript(self):
        assert pluralize(1, "transcript") == "1 transcript"
        assert pluralize(460, "transcript") == "460 transcripts"

    def test_segment(self):
        assert pluralize(1, "segment") == "1 segment"
        assert pluralize(460, "segment") == "460 segments"


class TestFormatDuration:
    def test_none(self):
        assert format_duration_seconds(None) == ""

    def test_zero(self):
        assert format_duration_seconds(0) == "0:00"

    def test_seconds_only(self):
        assert format_duration_seconds(45) == "0:45"

    def test_minutes_seconds(self):
        assert format_duration_seconds(1122) == "18:42"

    def test_hours(self):
        assert format_duration_seconds(3661) == "1:01:01"

    def test_negative(self):
        assert format_duration_seconds(-5) == ""


class TestFormatSpeed:
    def test_none(self):
        assert format_speed_x(None) == ""

    def test_normal(self):
        assert format_speed_x(6.06) == "6.1x realtime"

    def test_slow(self):
        assert format_speed_x(1.5) == "1.5x realtime"


class TestProcessingMetrics:
    def test_to_dict(self):
        m = ProcessingMetrics(
            video_duration_seconds=1122.0,
            transcription_elapsed_seconds=185.0,
            processing_elapsed_seconds=199.0,
            transcription_model="base",
            transcription_language="tr",
            segment_count=460,
            transcription_speed_x=6.06,
        )
        d = m.to_dict()
        assert d["video_duration_seconds"] == 1122.0
        assert d["transcription_elapsed_seconds"] == 185.0
        assert d["segment_count"] == 460
        assert d["transcription_speed_x"] == 6.06

    def test_from_dict(self):
        d = {
            "video_duration_seconds": 1122.0,
            "transcription_elapsed_seconds": 185.0,
            "processing_elapsed_seconds": 199.0,
            "transcription_model": "base",
            "transcription_language": "tr",
            "segment_count": 460,
            "transcription_speed_x": 6.06,
        }
        m = ProcessingMetrics.from_dict(d)
        assert m.video_duration_seconds == 1122.0
        assert m.segment_count == 460

    def test_from_dict_missing_fields(self):
        """Old manifests without metrics fields should still load."""
        m = ProcessingMetrics.from_dict({})
        assert m.video_duration_seconds is None
        assert m.segment_count is None

    def test_from_dict_partial(self):
        m = ProcessingMetrics.from_dict({"segment_count": 100})
        assert m.segment_count == 100
        assert m.video_duration_seconds is None


class TestFormatDurationHuman:
    def test_none(self):
        assert format_duration_human(None) == ""

    def test_zero(self):
        assert format_duration_human(0) == ""

    def test_negative(self):
        assert format_duration_human(-5) == ""

    def test_seconds_only(self):
        assert format_duration_human(45) == "45s"

    def test_minutes_seconds(self):
        assert format_duration_human(192) == "3m 12s"

    def test_minutes_only(self):
        assert format_duration_human(300) == "5m 00s"

    def test_hours(self):
        assert format_duration_human(5040) == "1h 24m"

    def test_large_hours(self):
        assert format_duration_human(502127) == "139h 28m"

    def test_exactly_one_hour(self):
        assert format_duration_human(3600) == "1h 00m"

    def test_59_seconds(self):
        assert format_duration_human(59) == "59s"

    def test_one_minute(self):
        assert format_duration_human(60) == "1m 00s"


class TestDurationSummary:
    def _make_video(self, vid: str, duration: float | None) -> VideoMetadata:
        return VideoMetadata(
            id=vid,
            title=f"Video {vid}",
            url=f"https://youtube.com/watch?v={vid}",
            channel="Test Channel",
            duration_seconds=duration,
        )

    def test_empty_list(self):
        dur = DurationSummary.from_videos([])
        assert dur.known_count == 0
        assert dur.missing_count == 0
        assert dur.total_seconds == 0.0

    def test_all_valid(self):
        videos = [
            self._make_video("a", 100.0),
            self._make_video("b", 200.0),
            self._make_video("c", 300.0),
        ]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 3
        assert dur.missing_count == 0
        assert dur.total_seconds == 600.0
        assert dur.average_seconds == 200.0
        assert dur.shortest_seconds == 100.0
        assert dur.longest_seconds == 300.0

    def test_some_missing(self):
        videos = [
            self._make_video("a", 100.0),
            self._make_video("b", None),
            self._make_video("c", 300.0),
        ]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 2
        assert dur.missing_count == 1
        assert dur.total_seconds == 400.0
        assert dur.average_seconds == 200.0
        assert dur.shortest_seconds == 100.0
        assert dur.longest_seconds == 300.0

    def test_all_missing(self):
        videos = [
            self._make_video("a", None),
            self._make_video("b", None),
        ]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 0
        assert dur.missing_count == 2
        assert dur.total_seconds == 0.0
        assert dur.average_seconds == 0.0

    def test_zero_duration_treated_as_missing(self):
        videos = [self._make_video("a", 0.0)]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 0
        assert dur.missing_count == 1

    def test_negative_duration_treated_as_missing(self):
        videos = [self._make_video("a", -10.0)]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 0
        assert dur.missing_count == 1

    def test_single_video(self):
        videos = [self._make_video("a", 1122.0)]
        dur = DurationSummary.from_videos(videos)
        assert dur.known_count == 1
        assert dur.missing_count == 0
        assert dur.total_seconds == 1122.0
        assert dur.average_seconds == 1122.0
        assert dur.shortest_seconds == 1122.0
        assert dur.longest_seconds == 1122.0

    def test_to_dict(self):
        dur = DurationSummary(
            known_count=3,
            missing_count=1,
            total_seconds=600.0,
            average_seconds=200.0,
            shortest_seconds=100.0,
            longest_seconds=300.0,
        )
        d = dur.to_dict()
        assert d["known_count"] == 3
        assert d["missing_count"] == 1
        assert d["total_seconds"] == 600.0
        assert d["average_seconds"] == 200.0
        assert d["shortest_seconds"] == 100.0
        assert d["longest_seconds"] == 300.0
