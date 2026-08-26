"""Transcript normalization utilities."""

from __future__ import annotations

import re

from ytx.models import Transcript, TranscriptSegment

_WHITESPACE_RE = re.compile(r'\s+')


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces."""
    return _WHITESPACE_RE.sub(' ', text).strip()


def normalize_transcript(transcript: Transcript) -> Transcript:
    """Apply conservative normalization to a transcript.

    - Normalizes whitespace in each segment
    - Removes empty segments
    - Preserves original timing and meaning
    """
    normalized_segments: list[TranscriptSegment] = []
    for seg in transcript.segments:
        text = normalize_whitespace(seg.text)
        if text:
            normalized_segments.append(
                TranscriptSegment(start=seg.start, duration=seg.duration, text=text)
            )

    return Transcript(
        language=transcript.language,
        language_name=transcript.language_name,
        source=transcript.source,
        is_generated=transcript.is_generated,
        segments=normalized_segments,
    )
