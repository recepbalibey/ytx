"""Audio download using yt-dlp."""

from __future__ import annotations

import logging
import os
import re
import tempfile

import yt_dlp

from ytx.exceptions import (
    AudioDownloadError,
    YouTubeAuthenticationRequiredError,
    YouTubePlaybackClientError,
)
from ytx.models import YouTubeAuthMode

logger = logging.getLogger(__name__)

# Patterns that indicate YouTube requires authentication
_AUTH_REQUIRED_PATTERNS = [
    re.compile(r"sign in to confirm", re.IGNORECASE),
    re.compile(r"not a bot", re.IGNORECASE),
    re.compile(r"cookies[\s-]*from[\s-]*browser", re.IGNORECASE),
    re.compile(r"login required", re.IGNORECASE),
    re.compile(r"authentication.*required", re.IGNORECASE),
]

# Pattern for "page needs to be reloaded" playback client error
_PLAYBACK_CLIENT_PATTERN = re.compile(
    r"page needs to be reloaded", re.IGNORECASE
)

# Allowed player-client values for fallback (hardcoded allowlist)
_ALLOWED_PLAYER_CLIENTS = frozenset({"default", "web_embedded"})


def _is_auth_required(error_msg: str) -> bool:
    """Check if an error message indicates authentication is required."""
    return any(pattern.search(error_msg) for pattern in _AUTH_REQUIRED_PATTERNS)


def _is_playback_client_error(error_msg: str) -> bool:
    """Check if error indicates a playback client issue (e.g., page needs reload)."""
    return bool(_PLAYBACK_CLIENT_PATTERN.search(error_msg))


def _build_ytdlp_opts(
    outtmpl: str,
    auth_mode: YouTubeAuthMode = YouTubeAuthMode.AUTO,
    use_firefox_auth: bool = False,
    player_client: str | None = None,
) -> dict:
    """Build yt-dlp options dict.

    Args:
        outtmpl: Output template for downloaded files.
        auth_mode: Authentication mode setting.
        use_firefox_auth: If True, use Firefox cookies regardless of auth_mode.
        player_client: Optional player_client extractor arg (e.g., "default,web_embedded").
    """
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
    }

    # Add Firefox cookies if requested
    if use_firefox_auth or auth_mode == YouTubeAuthMode.FIREFOX:
        opts["cookiesfrombrowser"] = ("firefox",)

    # Add player_client extractor arg if specified
    if player_client:
        _validate_player_client(player_client)
        opts["extractor_args"] = {"youtube": {"player_client": [player_client]}}

    return opts


def _validate_player_client(player_client: str) -> None:
    """Validate player_client values against the allowlist.

    Raises ValueError if any value is not in the allowlist.
    """
    if not player_client or not player_client.strip():
        return
    clients = [c.strip() for c in player_client.split(",")]
    for client in clients:
        if client and client not in _ALLOWED_PLAYER_CLIENTS:
            raise ValueError(
                f"Unsupported player_client value: {client!r}. "
                f"Allowed: {', '.join(sorted(_ALLOWED_PLAYER_CLIENTS))}"
            )


def download_audio(
    video_id: str,
    output_dir: str | None = None,
    keep: bool = False,
    auth_mode: YouTubeAuthMode = YouTubeAuthMode.AUTO,
    use_firefox_auth: bool = False,
    player_client: str | None = None,
) -> str:
    """Download audio for a video and return the file path.

    Args:
        video_id: YouTube video ID.
        output_dir: Directory to save audio. If None, uses a temp directory.
        keep: If True, save in output_dir permanently. If False, use temp dir.
        auth_mode: YouTube authentication mode.
        use_firefox_auth: Force Firefox auth (for retry after auth error).
        player_client: Optional player_client for yt-dlp extractor.

    Returns:
        Path to the downloaded audio file.

    Raises:
        AudioDownloadError: If download fails.
        YouTubeAuthenticationRequiredError: If YouTube requires authentication.
        YouTubePlaybackClientError: If YouTube rejects the playback client.
    """
    if keep and output_dir:
        os.makedirs(output_dir, exist_ok=True)
        outtmpl = os.path.join(output_dir, f"{video_id}.%(ext)s")
    else:
        temp_dir = tempfile.mkdtemp(prefix="ytx_audio_")
        outtmpl = os.path.join(temp_dir, f"{video_id}.%(ext)s")

    opts = _build_ytdlp_opts(outtmpl, auth_mode, use_firefox_auth, player_client)
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        error_msg = str(e)
        # Sanitize: remove any cookie/header values from error message
        sanitized = _sanitize_error(error_msg)
        if _is_auth_required(error_msg):
            raise YouTubeAuthenticationRequiredError(video_id) from e
        if _is_playback_client_error(error_msg):
            raise YouTubePlaybackClientError(video_id) from e
        raise AudioDownloadError(f"Failed to download audio for {video_id}: {sanitized}") from e

    # Find the output file
    expected_path = os.path.join(
        os.path.dirname(outtmpl),
        f"{video_id}.mp3",
    )
    if os.path.exists(expected_path):
        return expected_path

    # Fallback: look for any file with the video ID prefix
    directory = os.path.dirname(outtmpl)
    for fname in os.listdir(directory):
        if fname.startswith(video_id):
            return os.path.join(directory, fname)

    raise AudioDownloadError(f"Audio file not found after download for {video_id}")


def _sanitize_error(msg: str) -> str:
    """Remove potentially sensitive information from error messages.

    Strips cookie headers, authorization tokens, and other sensitive data
    that yt-dlp might include in error messages.
    """
    # Remove Cookie headers
    msg = re.sub(r"Cookie:\s*[^\s]+", "Cookie: [REDACTED]", msg, flags=re.IGNORECASE)
    # Remove Set-Cookie headers
    msg = re.sub(r"Set-Cookie:\s*[^\s]+", "Set-Cookie: [REDACTED]", msg, flags=re.IGNORECASE)
    # Remove Authorization headers
    msg = re.sub(
        r"Authorization:\s*[^\n]+",
        "Authorization: [REDACTED]",
        msg,
        flags=re.IGNORECASE,
    )
    # Remove SAPISID and similar auth tokens
    msg = re.sub(r"SAPISID=\S+", "SAPISID=[REDACTED]", msg)
    msg = re.sub(r"HSID=\S+", "HSID=[REDACTED]", msg)
    msg = re.sub(r"SSID=\S+", "SSID=[REDACTED]", msg)
    msg = re.sub(r"SID=\S+", "SID=[REDACTED]", msg)
    return msg


def cleanup_audio(audio_path: str) -> None:
    """Remove a temporary audio file and its parent directory if empty."""
    try:
        if os.path.exists(audio_path):
            os.remove(audio_path)
            parent = os.path.dirname(audio_path)
            # Remove temp dir if empty
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
    except OSError as e:
        logger.warning("Failed to clean up audio file %s: %s", audio_path, e)
