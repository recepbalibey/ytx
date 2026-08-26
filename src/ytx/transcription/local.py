"""Local transcription using faster-whisper."""

from __future__ import annotations

import logging

from ytx.config import DEFAULT_MODEL_SIZE
from ytx.exceptions import TranscriptionDependencyError, TranscriptionError
from ytx.models import Transcript, TranscriptSegment, TranscriptSource
from ytx.transcription.base import LocalTranscriptionProvider

logger = logging.getLogger(__name__)


class FasterWhisperProvider(LocalTranscriptionProvider):
    """Transcription provider using faster-whisper."""

    def __init__(self) -> None:
        self._model = None
        self._loaded_model_size: str | None = None

    def _ensure_model(self, model_size: str | None = None) -> None:
        """Lazy-load the model on first use."""
        size = model_size or DEFAULT_MODEL_SIZE
        if self._model is not None and self._loaded_model_size == size:
            return

        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscriptionDependencyError(
                "Local transcription support is not installed.\n"
                "Install it with: pip install 'ytx[transcription]'"
            ) from e

        logger.info("Loading faster-whisper model '%s'...", size)
        try:
            self._model = WhisperModel(size, device="auto", compute_type="auto")
            self._loaded_model_size = size
        except Exception as e:
            raise TranscriptionError(f"Failed to load model '{size}': {e}") from e

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        model_size: str | None = None,
    ) -> Transcript:
        """Transcribe an audio file using faster-whisper."""
        self._ensure_model(model_size)

        try:
            segments_iter, info = self._model.transcribe(
                audio_path,
                language=language if language != "auto" else None,
                beam_size=5,
                vad_filter=True,
            )
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {e}") from e

        detected_language = info.language or language or "unknown"
        detected_probability = info.language_probability or 0.0

        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    duration=seg.end - seg.start,
                    text=seg.text.strip(),
                )
            )

        logger.info(
            "Transcribed %s: %d segments, language=%s (prob=%.2f)",
            audio_path,
            len(segments),
            detected_language,
            detected_probability,
        )

        return Transcript(
            language=detected_language,
            language_name=detected_language,
            source=TranscriptSource.LOCAL_TRANSCRIPTION,
            is_generated=True,
            segments=segments,
        )

    def is_available(self) -> bool:
        """Check if faster-whisper is importable."""
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False
