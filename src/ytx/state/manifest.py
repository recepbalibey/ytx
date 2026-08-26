"""State management for resume and skip-existing support."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from ytx.config import MANIFEST_SCHEMA_VERSION
from ytx.models import ProcessingMetrics, ProcessingStatus, TranscriptSource


class Manifest:
    """Manages processing state for a batch job (playlist/channel).

    Stored as manifest.json in the output directory.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """Load existing manifest or create a new one."""
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("schema_version") == MANIFEST_SCHEMA_VERSION:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source": {},
            "videos": {},
        }

    def set_source(self, source_type: str, url: str, source_id: str) -> None:
        """Set the source metadata for this manifest."""
        self._data["source"] = {
            "type": source_type,
            "url": url,
            "id": source_id,
        }

    def get_video_status(self, video_id: str) -> ProcessingStatus | None:
        """Get the processing status of a video."""
        entry = self._data["videos"].get(video_id)
        if entry is None:
            return None
        return ProcessingStatus(entry["status"])

    def get_video_output_paths(self, video_id: str) -> list[str]:
        """Get the saved output paths for a completed video."""
        entry = self._data["videos"].get(video_id)
        if entry is None:
            return []
        return entry.get("output_paths", [])

    def get_video_metrics(self, video_id: str) -> ProcessingMetrics | None:
        """Get the saved processing metrics for a video."""
        entry = self._data["videos"].get(video_id)
        if entry is None or "metrics" not in entry:
            return None
        return ProcessingMetrics.from_dict(entry["metrics"])

    def set_video_status(
        self,
        video_id: str,
        status: ProcessingStatus,
        transcript_source: TranscriptSource | None = None,
        error: str | None = None,
        output_paths: list[str] | None = None,
        metrics: ProcessingMetrics | None = None,
    ) -> None:
        """Update the status of a video."""
        entry: dict[str, Any] = {
            "status": status.value,
        }
        if transcript_source:
            entry["transcript_source"] = transcript_source.value
        if error:
            entry["error"] = error
        if output_paths:
            entry["output_paths"] = output_paths
        if metrics:
            entry["metrics"] = metrics.to_dict()
        self._data["videos"][video_id] = entry

    def get_counts(self) -> dict[str, int]:
        """Get counts of videos by status."""
        counts: dict[str, int] = {}
        for entry in self._data["videos"].values():
            status = entry["status"]
            counts[status] = counts.get(status, 0) + 1
        return counts

    def save(self) -> None:
        """Persist the manifest to disk atomically."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self.path) or ".",
            prefix=".tmp_manifest_",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    @property
    def video_ids(self) -> list[str]:
        """All video IDs in the manifest."""
        return list(self._data["videos"].keys())

    def pending_video_ids(self) -> list[str]:
        """Video IDs that are not yet complete."""
        return [
            vid
            for vid, entry in self._data["videos"].items()
            if entry["status"] not in ("complete", "skipped")
        ]
