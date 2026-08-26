"""Centralized model name mapping for transcription quality presets.

The web UI exposes friendly names (fast/balanced/best) while faster-whisper
requires specific model identifiers (base/small/medium/etc).

This module is the SINGLE source of truth for that mapping.
"""

from __future__ import annotations

# Friendly name -> faster-whisper model identifier
QUALITY_TO_MODEL: dict[str, str] = {
    "fast": "tiny",
    "balanced": "base",
    "best": "small",
}

# Valid faster-whisper model identifiers (accepted by WhisperModel)
VALID_WHISPER_MODELS: frozenset[str] = frozenset({
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v1",
    "large-v2",
    "large-v3",
    "large",
    "distil-small.en",
    "distil-medium.en",
    "distil-large-v2",
    "distil-large-v3",
    "large-v3-turbo",
    "turbo",
})

# Default quality for web UI
DEFAULT_WEB_QUALITY = "balanced"

# Default model for CLI (must be a valid whisper model)
DEFAULT_CLI_MODEL = "base"


def resolve_model_size(raw: str | None) -> str:
    """Resolve a model name/quality preset to a valid faster-whisper model identifier.

    Accepts:
    - Friendly quality names: "fast", "balanced", "best"
    - Direct model names: "base", "small", "medium", etc.
    - None: returns the default CLI model

    Returns a valid faster-whisper model identifier string.
    """
    if raw is None:
        return DEFAULT_CLI_MODEL

    raw_lower = raw.strip().lower()

    # Check friendly name mapping first
    if raw_lower in QUALITY_TO_MODEL:
        return QUALITY_TO_MODEL[raw_lower]

    # Check if it's already a valid whisper model name
    if raw_lower in VALID_WHISPER_MODELS:
        return raw_lower

    # Unknown value. Return default and let faster-whisper validate.
    return raw_lower


def resolve_web_model(raw: str | None) -> str:
    """Resolve model for web UI requests.

    Unlike resolve_model_size, this defaults to the web quality preset
    when no model is specified (i.e., user left default "Balanced" selected).
    """
    if raw is None:
        return QUALITY_TO_MODEL[DEFAULT_WEB_QUALITY]
    return resolve_model_size(raw)
