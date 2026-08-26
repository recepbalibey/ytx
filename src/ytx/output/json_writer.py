"""JSON output writer."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from ytx.config import APP_VERSION, SCHEMA_VERSION
from ytx.models import TranscriptResult


def write_json(
    result: TranscriptResult,
    output_path: str,
    include_timestamps: bool = True,
) -> str:
    """Write transcript as structured JSON."""
    if result.transcript is None:
        raise ValueError("No transcript to write")

    video = result.video
    transcript = result.transcript

    data = {
        "schema_version": SCHEMA_VERSION,
        "video": {
            "id": video.id,
            "title": video.title,
            "url": video.url,
            "channel": {
                "id": video.channel.id,
                "name": video.channel.name,
                "url": video.channel.url,
            },
            "published_at": video.published_at.isoformat() if video.published_at else None,
            "duration_seconds": video.duration_seconds,
        },
        "transcript": {
            "language": transcript.language,
            "language_name": transcript.language_name,
            "requested_language": transcript.requested_language,
            "source": transcript.source.value,
            "generated": transcript.is_generated,
            "segments": [
                {
                    "start": round(seg.start, 3),
                    "duration": round(seg.duration, 3),
                    "text": seg.text,
                }
                for seg in transcript.segments
            ],
        },
        "generated_by": {
            "tool": "ytx",
            "version": APP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    if result.metrics:
        data["processing_metrics"] = result.metrics.to_dict()

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
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
