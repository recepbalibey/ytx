"""Custom exception hierarchy."""


class YTXError(Exception):
    """Base exception for all YTX errors."""


class URLError(YTXError):
    """Invalid or unsupported URL."""


class VideoUnavailableError(YTXError):
    """Video is private, deleted, or region-blocked."""

    def __init__(self, video_id: str, reason: str = "unavailable"):
        self.video_id = video_id
        self.reason = reason
        super().__init__(f"Video {video_id} is {reason}")


class NoCaptionsError(YTXError):
    """No suitable captions found for a video."""

    def __init__(self, video_id: str):
        self.video_id = video_id
        super().__init__(f"No captions available for video {video_id}")


class CaptionAccessBlockedError(YTXError):
    """YouTube blocked caption retrieval (IP blocked, rate limited, etc.)."""

    def __init__(self, video_id: str, reason: str = "blocked"):
        self.video_id = video_id
        self.reason = reason
        super().__init__(
            f"YouTube blocked caption retrieval for video {video_id}: {reason}"
        )


class CaptionRetrievalError(YTXError):
    """Caption retrieval failed due to a network or API error."""

    def __init__(self, video_id: str, reason: str = "retrieval failed"):
        self.video_id = video_id
        self.reason = reason
        super().__init__(
            f"Failed to retrieve captions for video {video_id}: {reason}"
        )


class TranscriptionError(YTXError):
    """Local transcription failed."""


class TranscriptionDependencyError(YTXError):
    """Transcription dependencies not installed."""


class AudioDownloadError(YTXError):
    """Failed to download audio."""


class YouTubeAuthenticationRequiredError(AudioDownloadError):
    """YouTube requires browser authentication to download audio."""

    def __init__(self, video_id: str, message: str = "YouTube sign-in required"):
        self.video_id = video_id
        super().__init__(message)


class YouTubePlaybackClientError(AudioDownloadError):
    """YouTube rejected the playback client (e.g., 'page needs to be reloaded').

    This typically happens with authenticated browser cookies when the
    tv_downgraded client is used. Can often be resolved by retrying with
    an alternate player client.
    """

    def __init__(self, video_id: str, message: str = "YouTube playback session failed"):
        self.video_id = video_id
        super().__init__(message)


class OutputError(YTXError):
    """Failed to write output files."""


class StateError(YTXError):
    """State/manifest operation failed."""
