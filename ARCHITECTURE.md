# YTX Architecture

## Dependency Research

| Library | Purpose | Version | License | Maintenance | Risk |
|---------|---------|---------|---------|-------------|------|
| youtube-transcript-api | Caption extraction | 1.2.4 | MIT | Active (Jan 2026) | YouTube internal API changes |
| yt-dlp | Video/audio download, metadata, playlist/channel discovery | 2026.8.19 | Unlicense | Very active | YouTube changes |
| faster-whisper | Local transcription via CTranslate2 | 1.2.1 | MIT | Active (Oct 2025) | Model download size |
| click | CLI framework | 8.x | MIT | Very active | Low |
| rich | Terminal UI | 15.0.0 | MIT | Active (Apr 2026) | Low |
| fastapi | Web framework (optional) | 0.115+ | MIT | Very active | Low |
| uvicorn | ASGI server (optional) | 0.34+ | MIT | Very active | Low |
| jinja2 | Templates (optional) | 3.1+ | MIT | Very active | Low |

### Key Decisions

- **Python 3.10+**: yt-dlp requires 3.10+. This is the floor.
- **faster-whisper over openai-whisper**: 4x faster, lower memory, no system ffmpeg required (uses PyAV). MIT licensed.
- **yt-dlp for discovery**: Handles video, playlist, channel URL resolution and metadata extraction. We wrap it behind our own adapter.
- **youtube-transcript-api for captions**: Dedicated, lightweight, well-maintained. Separate from yt-dlp.
- **click for CLI**: Replaced typer to support both `ytx URL` and `ytx web` without breaking backward compatibility.
- **dataclasses over Pydantic**: Simpler, no extra dependency, sufficient for our models.
- **FastAPI + SSE for web**: Lightweight, async, SSE for real-time progress without WebSocket complexity.

## Architecture

```
                    YTX Core
                       │
             ┌─────────┴─────────┐
             │                   │
             ▼                   ▼
           CLI                  Web
        (click)            (FastAPI)
                              │
                         ┌────┴────┐
                         │         │
                      Routes    JobManager
                         │         │
                      SSE/HTML   Pipeline
```

The Pipeline is the shared core. Both CLI and Web call Pipeline with the same parameters. The Web layer adds a `ProgressCallback` to receive real-time events.

## Module Structure

```
src/ytx/
├── __init__.py
├── __main__.py
├── cli.py              # click CLI with 'ytx URL' and 'ytx web'
├── config.py           # version, defaults
├── models.py           # dataclasses + progress events
├── exceptions.py       # custom exceptions
├── pipeline.py         # orchestrates everything, emits progress events
├── youtube/
│   ├── __init__.py
│   ├── urls.py         # URL detection/normalization
│   └── discovery.py    # yt-dlp wrapper for video listing + metadata
├── transcripts/
│   ├── __init__.py
│   ├── captions.py     # youtube-transcript-api wrapper
│   ├── normalize.py    # normalize to canonical Transcript
│   └── selection.py    # language selection logic
├── transcription/
│   ├── __init__.py
│   ├── base.py         # abstract provider
│   └── local.py        # faster-whisper implementation
├── audio/
│   ├── __init__.py
│   └── downloader.py   # yt-dlp audio extraction
├── output/
│   ├── __init__.py
│   ├── base.py         # writer protocol
│   ├── txt.py
│   ├── markdown.py
│   ├── json_writer.py
│   ├── srt.py
│   └── combined.py     # JSONL + combined markdown
├── state/
│   ├── __init__.py
│   └── manifest.py     # resume/skip state
├── utils/
│   ├── __init__.py
│   ├── filenames.py    # sanitization
│   └── timestamps.py   # formatting
└── web/
    ├── __init__.py
    ├── app.py          # FastAPI app, routes, SSE
    ├── jobs.py         # in-memory job manager
    ├── static/
    │   ├── app.css
    │   └── htmx.min.js
    └── templates/
        ├── base.html
        ├── index.html
        ├── job.html
        └── transcript.html
```

## Progress Events

The Pipeline emits `ProgressEvent` objects through an optional `on_progress` callback. The CLI ignores these (uses Rich console directly). The Web layer's `JobManager` translates them into job state updates and SSE streams.

```
ProgressEventType:
  JOB_STARTED → DISCOVERY_STARTED → DISCOVERY_COMPLETE
    → VIDEO_STARTED → CAPTIONS_FOUND/MISSING → OUTPUT_WRITTEN → VIDEO_COMPLETED
    → VIDEO_STARTED → ... → VIDEO_FAILED
  → JOB_COMPLETED
```

## Web Layer

- **FastAPI** serves the UI and API
- **JobManager** is an in-memory singleton tracking jobs (one active at a time)
- **SSE** (`/jobs/{id}/events`) streams real-time progress to the browser
- **Threading** runs Pipeline in a background thread to avoid blocking the event loop
- **No database**: manifest.json on disk handles persistence
- **Localhost-only** default binding (127.0.0.1)

## Transcript Source Enum

```
youtube_manual   - human-created captions
youtube_auto     - auto-generated captions
youtube_translated - translated captions
local_transcription - locally generated via speech-to-text
```

## Processing Status

```
pending → processing → complete
                     → failed
                     → skipped
```

## Exit Codes

- 0: success
- 1: fatal error
- 2: invalid input/CLI usage
- 3: partial failure (some videos failed)
