"""Language selection and fallback logic."""

from __future__ import annotations

from ytx.models import Transcript


def select_best_transcript(
    available_languages: list[str],
    requested_language: str | None = None,
) -> str | None:
    """Select the best language code from available options.

    Priority:
    1. Requested language (manual preferred over auto)
    2. English
    3. First available
    """
    if not available_languages:
        return None

    if requested_language:
        # Exact match
        if requested_language in available_languages:
            return requested_language
        # Prefix match (e.g., "en" matches "en-US")
        for lang in available_languages:
            if lang.startswith(requested_language):
                return lang

    # English fallback
    if "en" in available_languages:
        return "en"

    # Any available
    return available_languages[0]


def describe_transcript_source(transcript: Transcript) -> str:
    """Return a human-readable description of the transcript source."""
    source_descriptions = {
        "youtube_manual": "YouTube manual captions",
        "youtube_auto": "YouTube auto-generated captions",
        "youtube_translated": "YouTube translated captions",
        "local_transcription": "Local transcription",
    }
    return source_descriptions.get(transcript.source.value, "Unknown source")
