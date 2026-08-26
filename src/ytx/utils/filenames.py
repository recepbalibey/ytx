"""Filename sanitization utilities."""

from __future__ import annotations

import re
import unicodedata

# Characters not allowed in filenames on Windows/macOS/Linux
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_DASH = re.compile(r"-+")
_MULTI_UNDERSCORE = re.compile(r"_+")

# Reserved Windows filenames
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}

MAX_FILENAME_LENGTH = 200


def sanitize_filename(name: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Convert a string into a safe filename.

    Handles Unicode, reserved characters, long names, and platform differences.
    """
    # Normalize Unicode
    name = unicodedata.normalize("NFC", name)

    # Replace unsafe characters with dash
    name = _UNSAFE_CHARS.sub("-", name)

    # Strip leading/trailing whitespace and dots
    name = name.strip(" .")

    # Collapse multiple dashes/underscores
    name = _MULTI_DASH.sub("-", name)
    name = _MULTI_UNDERSCORE.sub("_", name)

    # Truncate
    if len(name) > max_length:
        name = name[:max_length].rstrip("-_. ")

    # Fallback
    if not name:
        name = "untitled"

    # Check Windows reserved names
    stem = name.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        name = f"_{name}"

    return name


def safe_video_dirname(video_id: str, title: str) -> str:
    """Create a safe directory name for a video: sanitized-title_video-id."""
    safe_title = sanitize_filename(title, max_length=150)
    return f"{safe_title}_{video_id}"
