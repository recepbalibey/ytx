"""Base output writer protocol."""

from __future__ import annotations

from typing import Protocol

from ytx.models import TranscriptResult


class OutputWriter(Protocol):
    """Protocol for output writers."""

    @property
    def file_extension(self) -> str: ...

    def write(
        self,
        result: TranscriptResult,
        output_path: str,
        include_timestamps: bool = True,
    ) -> str:
        """Write the transcript to a file. Returns the path written."""
        ...
