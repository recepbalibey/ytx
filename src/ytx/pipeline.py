"""Main processing pipeline."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from ytx.audio.downloader import cleanup_audio, download_audio
from ytx.exceptions import (
    AudioDownloadError,
    CaptionAccessBlockedError,
    CaptionRetrievalError,
    NoCaptionsError,
    TranscriptionDependencyError,
    TranscriptionError,
    VideoUnavailableError,
    YouTubeAuthenticationRequiredError,
    YouTubePlaybackClientError,
)
from ytx.models import (
    DurationSummary,
    JobSummary,
    OutputLayout,
    ProcessingMetrics,
    ProcessingResult,
    ProcessingStatus,
    ProgressCallback,
    ProgressEvent,
    ProgressEventType,
    Transcript,
    TranscriptResult,
    TranscriptSegment,
    TranscriptSource,
    URLType,
    VideoMetadata,
    YouTubeAuthMode,
)
from ytx.output.combined import write_combined_jsonl, write_combined_markdown
from ytx.output.json_writer import write_json
from ytx.output.markdown import write_markdown
from ytx.output.srt import write_srt
from ytx.output.txt import write_txt
from ytx.state.manifest import Manifest
from ytx.transcription.local import FasterWhisperProvider
from ytx.transcription.model_mapping import resolve_model_size
from ytx.transcripts.captions import fetch_captions
from ytx.transcripts.normalize import normalize_transcript
from ytx.utils.filenames import safe_video_dirname
from ytx.youtube.discovery import (
    discover_channel_videos,
    discover_playlist_videos,
    get_video_metadata,
)

logger = logging.getLogger(__name__)
console = Console()


def load_saved_transcript(json_path: str) -> Transcript | None:
    """Load a previously saved transcript from a JSON file.

    Returns a Transcript if the file is valid, None otherwise.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to load transcript from %s: %s", json_path, e)
        return None

    transcript_data = data.get("transcript")
    if transcript_data is None:
        return None

    segments = [
        TranscriptSegment(
            start=seg.get("start", 0.0),
            duration=seg.get("duration", 0.0),
            text=seg.get("text", ""),
        )
        for seg in transcript_data.get("segments", [])
    ]

    source_str = transcript_data.get("source", "youtube_auto")
    try:
        source = TranscriptSource(source_str)
    except ValueError:
        source = TranscriptSource.YOUTUBE_AUTO

    return Transcript(
        language=transcript_data.get("language", "unknown"),
        language_name=transcript_data.get("language_name", "Unknown"),
        source=source,
        is_generated=transcript_data.get("generated", True),
        requested_language=transcript_data.get("requested_language"),
        segments=segments,
    )


