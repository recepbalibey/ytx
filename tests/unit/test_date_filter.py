"""Tests for date filtering behavior."""

from datetime import datetime

from ytx.models import ChannelInfo, VideoMetadata
from ytx.youtube.discovery import _passes_date_filter


def _make_video(published_at: datetime | None = None) -> VideoMetadata:
    return VideoMetadata(
        id="test123",
        title="Test",
        url="https://youtube.com/watch?v=test123",
        channel=ChannelInfo(id="ch1", name="Ch", url="https://youtube.com/@ch"),
        published_at=published_at,
    )


class TestDateFilter:
    def test_no_filter_passes_all(self):
        video = _make_video(published_at=None)
        assert _passes_date_filter(video, after=None, before=None) is True

    def test_date_inside_range(self):
        video = _make_video(published_at=datetime(2025, 6, 15))
        assert _passes_date_filter(
            video,
            after=datetime(2025, 1, 1),
            before=datetime(2025, 12, 31),
        ) is True

    def test_date_before_range(self):
        video = _make_video(published_at=datetime(2024, 6, 15))
        assert _passes_date_filter(
            video,
            after=datetime(2025, 1, 1),
            before=None,
        ) is False

    def test_date_after_range(self):
        video = _make_video(published_at=datetime(2026, 6, 15))
        assert _passes_date_filter(
            video,
            after=None,
            before=datetime(2025, 12, 31),
        ) is False

    def test_exact_boundary_after_inclusive(self):
        """--after is inclusive: video on exact boundary date passes."""
        video = _make_video(published_at=datetime(2025, 1, 1))
        assert _passes_date_filter(
            video, after=datetime(2025, 1, 1), before=None
        ) is True

    def test_exact_boundary_before_inclusive(self):
        """--before is inclusive: video on exact boundary date passes."""
        video = _make_video(published_at=datetime(2025, 12, 31))
        assert _passes_date_filter(
            video, after=None, before=datetime(2025, 12, 31)
        ) is True

    def test_unknown_date_no_filter(self):
        """Without date filters, unknown dates pass through."""
        video = _make_video(published_at=None)
        assert _passes_date_filter(video, after=None, before=None) is True

    def test_unknown_date_with_after_filter(self):
        """With --after, unknown dates are skipped."""
        video = _make_video(published_at=None)
        assert _passes_date_filter(
            video, after=datetime(2025, 1, 1), before=None
        ) is False

    def test_unknown_date_with_before_filter(self):
        """With --before, unknown dates are skipped."""
        video = _make_video(published_at=None)
        assert _passes_date_filter(
            video, after=None, before=datetime(2025, 12, 31)
        ) is False

    def test_unknown_date_with_both_filters(self):
        """With both filters, unknown dates are skipped."""
        video = _make_video(published_at=None)
        assert _passes_date_filter(
            video, after=datetime(2025, 1, 1), before=datetime(2025, 12, 31)
        ) is False
