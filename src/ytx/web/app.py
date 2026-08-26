"""FastAPI application for YTX Web."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ytx.exceptions import (
    CaptionAccessBlockedError,
    CaptionRetrievalError,
    TranscriptionDependencyError,
    TranscriptionError,
    URLError,
    YouTubeAuthenticationRequiredError,
    YTXError,
)
from ytx.models import OutputLayout, ProgressEvent, YouTubeAuthMode
from ytx.pipeline import Pipeline
from ytx.transcription.local import FasterWhisperProvider
from ytx.transcription.model_mapping import resolve_web_model
from ytx.web.jobs import Job, JobManager, JobStatus

logger = logging.getLogger(__name__)

app = FastAPI(title="YTX Web", version="0.1.0")

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

job_manager = JobManager()

# Valid browser IDs for youtube_auth parameter
_VALID_BROWSER_IDS = frozenset({"auto", "firefox", "brave", "safari", "chrome", "edge"})


def _validate_origin(request: Request) -> None:
    """Validate Origin/Host for state-changing requests.

    Rejects requests from unexpected remote origins to prevent CSRF attacks
    on localhost web apps.
    """
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")

    # If Origin is present, verify it is one of the local origins.
    if origin:
        parsed_origin = urlparse(origin)
        if parsed_origin.scheme != "http" or parsed_origin.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            logger.warning("Rejected request from origin: %s", origin)
            raise HTTPException(403, "Origin not allowed")

    # Verify Host header is local. Parse it so hosts such as localhost.evil
    # cannot pass a string-prefix check.
    host_name = urlparse(f"//{host}").hostname
    if host and host != "testserver" and host_name not in {"127.0.0.1", "localhost"}:
        logger.warning("Rejected request with host: %s", host)
        raise HTTPException(403, "Host not allowed")


def _run_job_thread(job: Job, params: dict) -> None:
    """Run a pipeline job in a background thread."""
    try:
        def on_progress(event: ProgressEvent) -> None:
            job_manager.handle_progress_event(job, event)

        pipeline = Pipeline(
            output_dir=params["output_dir"],
            formats=params["formats"],
            language=params.get("language"),
            transcribe_missing=params.get("transcribe_missing", False),
            keep_audio=params.get("keep_audio", False),
            include_timestamps=params.get("timestamps", True),
            skip_existing=params.get("skip_existing", True),
            model_size=params.get("model"),
            combine=params.get("combine", False),
            combine_jsonl=params.get("combine_jsonl", False),
            latest=params.get("latest"),
            delay=params.get("delay", 0.5),
            on_progress=on_progress,
            output_layout=OutputLayout(params.get("output_layout", "flat")),
            selected_video_ids=params.get("selected_video_ids"),
            youtube_auth=YouTubeAuthMode(params.get("youtube_auth", "auto")),
        )
        job._pipeline = pipeline
        job.output_directory = params["output_dir"]
        job.output_layout = params.get("output_layout", "flat")
        job.selected_video_ids = params.get("selected_video_ids")

        summary = pipeline.run(params["url"])
        job.summary = summary

        # If pipeline was cancelled, mark job as cancelled (combined.md already written)
        if pipeline._cancelled:
            job.status = JobStatus.CANCELLED
            job.add_event({"type": "job_cancelled"})
        # If pipeline paused due to playback client error, mark as paused
        elif pipeline._playback_client_error:
            job.status = JobStatus.PAUSED
            error_msg = (
                "Firefox session could not be used. "
                "The current yt-dlp/YouTube authenticated playback path failed. "
                "Try Automatic mode first."
            )
            if error_msg not in job.errors:
                job.errors.append(error_msg)
            job.add_event({
                "type": "job_paused",
                "error": "YouTube playback session failed",
            })
        # Otherwise status was already set by JOB_COMPLETED event

    except YouTubeAuthenticationRequiredError:
        logger.info("Job %s requires authentication", job.id)
        job.status = JobStatus.FAILED
        job.errors.append(
            "YouTube sign-in required. Use your signed-in Firefox session to continue."
        )
        job.add_event({
            "type": "job_failed",
            "error": "YouTube sign-in required",
        })
    except CaptionAccessBlockedError as e:
        logger.info("Job %s blocked: %s", job.id, e)
        job.status = JobStatus.FAILED
        job.errors.append(
            "YouTube blocked caption retrieval from this network. "
            "Try again later or enable local transcription."
        )
        job.add_event({
            "type": "job_failed",
            "error": str(e),
        })
    except CaptionRetrievalError as e:
        logger.info("Job %s caption retrieval failed: %s", job.id, e)
        job.status = JobStatus.FAILED
        job.errors.append(f"Caption retrieval failed: {e.reason}")
        job.add_event({
            "type": "job_failed",
            "error": str(e),
        })
    except (URLError, YTXError, TranscriptionDependencyError, TranscriptionError) as e:
        logger.info("Job %s failed: %s", job.id, e)
        job.status = JobStatus.FAILED
        job.errors.append(str(e))
        job.add_event({
            "type": "job_failed",
            "error": str(e),
        })
    except Exception as e:
        logger.exception("Job %s failed unexpectedly", job.id)
        job.status = JobStatus.FAILED
        job.errors.append(str(e))
        job.add_event({
            "type": "job_failed",
            "error": str(e),
        })
    finally:
        job_manager.clear_active(job.id)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Home page."""
    transcription = FasterWhisperProvider()
    has_transcription = transcription.is_available()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "has_transcription": has_transcription,
        },
    )


