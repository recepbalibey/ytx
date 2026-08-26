"""In-memory job manager for the web interface."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ytx.models import DurationSummary, JobSummary, ProcessingMetrics, ProgressEvent

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    DISCOVERING = "discovering"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class VideoStatus(str, Enum):
    WAITING = "waiting"
    CHECKING_CAPTIONS = "checking_captions"
    EXTRACTING_CAPTIONS = "extracting_captions"
    DOWNLOADING_AUDIO = "downloading_audio"
    TRANSCRIBING = "transcribing"
    WRITING = "writing"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class VideoState:
    id: str
    title: str
    status: VideoStatus = VideoStatus.WAITING
    source: str | None = None
    error: str | None = None
    output_paths: list[str] = field(default_factory=list)
    metrics: ProcessingMetrics | None = None


@dataclass
class Job:
    id: str
    source_url: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_videos: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    skipped_videos: int = 0
    current_video_id: str | None = None
    current_video_title: str | None = None
    current_phase: str | None = None
    videos: dict[str, VideoState] = field(default_factory=dict)
    video_order: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    is_fatal_error: bool = False
    fatal_error_message: str | None = None
    output_directory: str | None = None
    summary: JobSummary | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    _event_event: threading.Event = field(default_factory=threading.Event, repr=False)

    # Aggregate metrics for local transcription estimates
    total_local_content_seconds: float = 0.0
    total_local_transcription_seconds: float = 0.0
    local_transcription_count: int = 0

    # Duration summary from discovery
    duration_summary: DurationSummary | None = None

    # Output layout used for this job
    output_layout: str = "flat"

    # Selected video IDs for manual selection (None = all)
    selected_video_ids: list[str] | None = None

    def add_event(self, event_data: dict[str, Any]) -> None:
        """Add an event and notify waiters."""
        self.events.append(event_data)
        self._event_event.set()
        self._event_event.clear()

    def get_events_since(self, index: int) -> list[dict[str, Any]]:
        """Get events since the given index."""
        return self.events[index:]


class JobManager:
    """Manages extraction jobs. Thread-safe, single active job."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._active_job_id: str | None = None
        self._lock = threading.Lock()

    def create_job(self, source_url: str) -> Job:
        """Create a new job. Raises if another job is already active."""
        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs.get(self._active_job_id)
                if active and active.status in (
                    JobStatus.QUEUED,
                    JobStatus.DISCOVERING,
                    JobStatus.PROCESSING,
                    JobStatus.CANCELLING,
                ):
                    raise RuntimeError("A job is already running")

            job_id = uuid.uuid4().hex[:12]
            job = Job(id=job_id, source_url=source_url)
            self._jobs[job_id] = job
            self._active_job_id = job_id
            return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def get_active_job(self) -> Job | None:
        if self._active_job_id:
            return self._jobs.get(self._active_job_id)
        return None

    def clear_active(self, job_id: str) -> None:
        with self._lock:
            if self._active_job_id == job_id:
                self._active_job_id = None

    def handle_progress_event(self, job: Job, event: ProgressEvent) -> None:
        """Translate a pipeline ProgressEvent into job state updates."""
        from ytx.models import ProgressEventType

        event_data: dict[str, Any] = {
            "type": event.type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if event.video_id:
            event_data["video_id"] = event.video_id
        if event.video_title:
            event_data["video_title"] = event.video_title
        if event.current is not None:
            event_data["current"] = event.current
        if event.total is not None:
            event_data["total"] = event.total
        if event.message:
            event_data["message"] = event.message
        if event.source:
            event_data["source"] = event.source
        if event.error:
            event_data["error"] = event.error
        if event.model_size:
            event_data["model_size"] = event.model_size
        if event.language:
            event_data["language"] = event.language
        if event.metrics:
            event_data["metrics"] = event.metrics.to_dict()
        if event.duration_summary:
            event_data["duration_summary"] = event.duration_summary.to_dict()

        # Update job state based on event type
        if event.type == ProgressEventType.JOB_STARTED:
            job.status = JobStatus.PROCESSING

        elif event.type == ProgressEventType.DISCOVERY_STARTED:
            job.status = JobStatus.DISCOVERING
            job.current_phase = "Discovering videos..."

        elif event.type == ProgressEventType.DISCOVERY_COMPLETE:
            job.total_videos = event.total or 0
            job.current_phase = None
            if event.duration_summary:
                job.duration_summary = event.duration_summary

        elif event.type == ProgressEventType.VIDEO_STARTED:
            vid = event.video_id or ""
            job.current_video_id = vid
            job.current_video_title = event.video_title
            if vid and vid not in job.videos:
                vs = VideoState(id=vid, title=event.video_title or "")
                job.videos[vid] = vs
                job.video_order.append(vid)

        elif event.type == ProgressEventType.CAPTIONS_FOUND:
            if event.video_id and event.video_id in job.videos:
                vs = job.videos[event.video_id]
                vs.status = VideoStatus.EXTRACTING_CAPTIONS
                vs.source = event.source

        elif event.type == ProgressEventType.CAPTIONS_MISSING:
            if event.video_id and event.video_id in job.videos:
                job.videos[event.video_id].status = VideoStatus.CHECKING_CAPTIONS

        elif event.type == ProgressEventType.AUDIO_DOWNLOAD_STARTED:
            if event.video_id and event.video_id in job.videos:
                job.videos[event.video_id].status = VideoStatus.DOWNLOADING_AUDIO

        elif event.type == ProgressEventType.TRANSCRIPTION_STARTED:
            if event.video_id and event.video_id in job.videos:
                job.videos[event.video_id].status = VideoStatus.TRANSCRIBING

        elif event.type == ProgressEventType.TRANSCRIPTION_COMPLETED:
            if event.video_id and event.video_id in job.videos:
                event_data["segments_info"] = event.message
                if event.metrics:
                    job.videos[event.video_id].metrics = event.metrics
                    # Update aggregate stats
                    if event.metrics.video_duration_seconds:
                        job.total_local_content_seconds += (
                            event.metrics.video_duration_seconds
                        )
                    if event.metrics.transcription_elapsed_seconds:
                        job.total_local_transcription_seconds += (
                            event.metrics.transcription_elapsed_seconds
                        )
                    job.local_transcription_count += 1

        elif event.type == ProgressEventType.OUTPUT_WRITTEN:
            if event.video_id and event.video_id in job.videos:
                job.videos[event.video_id].status = VideoStatus.WRITING
                if event.output_paths:
                    job.videos[event.video_id].output_paths = event.output_paths

        elif event.type == ProgressEventType.VIDEO_SKIPPED:
            if event.video_id and event.video_id in job.videos:
                job.videos[event.video_id].status = VideoStatus.SKIPPED
            job.skipped_videos += 1

        elif event.type == ProgressEventType.VIDEO_COMPLETED:
            if event.video_id and event.video_id in job.videos:
                vs = job.videos[event.video_id]
                vs.status = VideoStatus.COMPLETE
                vs.source = event.source
                if event.output_paths:
                    vs.output_paths = event.output_paths
                if event.metrics:
                    vs.metrics = event.metrics
            job.completed_videos += 1

        elif event.type == ProgressEventType.VIDEO_FAILED:
            if event.video_id and event.video_id in job.videos:
                vs = job.videos[event.video_id]
                vs.status = VideoStatus.FAILED
                # Use shorter error message for video row
                if event.error:
                    if 'playback' in event.error.lower() or 'Firefox session' in event.error:
                        vs.error = 'Playback session error'
                    else:
                        vs.error = event.error
            job.failed_videos += 1
            if event.error:
                # Deduplicate errors: track count per error message
                error_key = event.error.strip()
                if error_key in job.error_counts:
                    job.error_counts[error_key] += 1
                else:
                    job.errors.append(event.error)
                    job.error_counts[error_key] = 1

        elif event.type == ProgressEventType.JOB_WARNING:
            if event.message:
                job.warnings.append(event.message)

        elif event.type == ProgressEventType.JOB_FATAL_ERROR:
            job.is_fatal_error = True
            job.fatal_error_message = event.error
            if event.error:
                job.errors.append(event.error)

        elif event.type == ProgressEventType.JOB_COMPLETED:
            job.status = JobStatus.COMPLETE
            job.summary = event.summary
            job.current_phase = None

        elif event.type == ProgressEventType.JOB_FAILED:
            job.status = JobStatus.FAILED
            if event.error:
                job.errors.append(event.error)

        job.add_event(event_data)
