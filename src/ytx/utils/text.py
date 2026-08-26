"""Text formatting utilities."""

from __future__ import annotations


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """Return count with appropriate singular/plural form.

    Examples:
        pluralize(1, "video") -> "1 video"
        pluralize(5, "video") -> "5 videos"
        pluralize(1, "transcript") -> "1 transcript"
        pluralize(0, "failure", "failures") -> "0 failures"
    """
    if plural is None:
        plural = singular + "s"
    word = singular if count == 1 else plural
    return f"{count} {word}"


def format_duration_seconds(seconds: float | int | None) -> str:
    """Format seconds into human-readable duration.

    Examples:
        format_duration_seconds(1122) -> "18:42"
        format_duration_seconds(3661) -> "1:01:01"
        format_duration_seconds(None) -> ""
    """
    if seconds is None:
        return ""
    total = int(seconds)
    if total < 0:
        return ""
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_speed_x(speed: float | None) -> str:
    """Format realtime speed multiplier.

    Examples:
        format_speed_x(6.06) -> "6.1x realtime"
        format_speed_x(None) -> ""
    """
    if speed is None:
        return ""
    return f"{speed:.1f}x realtime"


def format_duration_human(total_seconds: float | int | None) -> str:
    """Format seconds into human-friendly duration like '139h 35m' or '3m 12s'.

    Omits seconds when total is >= 1 hour.
    Returns empty string for None/invalid values.

    Examples:
        format_duration_human(45) -> "45s"
        format_duration_human(192) -> "3m 12s"
        format_duration_human(3009) -> "50m 09s"
        format_duration_human(5040) -> "1h 24m"
        format_duration_human(502127) -> "139h 29m"
        format_duration_human(None) -> ""
        format_duration_human(0) -> ""
        format_duration_human(-5) -> ""
    """
    if total_seconds is None:
        return ""
    total = int(total_seconds)
    if total <= 0:
        return ""

    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60

    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"