@app.get("/api/detect-url")
async def detect_url(url: str = ""):
    """Detect URL type for live feedback."""
    if not url.strip():
        return JSONResponse({"type": None})
    try:
        from ytx.youtube.urls import detect_url_type
        url_type, identifier = detect_url_type(url.strip())
        return JSONResponse({"type": url_type.value, "id": identifier})
    except URLError:
        return JSONResponse({"type": None})


@app.get("/api/browsers")
async def detect_browsers():
    """Detect supported browsers installed locally.

    Returns only browser id and display name.
    Never exposes paths, profiles, cookies, or any browser data.
    """
    from ytx.web.browser_detect import detect_supported_browsers

    browsers = detect_supported_browsers()
    return JSONResponse({
        "browsers": [b.to_dict() for b in browsers],
    })


@app.get("/api/discover")
async def discover_videos(url: str = ""):
    """Discover videos in a playlist/channel for manual selection."""
    if not url.strip():
        raise HTTPException(400, "URL is required")

    try:
        from ytx.youtube.urls import detect_url_type
        url_type, identifier = detect_url_type(url.strip())
    except URLError as e:
        raise HTTPException(400, str(e)) from e

    if url_type.value not in ("playlist", "channel"):
        raise HTTPException(400, "Manual selection is only available for playlists and channels")

    try:
        if url_type.value == "playlist":
            from ytx.youtube.discovery import discover_playlist_videos
            videos = discover_playlist_videos(url.strip())
        else:
            from ytx.youtube.discovery import discover_channel_videos
            videos = discover_channel_videos(url.strip())
    except Exception as e:
        raise HTTPException(500, f"Discovery failed: {e}") from e

    from ytx.models import DurationSummary
    dur = DurationSummary.from_videos(videos)

    return JSONResponse({
        "videos": [
            {
                "id": v.id,
                "title": v.title,
                "url": v.url,
                "duration_seconds": v.duration_seconds,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "thumbnail_url": v.thumbnail_url or None,
            }
            for v in videos
        ],
        "duration_summary": dur.to_dict(),
    })


@app.post("/jobs")
async def create_job(request: Request):
    """Create a new extraction job."""
    _validate_origin(request)

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(400, "Invalid JSON body") from e

    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL is required")

    # Validate URL
    try:
        from ytx.youtube.urls import detect_url_type
        detect_url_type(url)
    except URLError as e:
        raise HTTPException(400, str(e)) from e

    # Build params
    formats_raw = body.get("formats", "md,json")
    if isinstance(formats_raw, str):
        formats = [f.strip() for f in formats_raw.split(",") if f.strip()]
    else:
        formats = formats_raw

    valid_formats = {"txt", "md", "json", "srt"}
    for fmt in formats:
        if fmt not in valid_formats:
            raise HTTPException(400, f"Invalid format: {fmt}")

    # Map friendly model names to internal names using centralized mapping
    model_raw = body.get("model") or None
    model_resolved = resolve_web_model(model_raw)

    # Validate youtube_auth parameter
    youtube_auth = body.get("youtube_auth", "auto")
    if youtube_auth not in _VALID_BROWSER_IDS:
        raise HTTPException(400, f"Invalid youtube_auth value: {youtube_auth}")

    params = {
        "url": url,
        "output_dir": body.get("output_dir", "./output"),
        "formats": formats,
        "language": body.get("language") or None,
        "transcribe_missing": bool(body.get("transcribe_missing", True)),
        "keep_audio": bool(body.get("keep_audio", False)),
        "timestamps": bool(body.get("timestamps", False)),
        "skip_existing": bool(body.get("skip_existing", True)),
        "model": model_resolved,
        "combine": bool(body.get("combine", False)),
        "combine_jsonl": bool(body.get("combine_jsonl", False)),
        "latest": body.get("latest"),
        "delay": float(body.get("delay", 0.5)),
        "output_layout": body.get("output_layout", "flat"),
        "selected_video_ids": body.get("selected_video_ids"),
        "youtube_auth": youtube_auth,
    }

    if params["latest"] is not None:
        params["latest"] = int(params["latest"])

    try:
        job = job_manager.create_job(url)
        job.selected_video_ids = params.get("selected_video_ids")
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e

    thread = threading.Thread(
        target=_run_job_thread, args=(job, params), daemon=True
    )
    thread.start()

    return JSONResponse({"job_id": job.id})


