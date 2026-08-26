"""Markdown output writer."""

from __future__ import annotations

import os
import tempfile

from ytx.models import TranscriptResult
from ytx.utils.timestamps import format_duration, format_timestamp_short


def write_markdown(
    result: TranscriptResult,
    output_path: str,
    include_timestamps: bool = True,
) -> str:
    """Write transcript as Markdown with metadata header."""
    if result.transcript is None:
        raise ValueError("No transcript to write")

    video = result.video
    transcript = result.transcript

    lines: list[str] = []
    lines.append(f"# {video.title}")
    lines.append("")
    lines.append(f"- **Channel:** {video.channel.name}")
    lines.append(f"- **URL:** {video.url}")
    if video.published_at:
        lines.append(f"- **Published:** {video.published_at.strftime('%Y-%m-%d')}")
    if video.duration_seconds:
        lines.append(f"- **Duration:** {format_duration(video.duration_seconds)}")
    lines.append(f"- **Language:** {transcript.language_name}")
    source_label = transcript.source.value.replace("_", " ").title()
    lines.append(f"- **Source:** {source_label}")
    lines.append("")
    lines.append("## Transcript")
    lines.append("")

    for seg in transcript.segments:
        if include_timestamps:
            ts = format_timestamp_short(seg.start)
            lines.append(f"**{ts}**")
            lines.append("")
            lines.append(seg.text)
            lines.append("")
        else:
            lines.append(seg.text)
            lines.append("")

    content = "\n".join(lines)
    _atomic_write(output_path, content)
    return output_path


def _atomic_write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path) or ".",
        prefix=".tmp_",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise
