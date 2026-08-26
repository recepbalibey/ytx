"""Plain text output writer."""

from __future__ import annotations

import os
import tempfile

from ytx.models import TranscriptResult
from ytx.utils.timestamps import format_timestamp_short


def write_txt(
    result: TranscriptResult,
    output_path: str,
    include_timestamps: bool = True,
) -> str:
    """Write transcript as plain text."""
    if result.transcript is None:
        raise ValueError("No transcript to write")

    lines: list[str] = []
    for seg in result.transcript.segments:
        if include_timestamps:
            ts = format_timestamp_short(seg.start)
            lines.append(f"[{ts}] {seg.text}")
        else:
            lines.append(seg.text)

    content = "\n".join(lines) + "\n"
    _atomic_write(output_path, content)
    return output_path


def _atomic_write(path: str, content: str) -> None:
    """Write content atomically using a temp file and rename."""
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
