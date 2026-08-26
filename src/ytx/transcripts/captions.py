"""Caption extraction using youtube-transcript-api."""

from __future__ import annotations

import logging
import time

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._api import FetchedTranscript
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    YouTubeRequestFailed,
)

from ytx.exceptions import (
    CaptionAccessBlockedError,
    CaptionRetrievalError,
    NoCaptionsError,
)
from ytx.models import Transcript, TranscriptSegment, TranscriptSource

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRYABLE_EXCEPTIONS = (RequestBlocked, IpBlocked, YouTubeRequestFailed)


def _source_from_transcript(transcript: FetchedTranscript) -> TranscriptSource:
    """Determine the TranscriptSource from a FetchedTranscript."""
    if transcript.is_generated:
        return TranscriptSource.YOUTUBE_AUTO
    return TranscriptSource.YOUTUBE_MANUAL


def _fetched_to_transcript(
    transcript: FetchedTranscript, requested_language: str | None = None
) -> Transcript:
    """Convert a FetchedTranscript to our normalized Transcript model."""
    segments = [
        TranscriptSegment(
            start=snippet.start,
            duration=snippet.duration,
            text=snippet.text,
        )
        for snippet in transcript
    ]
    return Transcript(
        language=transcript.language_code,
        language_name=transcript.language,
        source=_source_from_transcript(transcript),
        is_generated=transcript.is_generated,
        requested_language=requested_language,
        segments=segments,
    )


def _retry_with_backoff(func, video_id: str):
    """Execute a function with exponential backoff on retryable errors.

    Raises CaptionAccessBlockedError if all retries are exhausted due to
    blocking/rate-limiting. Non-retryable exceptions propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return func()
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt == _MAX_RETRIES - 1:
                logger.debug(
                    "Blocked for %s after %d attempts: %s",
                    video_id, _MAX_RETRIES, e,
                )
                raise CaptionAccessBlockedError(
                    video_id, reason=str(e)
                ) from e
            wait = 2 ** (attempt + 1)
            logger.debug(
                "Blocked for %s, retrying in %ds (attempt %d/%d)",
                video_id, wait, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(wait)
    # Should not reach here, but just in case
    raise CaptionAccessBlockedError(video_id) from last_exc


def fetch_captions(
    video_id: str,
    languages: list[str] | None = None,
) -> Transcript:
    """Fetch captions for a video.

    Tries requested languages first, then falls back to any available transcript.

    Raises:
        NoCaptionsError: Video genuinely has no captions available.
        CaptionAccessBlockedError: YouTube blocked the request (IP/rate limit).
        CaptionRetrievalError: Other caption retrieval/network failures.
    """
    ytt = YouTubeTranscriptApi()

    # Step 1: List available transcripts
    try:
        transcript_list = _retry_with_backoff(
            lambda: ytt.list(video_id), video_id
        )
    except CaptionAccessBlockedError:
        raise
    except (NoTranscriptFound, TranscriptsDisabled) as e:
        # Genuine no-captions cases
        raise NoCaptionsError(video_id) from e
    except CouldNotRetrieveTranscript as e:
        # Other youtube-transcript-api errors (VideoUnavailable, etc.)
        raise CaptionRetrievalError(video_id, reason=str(e)) from e
    except Exception as e:
        raise CaptionRetrievalError(video_id, reason=str(e)) from e

    # Step 2: Try to find and fetch a transcript in the requested languages
    if languages:
        requested = languages[0]
        try:
            transcript = transcript_list.find_transcript(languages)
        except NoTranscriptFound:
            # Requested language not available. Fall through to fallback.
            pass
        except Exception as e:
            raise CaptionRetrievalError(video_id, reason=str(e)) from e
        else:
            # Found a transcript for the requested language. Fetch it.
            try:
                fetched = _retry_with_backoff(transcript.fetch, video_id)
                result = _fetched_to_transcript(fetched, requested_language=requested)
            except CaptionAccessBlockedError:
                raise
            except Exception as e:
                raise CaptionRetrievalError(video_id, reason=str(e)) from e

            # If auto-generated, try to prefer manual in same language
            if result.is_generated:
                try:
                    manual = transcript_list.find_manually_created_transcript(languages)
                    fetched_manual = _retry_with_backoff(manual.fetch, video_id)
                    return _fetched_to_transcript(fetched_manual, requested_language=requested)
                except (NoTranscriptFound, CaptionAccessBlockedError):
                    # No manual version or it was blocked. Keep the generated result.
                    pass
                except Exception:
                    # Failed to fetch manual captions. Keep the generated result.
                    pass
            return result

    # Step 3: Fallback. Try English, then any available language.
    for fallback_langs in [["en"], []]:
        try:
            if fallback_langs:
                transcript = transcript_list.find_transcript(fallback_langs)
            else:
                transcript = next(iter(transcript_list))
        except (StopIteration, NoTranscriptFound):
            continue
        except Exception as e:
            raise CaptionRetrievalError(video_id, reason=str(e)) from e

        try:
            fetched = _retry_with_backoff(transcript.fetch, video_id)
            return _fetched_to_transcript(
                fetched, requested_language=languages[0] if languages else None
            )
        except CaptionAccessBlockedError:
            raise
        except Exception as e:
            raise CaptionRetrievalError(video_id, reason=str(e)) from e

    raise NoCaptionsError(video_id)


def list_available_captions(video_id: str) -> list[dict[str, str | bool]]:
    """List all available caption tracks for a video.

    Returns a list of dicts with language, language_code, is_generated, is_translatable.
    """
    ytt = YouTubeTranscriptApi()
    try:
        transcript_list = ytt.list(video_id)
    except Exception:
        return []

    tracks = []
    for t in transcript_list:
        tracks.append({
            "language": t.language,
            "language_code": t.language_code,
            "is_generated": t.is_generated,
            "is_translatable": t.is_translatable,
        })
    return tracks
