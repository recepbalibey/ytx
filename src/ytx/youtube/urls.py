"""YouTube URL detection and normalization."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from ytx.exceptions import URLError
from ytx.models import URLType

# Video ID patterns
_VIDEO_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{11}$')

# Only accept official YouTube hosts. This keeps a lookalike URL from being
# passed to yt-dlp, which could otherwise make a network request to another
# site from the local web interface.
_YOUTUBE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
})

# URL patterns
_PATTERNS = {
    URLType.VIDEO: [
        re.compile(r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})'),
    ],
    URLType.PLAYLIST: [
        re.compile(r'youtube\.com/playlist\?.*list=([a-zA-Z0-9_-]+)'),
    ],
    URLType.CHANNEL: [
        re.compile(r'youtube\.com/@([\w.-]+)'),
        re.compile(r'youtube\.com/channel/([a-zA-Z0-9_-]+)'),
        re.compile(r'youtube\.com/c/([\w.-]+)'),
        re.compile(r'youtube\.com/user/([\w.-]+)'),
    ],
}


def detect_url_type(url: str) -> tuple[URLType, str]:
    """Detect whether a URL is a video, playlist, or channel.

    Returns (URLType, extracted_id_or_handle).
    """
    url = url.strip()

    # Bare video ID
    if _VIDEO_ID_RE.match(url):
        return URLType.VIDEO, url

    parsed = urlparse(url if "://" in url else f"https://{url}")
    hostname = (parsed.hostname or "").lower()
    if hostname not in _YOUTUBE_HOSTS:
        raise URLError("URL must be a YouTube video, playlist, or channel")
    query = parse_qs(parsed.query)

    # Playlist with video - check playlist first if list param exists
    if "list" in query:
        # If it also has a video ID, we treat it as playlist (user wants all)
        # unless --no-playlist is used (handled by caller)
        return URLType.PLAYLIST, query["list"][0]

    # Video
    for pattern in _PATTERNS[URLType.VIDEO]:
        m = pattern.search(url)
        if m:
            return URLType.VIDEO, m.group(1)

    # Playlist
    for pattern in _PATTERNS[URLType.PLAYLIST]:
        m = pattern.search(url)
        if m:
            return URLType.PLAYLIST, m.group(1)

    # Channel
    for pattern in _PATTERNS[URLType.CHANNEL]:
        m = pattern.search(url)
        if m:
            return URLType.CHANNEL, m.group(1)

    raise URLError(f"Could not detect URL type: {url}")


def normalize_video_url(video_id: str) -> str:
    """Create a canonical video URL from an ID."""
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_video_id(url: str) -> str | None:
    """Extract a video ID from a URL, or None if not a video URL."""
    try:
        url_type, id_or_handle = detect_url_type(url)
        if url_type == URLType.VIDEO:
            return id_or_handle
    except URLError:
        pass
    return None
