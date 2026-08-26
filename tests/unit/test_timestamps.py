"""Tests for timestamp formatting."""

from ytx.utils.timestamps import format_duration, format_timestamp_short, format_timestamp_srt


class TestFormatTimestampSRT:
    def test_zero(self):
        assert format_timestamp_srt(0.0) == "00:00:00,000"

    def test_seconds(self):
        assert format_timestamp_srt(5.5) == "00:00:05,500"

    def test_minutes(self):
        assert format_timestamp_srt(65.0) == "00:01:05,000"

    def test_hours(self):
        assert format_timestamp_srt(3661.5) == "01:01:01,500"

    def test_negative(self):
        assert format_timestamp_srt(-1.0) == "00:00:00,000"

    def test_precision(self):
        result = format_timestamp_srt(1.234)
        assert result == "00:00:01,234"


class TestFormatTimestampShort:
    def test_zero(self):
        assert format_timestamp_short(0.0) == "00:00"

    def test_under_hour(self):
        assert format_timestamp_short(65.0) == "01:05"

    def test_over_hour(self):
        assert format_timestamp_short(3661.0) == "01:01:01"

    def test_negative(self):
        assert format_timestamp_short(-1.0) == "00:00"


class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == "unknown"

    def test_seconds(self):
        assert format_duration(45) == "0:45"

    def test_minutes(self):
        assert format_duration(125) == "2:05"

    def test_hours(self):
        assert format_duration(3661) == "1:01:01"
