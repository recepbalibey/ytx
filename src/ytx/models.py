"""Core data models using dataclasses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class URLType(Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"


class OutputLayout(Enum):
    """Output directory layout mode."""

    FLAT = "flat"
    STRUCTURED = "structured"


class YouTubeAuthMode(Enum):
    """YouTube authentication mode for yt-dlp."""

    AUTO = "auto"
    FIREFOX = "firefox"


class TranscriptSource(Enum):
    YOUTUBE_MANUAL = "youtube_manual"
    YOUTUBE_AUTO = "youtube_auto"
    YOUTUBE_TRANSLATED = "youtube_translated"
    LOCAL_TRANSCRIPTION = "local_transcription"


class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptSegment:
    """A single timed text segment."""

    start: float
    duration: float
    text: str

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Transcript:
    """Normalized transcript data."""

    language: str
    language_name: str
    source: TranscriptSource
    is_generated: bool
    requested_language: str | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return " ".join(seg.text for seg in self.segments)


@dataclass
class ChannelInfo:
    """Channel metadata."""

    id: str
    name: str
    url: str


@dataclass
class VideoMetadata:
    """Metadata for a single video."""

    id: str
    title: str
    url: str
    channel: ChannelInfo
    published_at: datetime | None = None
    duration_seconds: int | None = None
    description: str = ""
    thumbnail_url: str = ""
    playlist_index: int | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None


@dataclass
class PlaylistMetadata:
    """Playlist-level metadata."""

    id: str
    title: str
    url: str
    channel: ChannelInfo | None = None
    video_count: int = 0


@dataclass
class ChannelMetadata:
    """Channel-level metadata."""

    id: str
    name: str
    url: str
    video_count: int = 0


@dataclass
class ProcessingMetrics:
    """Metrics for a single video's processing."""

    video_duration_seconds: float | None = None
    transcription_elapsed_seconds: float | None = None
    processing_elapsed_seconds: float | None = None
    transcription_model: str | None = None
    transcription_language: str | None = None
    segment_count: int | None = None
    transcription_speed_x: float | None = None  # realtime multiplier

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_duration_seconds": self.video_duration_seconds,
            "transcription_elapsed_seconds": self.transcription_elapsed_seconds,
            "processing_elapsed_seconds": self.processing_elapsed_seconds,
            "transcription_model": self.transcription_model,
            "transcription_language": self.transcription_language,
            "segment_count": self.segment_count,
            "transcription_speed_x": self.transcription_speed_x,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessingMetrics:
        return cls(
            video_duration_seconds=data.get("video_duration_seconds"),
            transcription_elapsed_seconds=data.get("transcription_elapsed_seconds"),
            processing_elapsed_seconds=data.get("processing_elapsed_seconds"),
            transcription_model=data.get("transcription_model"),
            transcription_language=data.get("transcription_language"),
            segment_count=data.get("segment_count"),
            transcription_speed_x=data.get("transcription_speed_x"),
        )


@dataclass
class DurationSummary:
    """Summary of video durations from discovery."""

    known_count: int = 0
    missing_count: int = 0
    total_seconds: float = 0.0
    average_seconds: float = 0.0
    shortest_seconds: float = 0.0
    longest_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_count": self.known_count,
            "missing_count": self.missing_count,
            "total_seconds": self.total_seconds,
            "average_seconds": self.average_seconds,
            "shortest_seconds": self.shortest_seconds,
            "longest_seconds": self.longest_seconds,
        }

    @classmethod
    def from_videos(cls, videos: list[VideoMetadata]) -> DurationSummary:
        """Compute duration summary from a list of video metadata.

        Ignores None, zero, and negative durations.
        """
        valid_durations: list[float] = []
        missing = 0
        for v in videos:
            d = v.duration_seconds
            if d is not None and d > 0:
                valid_durations.append(float(d))
            else:
                missing += 1

        if not valid_durations:
            return cls(known_count=0, missing_count=missing)

        return cls(
            known_count=len(valid_durations),
            missing_count=missing,
            total_seconds=sum(valid_durations),
            average_seconds=sum(valid_durations) / len(valid_durations),
            shortest_seconds=min(valid_durations),
            longest_seconds=max(valid_durations),
        )


@dataclass
class TranscriptResult:
    """Complete result for a single video."""

    video: VideoMetadata
    transcript: Transcript | None = None
    error: str | None = None
    metrics: ProcessingMetrics | None = None


@dataclass
class ProcessingResult:
    """Result of processing a single video in the pipeline."""

    video_id: str
    status: ProcessingStatus
    transcript_source: TranscriptSource | None = None
    output_paths: list[str] = field(default_factory=list)
    error: str | None = None
    metrics: ProcessingMetrics | None = None


@dataclass
class JobSummary:
    """Summary of a batch processing job."""

    total_discovered: int = 0
    captions_extracted: int = 0
    locally_transcribed: int = 0
    skipped_existing: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_discovered": self.total_discovered,
            "captions_extracted": self.captions_extracted,
            "locally_transcribed": self.locally_transcribed,
            "skipped_existing": self.skipped_existing,
            "failed": self.failed,
        }


class ProgressEventType(Enum):
    """Types of progress events emitted by the pipeline."""

    JOB_STARTED = "job_started"
    DISCOVERY_STARTED = "discovery_started"
    DISCOVERY_COMPLETE = "discovery_complete"
    VIDEO_STARTED = "video_started"
    CAPTIONS_FOUND = "captions_found"
    CAPTIONS_MISSING = "captions_missing"
    AUDIO_DOWNLOAD_STARTED = "audio_download_started"
    TRANSCRIPTION_STARTED = "transcription_started"
    TRANSCRIPTION_COMPLETED = "transcription_completed"
    OUTPUT_WRITTEN = "output_written"
    VIDEO_SKIPPED = "video_skipped"
    VIDEO_FAILED = "video_failed"
    VIDEO_COMPLETED = "video_completed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_FATAL_ERROR = "job_fatal_error"
    JOB_WARNING = "job_warning"


@dataclass
class ProgressEvent:
    """A progress event emitted by the pipeline."""

    type: ProgressEventType
    video_id: str | None = None
    video_title: str | None = None
    current: int | None = None
    total: int | None = None
    message: str | None = None
    source: str | None = None
    error: str | None = None
    summary: JobSummary | None = None
    output_paths: list[str] | None = None
    model_size: str | None = None
    language: str | None = None
    metrics: ProcessingMetrics | None = None
    duration_summary: DurationSummary | None = None


# Type alias for the progress callback
ProgressCallback = Callable[[ProgressEvent], None]
