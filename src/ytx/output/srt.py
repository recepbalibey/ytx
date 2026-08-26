"""SRT subtitle output writer."""

from __future__ import annotations

import os
import tempfile

from ytx.models import TranscriptResult
from ytx.utils.timestamps import format_timestamp_srt


def write_srt(
    result: TranscriptResult,
    output_path: str,
    include_timestamps: bool = True,
) -> str:
    """Write transcript as SRT subtitle file."""
    if result.transcript is None:
        raise ValueError("No transcript to write")

    lines: list[str] = []
    for i, seg in enumerate(result.transcript.segments, start=1):
        start_ts = format_timestamp_srt(seg.start)
        end_ts = format_timestamp_srt(seg.end)
        lines.append(str(i))
        lines.append(f"{start_ts} --> {end_ts}")
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
