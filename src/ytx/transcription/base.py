"""Abstract base for local transcription providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ytx.models import Transcript


class LocalTranscriptionProvider(ABC):
    """Interface for local speech-to-text providers."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        model_size: str | None = None,
    ) -> Transcript:
        """Transcribe an audio file and return a normalized Transcript.

        Args:
            audio_path: Path to the audio file.
            language: ISO language code, or None for auto-detection.
            model_size: Model size hint (e.g., "tiny", "base", "small", "medium", "large-v3").
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the transcription backend is available."""
        ...