@app.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    """Get job status page."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return templates.TemplateResponse(
        request,
        "job.html",
        {"job": job},
    )


@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """Get job status as JSON (for polling)."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JSONResponse(_job_to_dict(job))


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str, after: int = 0):
    """SSE endpoint for real-time job progress."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    def event_stream():
        last_index = after
        while True:
            events = job.get_events_since(last_index)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                last_index += 1

            if job.status in (
                JobStatus.COMPLETE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.PAUSED,
            ):
                # Send final state
                yield f"data: {json.dumps({'type': 'stream_end', 'status': job.status.value})}\n\n"
                break

            # Wait briefly for new events
            job._event_event.wait(timeout=1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    """Cancel a running job."""
    _validate_origin(request)

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status not in (JobStatus.QUEUED, JobStatus.DISCOVERING, JobStatus.PROCESSING):
        return JSONResponse({"error": "Job is not running"}, status_code=400)

    # Set CANCELLING state immediately so UI shows correct status
    job.status = JobStatus.CANCELLING

    pipeline = getattr(job, "_pipeline", None)
    if pipeline:
        pipeline.cancel()

    # Emit a cancellation event so the UI knows cancellation was requested.
    job.add_event({"type": "job_cancelling"})
    return JSONResponse({"ok": True})


@app.get("/jobs/{job_id}/videos/{video_id}")
async def get_video_transcript(request: Request, job_id: str, video_id: str):
    """View a video's transcript."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    video = job.videos.get(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    # Find transcript: prefer JSON, fall back to Markdown, then TXT
    transcript_data = None
    transcript_markdown = None
    has_timestamps = False

    for path in video.output_paths:
        if path.endswith(".json") and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if "transcript" in data and "segments" in data["transcript"]:
                    transcript_data = data
                    has_timestamps = any(
                        seg.get("start", 0) > 0
                        for seg in data["transcript"].get("segments", [])
                    )
                    break
            except (json.JSONDecodeError, OSError):
                pass

    if transcript_data is None:
        for path in video.output_paths:
            if path.endswith(".md") and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        transcript_markdown = f.read()
                    break
                except OSError:
                    pass

    if transcript_data is None and transcript_markdown is None:
        for path in video.output_paths:
            if path.endswith(".txt") and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        transcript_markdown = f.read()
                    break
                except OSError:
                    pass

    return templates.TemplateResponse(
        request,
        "transcript.html",
        {
            "job": job,
            "video": video,
            "transcript_data": transcript_data,
            "transcript_markdown": transcript_markdown,
            "has_timestamps": has_timestamps,
        },
    )


