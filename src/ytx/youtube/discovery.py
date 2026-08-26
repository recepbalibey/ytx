"""YouTube video discovery and metadata extraction using yt-dlp."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import yt_dlp

from ytx.exceptions import URLError, VideoUnavailableError
from ytx.models import ChannelInfo, VideoMetadata

logger = logging.getLogger(__name__)


def _passes_date_filter(
    meta: VideoMetadata,
    after: datetime | None,
    before: datetime | None,
) -> bool:
    """Check if a video passes date filters.

    If any date filter is active and the video has no publication date,
    the video is skipped (returns False).
    """
    has_filter = after is not None or before is not None
    if has_filter and meta.published_at is None:
        logger.debug(
            "Skipping %s: publication date unavailable, cannot apply date filter.",
            meta.id,
        )
        return False
    if after and meta.published_at and meta.published_at < after:
        return False
    return not (before and meta.published_at and meta.published_at > before)


# Common yt-dlp options for metadata extraction (no download)
_BASE_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
    "ignoreerrors": True,
    "no_color": True,
}


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse yt-dlp date string (YYYYMMDD or ISO format)."""
    if not date_str:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _entry_to_metadata(
    entry: dict[str, Any], channel: ChannelInfo | None = None
) -> VideoMetadata | None:
    """Convert a yt-dlp entry dict to VideoMetadata."""
    video_id = entry.get("id")
    if not video_id:
        return None

    title = entry.get("title") or "Untitled"
    url = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"

    # Channel info
    if channel is None:
        channel = ChannelInfo(
            id=entry.get("channel_id") or entry.get("uploader_id") or "",
            name=entry.get("channel") or entry.get("uploader") or "Unknown",
            url=entry.get("channel_url") or entry.get("uploader_url") or "",
        )

    return VideoMetadata(
        id=video_id,
        title=title,
        url=url,
        channel=channel,
        published_at=_parse_date(entry.get("upload_date")),
        duration_seconds=entry.get("duration"),
        description=entry.get("description") or "",
        thumbnail_url=entry.get("thumbnail") or "",
        playlist_index=entry.get("playlist_index"),
        playlist_id=entry.get("playlist_id"),
        playlist_title=entry.get("playlist_title"),
    )


def get_video_metadata(video_id: str) -> VideoMetadata:
    """Fetch metadata for a single video."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {**_BASE_OPTS, "extract_flat": False}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if "private" in error_msg:
            raise VideoUnavailableError(video_id, "private") from e
        if "unavailable" in error_msg or "not available" in error_msg:
            raise VideoUnavailableError(video_id, "unavailable") from e
        raise VideoUnavailableError(video_id, str(e)) from e

    if info is None:
        raise VideoUnavailableError(video_id, "no data returned")

    meta = _entry_to_metadata(info)
    if meta is None:
        raise VideoUnavailableError(video_id, "could not parse metadata")
    return meta


def discover_playlist_videos(
    playlist_url: str,
    after: datetime | None = None,
    before: datetime | None = None,
    latest: int | None = None,
) -> list[VideoMetadata]:
    """Discover videos in a playlist. Returns in playlist order."""
    opts = {**_BASE_OPTS}
    if latest:
        opts["playlistend"] = latest

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise URLError(f"Failed to extract playlist: {e}") from e

    if info is None:
        raise URLError("Playlist returned no data")

    entries = info.get("entries") or []
    videos: list[VideoMetadata] = []

    channel = None
    if info.get("channel_id"):
        channel = ChannelInfo(
            id=info.get("channel_id", ""),
            name=info.get("channel", "Unknown"),
            url=info.get("channel_url", ""),
        )

    for entry in entries:
        if entry is None:
            continue
        meta = _entry_to_metadata(entry, channel)
        if meta is None:
            continue
        if not _passes_date_filter(meta, after, before):
            continue
        videos.append(meta)

    return videos


def discover_channel_videos(
    channel_url: str,
    after: datetime | None = None,
    before: datetime | None = None,
    latest: int | None = None,
) -> list[VideoMetadata]:
    """Discover uploaded videos from a channel.

    Returns newest-first by default.
    """
    # Normalize to /videos tab
    videos_url = channel_url.rstrip("/")
    if not videos_url.endswith("/videos"):
        videos_url += "/videos"

    opts = {**_BASE_OPTS}
    if latest:
        opts["playlistend"] = latest

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(videos_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise URLError(f"Failed to extract channel: {e}") from e

    if info is None:
        raise URLError("Channel returned no data")

    entries = info.get("entries") or []
    videos: list[VideoMetadata] = []

    channel = ChannelInfo(
        id=info.get("channel_id") or info.get("uploader_id") or "",
        name=info.get("channel") or info.get("uploader") or "Unknown",
        url=info.get("channel_url") or info.get("uploader_url") or channel_url,
    )

    for entry in entries:
        if entry is None:
            continue
        meta = _entry_to_metadata(entry, channel)
        if meta is None:
            continue
        if not _passes_date_filter(meta, after, before):
            continue
        videos.append(meta)

    return videos