class Pipeline:
    """Orchestrates video discovery, transcript extraction, and output writing."""

    def __init__(
        self,
        output_dir: str,
        formats: list[str],
        language: str | None = None,
        transcribe_missing: bool = False,
        keep_audio: bool = False,
        include_timestamps: bool = True,
        skip_existing: bool = False,
        model_size: str | None = None,
        combine: bool = False,
        combine_jsonl: bool = False,
        after: datetime | None = None,
        before: datetime | None = None,
        latest: int | None = None,
        delay: float = 0.5,
        verbose: bool = False,
        on_progress: ProgressCallback | None = None,
        output_layout: OutputLayout = OutputLayout.FLAT,
        selected_video_ids: list[str] | None = None,
        youtube_auth: YouTubeAuthMode = YouTubeAuthMode.AUTO,
    ) -> None:
        self.output_dir = output_dir
        self.formats = formats
        self.language = language
        self.transcribe_missing = transcribe_missing
        self.keep_audio = keep_audio
        self.include_timestamps = include_timestamps
        self.skip_existing = skip_existing
        self.model_size = model_size
        self.combine = combine
        self.combine_jsonl = combine_jsonl
        self.after = after
        self.before = before
        self.latest = latest
        self.delay = delay
        self.verbose = verbose
        self.on_progress = on_progress
        self.output_layout = output_layout
        self.selected_video_ids = selected_video_ids
        self.youtube_auth = youtube_auth

        self._transcriber: FasterWhisperProvider | None = None
        self._summary = JobSummary()
        self._cancelled = False
        self._caption_blocked_warned = False
        self._auth_required = False  # Set True when auth-required detected
        self._firefox_retry_attempted = False  # Track if Firefox retry was tried
        self._playback_client_error = False  # Set True when playback client error detected
        self._used_filenames: dict[str, str] = {}  # basename -> video_id

    def cancel(self) -> None:
        """Request cancellation of the pipeline."""
        if not self._cancelled:
            self._cancelled = True
            console.print(
                "\n[yellow]Cancellation requested. "
                "Finishing current safe operation...[/yellow]"
            )

    def _emit(self, event: ProgressEvent) -> None:
        """Emit a progress event to the callback if set."""
        if self.on_progress:
            try:
                self.on_progress(event)
            except Exception:
                logger.debug("Progress callback error", exc_info=True)

    def _print_duration_stats(self, dur: DurationSummary) -> None:
        """Print duration summary to CLI console."""
        if dur.known_count == 0:
            return
        from ytx.utils.text import format_duration_human

        parts = [f"Total content: {format_duration_human(dur.total_seconds)}"]
        if dur.known_count > 1:
            parts.append(f"Avg: {format_duration_human(dur.average_seconds)}")
            parts.append(
                f"Range: {format_duration_human(dur.shortest_seconds)}"
                f" – {format_duration_human(dur.longest_seconds)}"
            )
        if dur.missing_count > 0:
            parts.append(f"({dur.missing_count} videos with unknown duration)")
        console.print("  ".join(parts))

    def _resolve_flat_filename(self, video: VideoMetadata, base_dir: str) -> str:
        """Resolve a unique flat filename for a video in the given directory.

        Uses sanitized title. On collision, appends _videoId.
        Tracks used filenames within this run to avoid filesystem checks.
        """
        from ytx.utils.filenames import sanitize_filename

        safe_title = sanitize_filename(video.title, max_length=200)
        basename = safe_title

        # Check if this exact basename was already used (by a different video)
        if basename in self._used_filenames and self._used_filenames[basename] != video.id:
            basename = f"{safe_title}_{video.id}"

        self._used_filenames[basename] = video.id
        return basename

    def _filter_selected_videos(self, videos: list[VideoMetadata]) -> list[VideoMetadata]:
        """Filter videos to only those in selected_video_ids, preserving order."""
        if self.selected_video_ids is None:
            return videos
        selected_set = set(self.selected_video_ids)
        return [v for v in videos if v.id in selected_set]

    def _get_transcriber(self) -> FasterWhisperProvider:
        """Lazy-load the transcription provider."""
        if self._transcriber is None:
            self._transcriber = FasterWhisperProvider()
            if not self._transcriber.is_available():
                raise TranscriptionDependencyError(
                    "Local transcription support is not installed.\n"
                    "Install it with: pip install 'ytx[transcription]'"
                )
        return self._transcriber

    def _validate_transcription_config(self) -> str | None:
        """Validate transcription configuration before batch processing.

        Returns an error message if configuration is invalid, None if valid.
        This is called once before processing a playlist/channel to fail fast
        on configuration errors rather than repeating them for every video.
        """
        if not self.transcribe_missing:
            return None

        try:
            transcriber = self._get_transcriber()
            # Resolve the model name to catch invalid presets
            resolved_model = resolve_model_size(self.model_size)
            # Try to initialize the model to catch configuration errors
            transcriber._ensure_model(resolved_model)
            return None
        except TranscriptionDependencyError as e:
            return str(e)
        except Exception as e:
            return f"Local transcription could not start: {e}"

    def run(self, url: str) -> JobSummary:
        """Run the pipeline for a URL (video, playlist, or channel)."""
        from ytx.youtube.urls import detect_url_type

        self._emit(ProgressEvent(type=ProgressEventType.JOB_STARTED))

        try:
            url_type, id_or_handle = detect_url_type(url)

            if url_type == URLType.VIDEO:
                return self._run_single_video(id_or_handle)
            elif url_type == URLType.PLAYLIST:
                return self._run_playlist(url, id_or_handle)
            elif url_type == URLType.CHANNEL:
                return self._run_channel(url, id_or_handle)
            else:
                console.print(f"[red]Unsupported URL type: {url_type}[/red]")
                self._emit(ProgressEvent(
                    type=ProgressEventType.JOB_FAILED,
                    message=f"Unsupported URL type: {url_type}",
                ))
                return self._summary
        except Exception as e:
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_FAILED,
                error=str(e),
            ))
            raise

    def _run_single_video(self, video_id: str) -> JobSummary:
        """Process a single video."""
        self._summary.total_discovered = 1
        console.print(f"Processing video: {video_id}")

        self._emit(ProgressEvent(
            type=ProgressEventType.DISCOVERY_COMPLETE,
            total=1,
        ))

        try:
            metadata = get_video_metadata(video_id)
        except VideoUnavailableError as e:
            console.print(f"[red]Video unavailable: {e}[/red]")
            self._summary.failed = 1
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_FAILED,
                error=str(e),
                summary=self._summary,
            ))
            return self._summary

        self._emit(ProgressEvent(
            type=ProgressEventType.VIDEO_STARTED,
            video_id=metadata.id,
            video_title=metadata.title,
            current=1,
            total=1,
        ))

        result = self._process_video(metadata)
        self._update_summary(result)
        self._print_result(result)

        if result.status == ProcessingStatus.COMPLETE:
            source_label = ""
            if result.transcript_source:
                source_label = result.transcript_source.value
            self._emit(ProgressEvent(
                type=ProgressEventType.VIDEO_COMPLETED,
                video_id=metadata.id,
                video_title=metadata.title,
                current=1,
                total=1,
                source=source_label,
                output_paths=result.output_paths,
            ))
        elif result.status == ProcessingStatus.FAILED:
            self._emit(ProgressEvent(
                type=ProgressEventType.VIDEO_FAILED,
                video_id=metadata.id,
                video_title=metadata.title,
                current=1,
                total=1,
                error=result.error,
            ))

        self._emit(ProgressEvent(
            type=ProgressEventType.JOB_COMPLETED,
            summary=self._summary,
        ))
        return self._summary

    def _run_playlist(self, url: str, playlist_id: str) -> JobSummary:
        """Process all videos in a playlist."""
        self._emit(ProgressEvent(type=ProgressEventType.DISCOVERY_STARTED))
        console.print("Discovering playlist videos...")
        # When manual selection is active, discover ALL videos (ignore latest)
        # The user will select after seeing the full list
        discover_latest = None if self.selected_video_ids else self.latest
        videos = discover_playlist_videos(
            url, after=self.after, before=self.before, latest=discover_latest
        )
        self._summary.total_discovered = len(videos)
        console.print(f"Found {len(videos)} videos in playlist")

        # Filter to selected videos if manual selection is active
        if self.selected_video_ids:
            videos = self._filter_selected_videos(videos)
            console.print(f"Selected {len(videos)} videos for processing")

        # Compute duration summary
        dur = DurationSummary.from_videos(videos)
        self._emit(ProgressEvent(
            type=ProgressEventType.DISCOVERY_COMPLETE,
            total=len(videos),
            duration_summary=dur,
        ))

        # Print duration stats to CLI
        self._print_duration_stats(dur)

        # Warn about long processing time for large playlists with local transcription
        if len(videos) > 20 and self.transcribe_missing:
            from ytx.utils.text import format_duration_human

            msg = f"{len(videos)} videos found."
            if dur.total_seconds > 0:
                msg += f" Total content: {format_duration_human(dur.total_seconds)}."
                msg += f" Average video: {format_duration_human(dur.average_seconds)}."
            msg += " Local transcription may take significant time for large batches."
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_WARNING,
                message=msg,
            ))

        if not videos:
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_COMPLETED,
                summary=self._summary,
            ))
            return self._summary

        # Fail-fast: validate transcription config before processing
        config_error = self._validate_transcription_config()
        if config_error:
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_FATAL_ERROR,
                error=config_error,
            ))
            self._summary.failed = len(videos)
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_COMPLETED,
                summary=self._summary,
            ))
            return self._summary

        # Create playlist output directory
        playlist_name = videos[0].playlist_title or playlist_id
        from ytx.utils.filenames import sanitize_filename

        playlist_dir = os.path.join(self.output_dir, sanitize_filename(playlist_name))
        os.makedirs(playlist_dir, exist_ok=True)

        # Initialize manifest. Use a hidden file in flat mode to avoid clutter.
        if self.output_layout == OutputLayout.FLAT:
            manifest_path = os.path.join(playlist_dir, ".ytx-manifest.json")
        else:
            manifest_path = os.path.join(playlist_dir, "manifest.json")
        manifest = Manifest(manifest_path)
        manifest.set_source("playlist", url, playlist_id)

        results = self._process_videos(videos, manifest, playlist_dir)

        # Always write combined output (even on cancellation, completed transcripts exist)
        self._write_combined_safe(results, playlist_dir)

        self._emit(ProgressEvent(
            type=ProgressEventType.JOB_COMPLETED,
            summary=self._summary,
        ))
        return self._summary

    def _run_channel(self, url: str, handle: str) -> JobSummary:
        """Process all videos from a channel."""
        self._emit(ProgressEvent(type=ProgressEventType.DISCOVERY_STARTED))
        console.print("Discovering channel videos...")
        # When manual selection is active, discover ALL videos (ignore latest)
        discover_latest = None if self.selected_video_ids else self.latest
        videos = discover_channel_videos(
            url, after=self.after, before=self.before, latest=discover_latest
        )
        self._summary.total_discovered = len(videos)
        console.print(f"Found {len(videos)} videos from channel")

        # Filter to selected videos if manual selection is active
        if self.selected_video_ids:
            videos = self._filter_selected_videos(videos)
            console.print(f"Selected {len(videos)} videos for processing")

        # Compute duration summary
        dur = DurationSummary.from_videos(videos)
        self._emit(ProgressEvent(
            type=ProgressEventType.DISCOVERY_COMPLETE,
            total=len(videos),
            duration_summary=dur,
        ))

        # Print duration stats to CLI
        self._print_duration_stats(dur)

        # Warn about long processing time for large channels with local transcription
        if len(videos) > 20 and self.transcribe_missing:
            from ytx.utils.text import format_duration_human

            msg = f"{len(videos)} videos found."
            if dur.total_seconds > 0:
                msg += f" Total content: {format_duration_human(dur.total_seconds)}."
                msg += f" Average video: {format_duration_human(dur.average_seconds)}."
            msg += " Local transcription may take significant time for large batches."
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_WARNING,
                message=msg,
            ))

        if not videos:
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_COMPLETED,
                summary=self._summary,
            ))
            return self._summary

        # Fail-fast: validate transcription config before processing
        config_error = self._validate_transcription_config()
        if config_error:
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_FATAL_ERROR,
                error=config_error,
            ))
            self._summary.failed = len(videos)
            self._emit(ProgressEvent(
                type=ProgressEventType.JOB_COMPLETED,
                summary=self._summary,
            ))
            return self._summary

        # Create channel output directory
        channel_name = videos[0].channel.name if videos[0].channel else handle
        from ytx.utils.filenames import sanitize_filename

        channel_dir = os.path.join(self.output_dir, sanitize_filename(channel_name))
        os.makedirs(channel_dir, exist_ok=True)

        # In structured mode, videos go into a videos/ subdirectory.
        # In flat mode, videos go directly into the channel directory.
        if self.output_layout == OutputLayout.STRUCTURED:
            videos_dir = os.path.join(channel_dir, "videos")
            os.makedirs(videos_dir, exist_ok=True)
        else:
            videos_dir = channel_dir

        # Initialize manifest. Use a hidden file in flat mode to avoid clutter.
        if self.output_layout == OutputLayout.FLAT:
            manifest_path = os.path.join(channel_dir, ".ytx-manifest.json")
        else:
            manifest_path = os.path.join(channel_dir, "manifest.json")
        manifest = Manifest(manifest_path)
        manifest.set_source("channel", url, videos[0].channel.id if videos[0].channel else handle)

        results = self._process_videos(videos, manifest, videos_dir)

        # Always write combined output (even on cancellation, completed transcripts exist)
        self._write_combined_safe(results, channel_dir)

        self._emit(ProgressEvent(
            type=ProgressEventType.JOB_COMPLETED,
            summary=self._summary,
        ))
        return self._summary

    def _process_videos(
        self,
        videos: list[VideoMetadata],
        manifest: Manifest,
        base_dir: str,
    ) -> list[TranscriptResult]:
        """Process a list of videos with progress display."""
        results: list[TranscriptResult] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing videos...", total=len(videos))

            for i, video in enumerate(videos):
                # Check for cancellation
                if self._cancelled:
                    completed = len(results)
                    console.print(
                        f"\n[yellow]Cancelled after {completed} completed "
                        f"{'video' if completed == 1 else 'videos'}.[/yellow]"
                    )
                    console.print("[yellow]Completed transcripts preserved. "
                                  "No further videos will be processed.[/yellow]")
                    logger.info("Pipeline cancelled after %d/%d videos", i, len(videos))
                    break

                # Check for shared playback client error. Pause the batch if found.
                if self._playback_client_error:
                    completed = len(results)
                    remaining = len(videos) - i
                    console.print(
                        f"\n[yellow]Playback session error after {completed} completed "
                        f"{'video' if completed == 1 else 'videos'}. "
                        f"{remaining} videos not attempted.[/yellow]"
                    )
                    console.print(
                        "[yellow]Try refreshing YouTube in Firefox, then resume.[/yellow]"
                    )
                    logger.info(
                        "Pipeline paused due to playback client error after %d/%d videos",
                        i, len(videos),
                    )
                    break

                progress.update(
                    task,
                    description=f"[{i+1}/{len(videos)}] {video.title[:50]}",
                )

                self._emit(ProgressEvent(
                    type=ProgressEventType.VIDEO_STARTED,
                    video_id=video.id,
                    video_title=video.title,
                    current=i + 1,
                    total=len(videos),
                ))

                # Always check manifest for resume behavior
                existing_status = manifest.get_video_status(video.id)
                if existing_status == ProcessingStatus.COMPLETE:
                    # Validate saved transcript exists and is valid
                    loaded = self._load_existing_transcript(video, manifest, base_dir)
                    if loaded is not None:
                        results.append(loaded)
                        self._summary.skipped_existing += 1
                        self._emit(ProgressEvent(
                            type=ProgressEventType.VIDEO_SKIPPED,
                            video_id=video.id,
                            video_title=video.title,
                            current=i + 1,
                            total=len(videos),
                            message="Already completed",
                        ))
                        progress.advance(task)
                        continue
                    # Transcript missing or corrupt. Process it again.
                    logger.debug(
                        "Manifest says complete for %s but transcript invalid, reprocessing",
                        video.id,
                    )

                result = self._process_video(video, manifest, base_dir)
                self._update_summary(result)

                if self.verbose:
                    self._print_result(result)

                # Emit per-video completion event
                if result.status == ProcessingStatus.COMPLETE:
                    source_label = ""
                    if result.transcript_source:
                        source_label = result.transcript_source.value
                    self._emit(ProgressEvent(
                        type=ProgressEventType.VIDEO_COMPLETED,
                        video_id=video.id,
                        video_title=video.title,
                        current=i + 1,
                        total=len(videos),
                        source=source_label,
                        output_paths=result.output_paths,
                    ))
                elif result.status == ProcessingStatus.FAILED:
                    self._emit(ProgressEvent(
                        type=ProgressEventType.VIDEO_FAILED,
                        video_id=video.id,
                        video_title=video.title,
                        current=i + 1,
                        total=len(videos),
                        error=result.error,
                    ))

                # Build TranscriptResult for combined output if successful
                if result.status == ProcessingStatus.COMPLETE:
                    transcript = self._load_transcript_from_result(video, result)
                    if transcript is not None:
                        results.append(
                            TranscriptResult(video=video, transcript=transcript)
                        )

                manifest.save()
                progress.advance(task)

                # Delay between videos to avoid rate limiting
                if self.delay > 0 and i < len(videos) - 1:
                    time.sleep(self.delay)

        manifest.save()
        return results

    def _load_existing_transcript(
        self, video: VideoMetadata, manifest: Manifest, base_dir: str | None = None
    ) -> TranscriptResult | None:
        """Load an existing transcript for a skipped video.

        Tries to find the JSON transcript from manifest output paths,
        then falls back to the expected output location.
        If JSON not found, tries to parse from .md file (recovery for pre-fix batches).
        Returns None if the transcript cannot be loaded.
        """
        # Try manifest output paths first
        output_paths = manifest.get_video_output_paths(video.id)
        json_path = None
        md_path = None
        for path in output_paths:
            if path.endswith(".json") and os.path.exists(path):
                json_path = path
                break
            if path.endswith(".md") and os.path.exists(path):
                md_path = path

        # Fallback: expected location
        if json_path is None:
            search_dir = base_dir or self.output_dir
            if self.output_layout == OutputLayout.FLAT:
                # Flat mode: look for title-based json file
                from ytx.utils.filenames import sanitize_filename
                safe_title = sanitize_filename(video.title, max_length=200)
                json_path = os.path.join(search_dir, f"{safe_title}.json")
                if md_path is None:
                    md_path = os.path.join(search_dir, f"{safe_title}.md")
            else:
                # Structured mode: look in per-video directory
                video_dir = os.path.join(
                    search_dir,
                    safe_video_dirname(video.id, video.title),
                )
                json_path = os.path.join(video_dir, "transcript.json")
                if md_path is None:
                    md_path = os.path.join(video_dir, "transcript.md")

        # Try JSON first
        if os.path.exists(json_path):
            transcript = load_saved_transcript(json_path)
            if transcript is not None:
                return TranscriptResult(video=video, transcript=transcript)

        # Fallback: parse from .md file (recovery for pre-fix batches)
        if md_path and os.path.exists(md_path):
            transcript = self._parse_markdown_transcript(md_path, video)
            if transcript is not None:
                logger.info("Recovered transcript from markdown: %s", md_path)
                return TranscriptResult(video=video, transcript=transcript)

        logger.debug("No saved transcript found for %s", video.id)
        return None

    def _parse_markdown_transcript(
        self, md_path: str, video: VideoMetadata
    ) -> Transcript | None:
        """Parse a YTX markdown file to recover transcript text.

        This is a recovery path for batches processed before the JSON fix.
        """
        try:
            with open(md_path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return None

        # Find the transcript section
        marker = "## Transcript"
        idx = content.find(marker)
        if idx < 0:
            return None

        body = content[idx + len(marker):].strip()
        if not body:
            return None

        # Create a simple transcript from the text
        segments = []
        for line in body.split("\n"):
            line = line.strip()
            if line:
                segments.append(TranscriptSegment(
                    start=0.0, duration=0.0, text=line
                ))

        if not segments:
            return None

        return Transcript(
            language="unknown",
            language_name="Unknown",
            source=TranscriptSource.YOUTUBE_AUTO,
            is_generated=True,
            segments=segments,
        )

    def _load_transcript_from_result(
        self, video: VideoMetadata, result: ProcessingResult
    ) -> Transcript | None:
        """Load transcript from the output paths of a ProcessingResult.

        Tries JSON first, then falls back to markdown parsing.
        """
        for path in result.output_paths:
            if path.endswith(".json"):
                return load_saved_transcript(path)
        # Fallback: try to parse from markdown
        for path in result.output_paths:
            if path.endswith(".md"):
                transcript = self._parse_markdown_transcript(path, video)
                if transcript is not None:
                    return transcript
        return None

    def _get_existing_video_dir(
        self, video: VideoMetadata, manifest: Manifest | None
    ) -> str | None:
        """Get the existing output directory for a video from the manifest.

        Returns the directory path if the manifest has output paths for this video,
        None otherwise. This ensures stable directory identity even when titles change.
        """
        if manifest is None:
            return None
        output_paths = manifest.get_video_output_paths(video.id)
        if output_paths:
            return os.path.dirname(output_paths[0])
        return None

    def _process_video(
        self,
        video: VideoMetadata,
        manifest: Manifest | None = None,
        base_dir: str | None = None,
    ) -> ProcessingResult:
        """Process a single video: extract transcript and write output."""
        video_start = time.monotonic()
        metrics = ProcessingMetrics(video_duration_seconds=video.duration_seconds)

        if manifest:
            manifest.set_video_status(video.id, ProcessingStatus.PROCESSING)
            manifest.save()

        # Try caption extraction first
        transcript = None
        source = None
        caption_error: Exception | None = None
        try:
            langs = [self.language] if self.language else None
            transcript = fetch_captions(video.id, languages=langs)
            transcript = normalize_transcript(transcript)
            source = transcript.source
            metrics.segment_count = len(transcript.segments)
            metrics.transcription_language = transcript.language
            self._emit(ProgressEvent(
                type=ProgressEventType.CAPTIONS_FOUND,
                video_id=video.id,
                video_title=video.title,
                source=transcript.source.value,
            ))
            # Warn if language fallback occurred
            if (
                self.language
                and transcript.requested_language
                and transcript.language != transcript.requested_language
            ):
                source_label = transcript.source.value.replace("_", " ")
                console.print(
                    f"  [yellow]Requested captions: {transcript.requested_language}[/yellow]"
                )
                console.print(
                    f"  [yellow]Using {transcript.language_name} "
                    f"{source_label} instead.[/yellow]"
                )
        except NoCaptionsError as e:
            caption_error = e
            self._emit(ProgressEvent(
                type=ProgressEventType.CAPTIONS_MISSING,
                video_id=video.id,
                video_title=video.title,
                message="No captions available",
            ))
        except CaptionAccessBlockedError as e:
            caption_error = e
            # Emit batch warning once when caption retrieval is blocked
            if not self._caption_blocked_warned:
                self._caption_blocked_warned = True
                self._emit(ProgressEvent(
                    type=ProgressEventType.JOB_WARNING,
                    message=(
                        "YouTube caption retrieval is blocked on this network. "
                        "Remaining videos may require local transcription."
                    ),
                ))
            self._emit(ProgressEvent(
                type=ProgressEventType.CAPTIONS_MISSING,
                video_id=video.id,
                video_title=video.title,
                message="Caption retrieval blocked",
            ))
        except CaptionRetrievalError as e:
            caption_error = e
            self._emit(ProgressEvent(
                type=ProgressEventType.CAPTIONS_MISSING,
                video_id=video.id,
                video_title=video.title,
                message="Caption retrieval failed",
            ))

        # If captions failed, decide what to do
        if caption_error is not None:
            # Check cancellation before falling through to transcription
            if self._cancelled:
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error="Cancelled",
                    metrics=metrics,
                )
            if self.transcribe_missing:
                # Fall through to local transcription
                pass
            else:
                # Provide specific error message based on error type
                if isinstance(caption_error, NoCaptionsError):
                    error_msg = "No captions available"
                    hint = "Use --transcribe-missing to create locally."
                elif isinstance(caption_error, CaptionAccessBlockedError):
                    error_msg = (
                        "YouTube blocked caption retrieval from this network. "
                        "Try again later or use --transcribe-missing."
                    )
                    hint = ""
                else:
                    error_msg = f"Failed to retrieve captions: {caption_error.reason}"
                    hint = "Use --transcribe-missing as fallback."

                full_error = f"{error_msg} {hint}".strip()
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                if manifest:
                    manifest.set_video_status(
                        video.id,
                        ProcessingStatus.FAILED,
                        error=full_error,
                    )
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error=error_msg,
                    metrics=metrics,
                )

        # Local transcription fallback (either no captions, blocked, or retrieval failed)
        if transcript is None and caption_error is not None and self.transcribe_missing:
            # Bulk fail-fast: if auth was already required, don't try more videos
            if self._auth_required:
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                if manifest:
                    manifest.set_video_status(
                        video.id, ProcessingStatus.FAILED,
                        error="YouTube sign-in required",
                    )
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error="YouTube sign-in required",
                    metrics=metrics,
                )

            try:
                # Check cancellation before audio download
                if self._cancelled:
                    metrics.processing_elapsed_seconds = time.monotonic() - video_start
                    return ProcessingResult(
                        video_id=video.id,
                        status=ProcessingStatus.FAILED,
                        error="Cancelled",
                        metrics=metrics,
                    )
                transcriber = self._get_transcriber()
                self._emit(ProgressEvent(
                    type=ProgressEventType.AUDIO_DOWNLOAD_STARTED,
                    video_id=video.id,
                    video_title=video.title,
                ))

                # Auto mode: try unauthenticated first, retry with Firefox on auth error
                use_firefox = self.youtube_auth == YouTubeAuthMode.FIREFOX
                try:
                    audio_path = download_audio(
                        video.id,
                        output_dir=base_dir,
                        keep=self.keep_audio,
                        auth_mode=self.youtube_auth,
                        use_firefox_auth=use_firefox,
                    )
                except YouTubeAuthenticationRequiredError:
                    if (
                        self.youtube_auth == YouTubeAuthMode.AUTO
                        and not self._firefox_retry_attempted
                    ):
                        # Auto mode: retry with Firefox
                        self._firefox_retry_attempted = True
                        logger.info("Auth required for %s, retrying with Firefox", video.id)
                        self._emit(ProgressEvent(
                            type=ProgressEventType.JOB_WARNING,
                            message="YouTube requires sign-in. Retrying with Firefox session...",
                        ))
                        audio_path = download_audio(
                            video.id,
                            output_dir=base_dir,
                            keep=self.keep_audio,
                            auth_mode=self.youtube_auth,
                            use_firefox_auth=True,
                        )
                    else:
                        # Firefox mode already or retry failed
                        self._auth_required = True
                        raise
                except YouTubePlaybackClientError:
                    # Retry with alternate player client when browser auth is active
                    if use_firefox or self.youtube_auth == YouTubeAuthMode.FIREFOX:
                        logger.info(
                            "Playback client error for %s, retrying with web_embedded client",
                            video.id,
                        )
                        self._emit(ProgressEvent(
                            type=ProgressEventType.JOB_WARNING,
                            message=(
                                "YouTube playback session failed. "
                                "Retrying with alternate player client..."
                            ),
                        ))
                        try:
                            audio_path = download_audio(
                                video.id,
                                output_dir=base_dir,
                                keep=self.keep_audio,
                                auth_mode=self.youtube_auth,
                                use_firefox_auth=use_firefox,
                                player_client="default,web_embedded",
                            )
                        except YouTubePlaybackClientError:
                            # Retry also failed. Pause the batch.
                            self._playback_client_error = True
                            raise
                    else:
                        # No browser auth active, can't retry meaningfully
                        self._playback_client_error = True
                        raise
                try:
                    # Resolve model size through centralized mapping
                    resolved_model = resolve_model_size(self.model_size)
                    metrics.transcription_model = resolved_model
                    metrics.transcription_language = self.language

                    # Check cancellation before starting transcription
                    if self._cancelled:
                        metrics.processing_elapsed_seconds = time.monotonic() - video_start
                        return ProcessingResult(
                            video_id=video.id,
                            status=ProcessingStatus.FAILED,
                            error="Cancelled",
                            metrics=metrics,
                        )

                    self._emit(ProgressEvent(
                        type=ProgressEventType.TRANSCRIPTION_STARTED,
                        video_id=video.id,
                        video_title=video.title,
                        model_size=resolved_model,
                        language=self.language,
                    ))
                    transcription_start = time.monotonic()
                    transcript = transcriber.transcribe(
                        audio_path,
                        language=self.language,
                        model_size=resolved_model,
                    )
                    transcription_elapsed = time.monotonic() - transcription_start
                    transcript = normalize_transcript(transcript)
                    source = TranscriptSource.LOCAL_TRANSCRIPTION

                    # Record metrics
                    metrics.transcription_elapsed_seconds = transcription_elapsed
                    metrics.segment_count = len(transcript.segments)
                    metrics.transcription_language = transcript.language
                    if video.duration_seconds and transcription_elapsed > 0:
                        metrics.transcription_speed_x = (
                            video.duration_seconds / transcription_elapsed
                        )

                    self._emit(ProgressEvent(
                        type=ProgressEventType.TRANSCRIPTION_COMPLETED,
                        video_id=video.id,
                        video_title=video.title,
                        message=f"{len(transcript.segments)} segments",
                        metrics=metrics,
                    ))
                finally:
                    if not self.keep_audio:
                        cleanup_audio(audio_path)
            except YouTubeAuthenticationRequiredError:
                self._auth_required = True
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                error_msg = (
                    "YouTube sign-in required. "
                    "Use your signed-in Firefox session to continue."
                )
                self._emit(ProgressEvent(
                    type=ProgressEventType.JOB_WARNING,
                    message=error_msg,
                ))
                if manifest:
                    manifest.set_video_status(
                        video.id, ProcessingStatus.FAILED, error=error_msg
                    )
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error=error_msg,
                    metrics=metrics,
                )
            except YouTubePlaybackClientError:
                self._playback_client_error = True
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                error_msg = (
                    "Firefox session could not be used. "
                    "The current yt-dlp/YouTube authenticated playback path failed. "
                    "Try Automatic mode first."
                )
                self._emit(ProgressEvent(
                    type=ProgressEventType.JOB_WARNING,
                    message=error_msg,
                ))
                if manifest:
                    manifest.set_video_status(
                        video.id, ProcessingStatus.FAILED, error=error_msg
                    )
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error=error_msg,
                    metrics=metrics,
                )
            except (TranscriptionError, TranscriptionDependencyError, AudioDownloadError) as e:
                metrics.processing_elapsed_seconds = time.monotonic() - video_start
                if manifest:
                    manifest.set_video_status(
                        video.id, ProcessingStatus.FAILED, error=str(e)
                    )
                return ProcessingResult(
                    video_id=video.id,
                    status=ProcessingStatus.FAILED,
                    error=str(e),
                    metrics=metrics,
                )

        if transcript is None:
            metrics.processing_elapsed_seconds = time.monotonic() - video_start
            if manifest:
                manifest.set_video_status(
                    video.id, ProcessingStatus.FAILED, error="No transcript produced"
                )
            return ProcessingResult(
                video_id=video.id,
                status=ProcessingStatus.FAILED,
                error="No transcript produced",
                metrics=metrics,
            )

        # Write output
        result = TranscriptResult(video=video, transcript=transcript, metrics=metrics)
        if self.output_layout == OutputLayout.FLAT:
            # Flat layout: resolve unique filename, write directly in base_dir
            flat_basename = self._resolve_flat_filename(video, base_dir or self.output_dir)
            # Check manifest for existing flat files (title change handling)
            existing_paths = manifest.get_video_output_paths(video.id) if manifest else []
            if existing_paths and os.path.exists(existing_paths[0]):
                # Reuse existing flat path basename
                existing_basename = os.path.splitext(os.path.basename(existing_paths[0]))[0]
                flat_basename = existing_basename
                self._used_filenames[existing_basename] = video.id
            output_paths = self._write_output(result, base_dir, flat_basename=flat_basename)
        else:
            # Structured layout: reuse existing directory if manifest has one
            existing_dir = self._get_existing_video_dir(video, manifest)
            output_paths = self._write_output(result, base_dir, video_dir=existing_dir)

        metrics.processing_elapsed_seconds = time.monotonic() - video_start

        self._emit(ProgressEvent(
            type=ProgressEventType.OUTPUT_WRITTEN,
            video_id=video.id,
            video_title=video.title,
            message=f"{len(output_paths)} files",
            output_paths=output_paths,
        ))

        if manifest:
            manifest.set_video_status(
                video.id,
                ProcessingStatus.COMPLETE,
                transcript_source=source,
                output_paths=output_paths,
                metrics=metrics,
            )

        return ProcessingResult(
            video_id=video.id,
            status=ProcessingStatus.COMPLETE,
            transcript_source=source,
            output_paths=output_paths,
            metrics=metrics,
        )

    def _write_output(
        self,
        result: TranscriptResult,
        base_dir: str | None = None,
        video_dir: str | None = None,
        flat_basename: str | None = None,
    ) -> list[str]:
        """Write transcript to all requested formats.

        Args:
            result: The transcript result to write.
            base_dir: Base output directory.
            video_dir: Existing video directory (from manifest). Used in structured mode.
            flat_basename: If set, write flat files using this basename (e.g., "Video Title").

        Only writes formats the user explicitly requested.
        """
        if base_dir is None:
            base_dir = self.output_dir

        if flat_basename is not None:
            # Flat layout: files directly in base_dir with title-based names
            os.makedirs(base_dir, exist_ok=True)
            writers = {
                "txt": (write_txt, f"{flat_basename}.txt"),
                "md": (write_markdown, f"{flat_basename}.md"),
                "json": (write_json, f"{flat_basename}.json"),
                "srt": (write_srt, f"{flat_basename}.srt"),
            }
        else:
            # Structured layout: per-video directory with fixed filenames
            if video_dir is None:
                dirname = safe_video_dirname(result.video.id, result.video.title)
                video_dir = os.path.join(base_dir, dirname)
            os.makedirs(video_dir, exist_ok=True)
            writers = {
                "txt": (write_txt, "transcript.txt"),
                "md": (write_markdown, "transcript.md"),
                "json": (write_json, "transcript.json"),
                "srt": (write_srt, "transcript.srt"),
            }

        paths: list[str] = []
        for fmt in self.formats:
            if fmt in writers:
                writer_func, filename = writers[fmt]
                if flat_basename is not None:
                    path = os.path.join(base_dir, filename)
                else:
                    path = os.path.join(video_dir, filename)
                try:
                    writer_func(result, path, include_timestamps=self.include_timestamps)
                    paths.append(path)
                except Exception as e:
                    logger.error("Failed to write %s for %s: %s", fmt, result.video.id, e)

        return paths

    def _write_combined(self, results: list[TranscriptResult], output_dir: str) -> None:
        """Write combined dataset files."""
        successful = [r for r in results if r.transcript is not None]
        if not successful:
            return

        if "json" in self.formats:
            jsonl_path = os.path.join(output_dir, "combined.jsonl")
            write_combined_jsonl(successful, jsonl_path)
            console.print(f"  Combined JSONL: {jsonl_path}")

        if "md" in self.formats:
            md_path = os.path.join(output_dir, "combined.md")
            write_combined_markdown(successful, md_path)
            console.print(f"  Combined Markdown: {md_path}")

    def _write_combined_safe(
        self, results: list[TranscriptResult], output_dir: str
    ) -> None:
        """Write combined output files.

        In flat mode, writes output.md (AI-ready corpus).
        In structured mode, writes combined.md (legacy format).
        Also writes JSONL if combine_jsonl is set.
        """
        successful = [r for r in results if r.transcript is not None]
        if not successful:
            return

        if self.output_layout == OutputLayout.FLAT:
            # Flat mode: write output.md
            from ytx.output.combined import write_output_md

            md_path = os.path.join(output_dir, "output.md")
            write_output_md(successful, md_path)
            console.print(f"  Combined transcript: {md_path}")
        else:
            # Structured mode: write combined.md (legacy)
            md_path = os.path.join(output_dir, "combined.md")
            write_combined_markdown(successful, md_path)
            console.print(f"  Combined transcript: {md_path}")

        # Optionally write JSONL
        if self.combine_jsonl:
            jsonl_path = os.path.join(output_dir, "combined.jsonl")
            write_combined_jsonl(successful, jsonl_path)
            console.print(f"  Combined JSONL: {jsonl_path}")

    def _update_summary(self, result: ProcessingResult) -> None:
        """Update the job summary based on a processing result."""
        if result.status == ProcessingStatus.COMPLETE:
            if result.transcript_source == TranscriptSource.LOCAL_TRANSCRIPTION:
                self._summary.locally_transcribed += 1
            else:
                self._summary.captions_extracted += 1
        elif result.status == ProcessingStatus.FAILED:
            self._summary.failed += 1
        elif result.status == ProcessingStatus.SKIPPED:
            self._summary.skipped_existing += 1

    def _print_result(self, result: ProcessingResult) -> None:
        """Print a single result to the console."""
        if result.status == ProcessingStatus.COMPLETE:
            source_label = ""
            if result.transcript_source:
                source_label = result.transcript_source.value.replace("_", " ")
            console.print(f"  [green]OK[/green] {result.video_id} ({source_label})")
        elif result.status == ProcessingStatus.FAILED:
            console.print(f"  [red]FAIL[/red] {result.video_id}: {result.error}")
        elif result.status == ProcessingStatus.SKIPPED:
            console.print(f"  [yellow]SKIP[/yellow] {result.video_id}")

    def print_summary(self) -> None:
        """Print the final job summary."""
        console.print()
        console.print("[bold]Completed[/bold]")
        console.print()
        s = self._summary
        console.print(f"  Videos discovered:     {s.total_discovered:>5}")
        console.print(f"  Captions extracted:    {s.captions_extracted:>5}")
        console.print(f"  Locally transcribed:   {s.locally_transcribed:>5}")
        console.print(f"  Skipped existing:      {s.skipped_existing:>5}")
        console.print(f"  Failed:                {s.failed:>5}")