@app.get("/jobs/{job_id}/files/{video_id}/{filename}")
async def download_file(job_id: str, video_id: str, filename: str):
    """Download a transcript file. Validates path safety."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    video = job.videos.get(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    # Security: only allow known filenames
    allowed_files = {
        "transcript.txt",
        "transcript.md",
        "transcript.json",
        "transcript.srt",
    }
    # Also allow flat-layout filenames (title-based with known extensions)
    if filename not in allowed_files:
        # Check if it's a valid flat-layout filename: any name with allowed extension
        allowed_extensions = {".txt", ".md", ".json", ".srt"}
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_extensions or filename.startswith("."):
            raise HTTPException(403, "File not allowed")

    # Find the file in output_paths
    target_path = None
    for path in video.output_paths:
        if os.path.basename(path) == filename and os.path.exists(path):
            # Security: verify the path is inside the output directory
            real_path = os.path.realpath(path)
            output_root = os.path.realpath(job.output_directory or "./output")
            if not real_path.startswith(output_root + os.sep) and real_path != output_root:
                raise HTTPException(403, "Access denied")
            target_path = real_path
            break

    if not target_path:
        raise HTTPException(404, "File not found")

    media_types = {
        "transcript.txt": "text/plain",
        "transcript.md": "text/markdown",
        "transcript.json": "application/json",
        "transcript.srt": "text/plain",
    }
    # Also map flat-layout extensions
    ext = os.path.splitext(filename)[1].lower()
    ext_media_types = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".srt": "text/plain",
    }

    from fastapi.responses import FileResponse

    return FileResponse(
        target_path,
        media_type=media_types.get(filename, ext_media_types.get(ext, "application/octet-stream")),
        filename=filename,
    )


@app.get("/jobs/{job_id}/combined/{filename}")
async def download_combined_file(job_id: str, filename: str):
    """Download a combined transcript file (output.md, combined.md, or combined.jsonl)."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Security: only allow known combined filenames
    allowed_files = {"output.md", "combined.md", "combined.jsonl"}
    if filename not in allowed_files:
        raise HTTPException(403, "File not allowed")

    if not job.output_directory:
        raise HTTPException(404, "Output directory not set")

    target_path = os.path.join(job.output_directory, filename)

    # Security: verify path is inside output directory
    real_path = os.path.realpath(target_path)
    output_root = os.path.realpath(job.output_directory)
    if not real_path.startswith(output_root + os.sep) and real_path != output_root:
        raise HTTPException(403, "Access denied")

    if not os.path.exists(real_path):
        raise HTTPException(404, "File not found")

    media_types = {
        "output.md": "text/markdown",
        "combined.md": "text/markdown",
        "combined.jsonl": "application/json",
    }

    from fastapi.responses import FileResponse

    return FileResponse(
        real_path,
        media_type=media_types.get(filename, "application/octet-stream"),
        filename=filename,
    )


def _job_to_dict(job: Job) -> dict:
    """Convert job state to a JSON-serializable dict."""
    videos = []
    for vid_id in job.video_order:
        vs = job.videos.get(vid_id)
        if vs:
            video_dict: dict[str, Any] = {
                "id": vs.id,
                "title": vs.title,
                "status": vs.status.value,
                "source": vs.source,
                "error": vs.error,
                "output_paths": vs.output_paths,
            }
            if vs.metrics:
                video_dict["metrics"] = vs.metrics.to_dict()
            videos.append(video_dict)

    # Calculate aggregate speed
    aggregate_speed = None
    if job.total_local_transcription_seconds > 0 and job.total_local_content_seconds > 0:
        aggregate_speed = job.total_local_content_seconds / job.total_local_transcription_seconds

    # Check for combined files
    combined_files = []
    if job.output_directory:
        # Combined files are in the output directory for playlists/channels
        # Flat mode uses output.md, structured mode uses combined.md
        for fname in ("output.md", "combined.md", "combined.jsonl"):
            fpath = os.path.join(job.output_directory, fname)
            if os.path.exists(fpath):
                combined_files.append(fname)

    # Determine manifest path
    manifest_path = None
    if job.output_directory:
        for candidate in (".ytx-manifest.json", "manifest.json"):
            mp = os.path.join(job.output_directory, candidate)
            if os.path.exists(mp):
                manifest_path = mp
                break

    return {
        "id": job.id,
        "source_url": job.source_url,
        "status": job.status.value,
        "total_videos": job.total_videos,
        "completed_videos": job.completed_videos,
        "failed_videos": job.failed_videos,
        "skipped_videos": job.skipped_videos,
        "current_video_id": job.current_video_id,
        "current_video_title": job.current_video_title,
        "current_phase": job.current_phase,
        "videos": videos,
        "errors": job.errors,
        "error_counts": job.error_counts,
        "warnings": job.warnings,
        "is_fatal_error": job.is_fatal_error,
        "fatal_error_message": job.fatal_error_message,
        "output_directory": job.output_directory,
        "combined_files": combined_files,
        "summary": job.summary.to_dict() if job.summary else None,
        "local_metrics": {
            "total_content_seconds": job.total_local_content_seconds,
            "total_transcription_seconds": job.total_local_transcription_seconds,
            "count": job.local_transcription_count,
            "aggregate_speed_x": aggregate_speed,
        },
        "duration_summary": job.duration_summary.to_dict() if job.duration_summary else None,
        "output_layout": job.output_layout,
        "manifest_path": manifest_path,
    }
