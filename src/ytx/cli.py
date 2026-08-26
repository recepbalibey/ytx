"""CLI entry point."""

from __future__ import annotations

import json
import signal
import webbrowser
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from ytx import __version__
from ytx.config import DEFAULT_DELAY, DEFAULT_MODEL_SIZE, DEFAULT_OUTPUT_DIR
from ytx.exceptions import TranscriptionDependencyError, URLError, YTXError
from ytx.models import OutputLayout, YouTubeAuthMode
from ytx.pipeline import Pipeline

console = Console()

_URL_PREFIXES = ("http://", "https://", "www.", "youtube.com", "youtu.be", "yt.be")
_VIDEO_ID_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


class YTXGroup(click.Group):
    """Custom group that makes 'ytx URL' work as the default extract command."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if (
            cmd_name
            and not self.commands.get(cmd_name)
            and (
                any(cmd_name.startswith(p) for p in _URL_PREFIXES)
                or (
                    len(cmd_name) == 11
                    and all(c in _VIDEO_ID_CHARS for c in cmd_name)
                )
            )
        ):
            ctx.ensure_object(dict)
            ctx.obj["url"] = cmd_name
            return self.commands.get("extract")
        return super().get_command(ctx, cmd_name)


@click.group(cls=YTXGroup, invoke_without_command=True)
@click.version_option(__version__, "--version")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """YTX: Convert YouTube videos, playlists, and channels into structured transcript datasets."""
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None and "url" not in ctx.obj:
        click.echo(ctx.get_help())


@cli.command("extract", hidden=True)
@click.argument("url", required=False)
@click.option("--output", "-o", default=DEFAULT_OUTPUT_DIR, help="Output directory path")
@click.option(
    "--format", "-f", "formats", default="md,json",
    help="Output format(s), comma-separated",
)
@click.option(
    "--language", "-l", default=None,
    help="Preferred transcript language (e.g., en, de, fr)",
)
@click.option(
    "--transcribe-missing", is_flag=True,
    help="Transcribe locally when captions are unavailable",
)
@click.option(
    "--keep-audio", is_flag=True,
    help="Keep downloaded audio files after transcription",
)
@click.option("--no-timestamps", is_flag=True, help="Exclude timestamps from output")
@click.option(
    "--latest", "-n", default=None, type=int,
    help="Process only the N most recent videos",
)
@click.option("--after", default=None, help="Videos published after date (YYYY-MM-DD)")
@click.option("--before", default=None, help="Videos published before date (YYYY-MM-DD)")
@click.option("--channel", "channel_contains", help="Only videos whose channel contains this text")
@click.option("--title", "title_contains", help="Only videos whose title contains this text")
@click.option("--min-duration", type=float, help="Only videos at least this many seconds long")
@click.option("--max-duration", type=float, help="Only videos at most this many seconds long")
@click.option("--skip-existing", is_flag=True, help="Skip previously processed videos")
@click.option(
    "--model", "-m", default=None,
    help=f"Transcription model size (default: {DEFAULT_MODEL_SIZE})",
)
@click.option("--combine-jsonl", is_flag=True, help="Also create JSONL dataset file")
@click.option(
    "--combine", is_flag=True, hidden=True,
    help="Deprecated: combined Markdown is now automatic. Use --combine-jsonl for JSONL.",
)
@click.option("--delay", default=DEFAULT_DELAY, type=float, help="Delay between requests")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option(
    "--output-layout", default="flat", type=click.Choice(["flat", "structured"]),
    help="Output layout: flat (files in source folder) or structured (per-video directories)",
)
@click.option(
    "--youtube-auth", default="auto", type=click.Choice(["auto", "firefox"]),
    help="YouTube access: auto (try without auth first) or firefox (use Firefox session)",
)
@click.pass_context
def extract_cmd(
    ctx: click.Context,
    url: str | None,
    output: str,
    formats: str,
    language: str | None,
    transcribe_missing: bool,
    keep_audio: bool,
    no_timestamps: bool,
    latest: int | None,
    after: str | None,
    before: str | None,
    channel_contains: str | None,
    title_contains: str | None,
    min_duration: float | None,
    max_duration: float | None,
    skip_existing: bool,
    model: str | None,
    combine_jsonl: bool,
    combine: bool,
    delay: float,
    verbose: bool,
    output_layout: str,
    youtube_auth: str,
) -> None:
    """Extract transcripts from YouTube videos, playlists, and channels."""
    if url is None:
        url = (ctx.obj or {}).get("url")
    if url is None:
        click.echo(ctx.get_help())
        raise SystemExit(0)

    # Handle --combine deprecation
    if combine:
        console.print(
            "[yellow]--combine is deprecated. Combined Markdown is now "
            "generated automatically. Use --combine-jsonl to also "
            "generate JSONL.[/yellow]"
        )
        combine_jsonl = True

    _run_extraction(
        url=url,
        output=output,
        formats=formats,
        language=language,
        transcribe_missing=transcribe_missing,
        keep_audio=keep_audio,
        timestamps=not no_timestamps,
        latest=latest,
        after=after,
        before=before,
        channel_contains=channel_contains,
        title_contains=title_contains,
        min_duration=min_duration,
        max_duration=max_duration,
        skip_existing=skip_existing,
        model=model,
        combine_jsonl=combine_jsonl,
        delay=delay,
        verbose=verbose,
        output_layout=output_layout,
        youtube_auth=youtube_auth,
    )


@cli.command("web")
@click.option(
    "--host",
    default="127.0.0.1",
    type=click.Choice(["127.0.0.1", "localhost"]),
    help="Local host to bind to (default: 127.0.0.1)",
)
@click.option("--port", "-p", default=8000, type=int, help="Port to listen on")
@click.option("--no-browser", is_flag=True, help="Do not open browser automatically")
def web_cmd(host: str, port: int, no_browser: bool) -> None:
    """Launch the YTX web interface."""
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        console.print(
            "[red]YTX Web support is not installed.[/red]\n\n"
            "Install it with:\n\n"
            '  pip install "ytx[web]"'
        )
        raise SystemExit(2) from None

    console.print("[bold]Starting YTX Web[/bold]")
    console.print(f"http://{host}:{port}")
    console.print()

    if not no_browser:
        console.print("Opening browser...")
        webbrowser.open(f"http://{host}:{port}")

    console.print("Press Ctrl+C to stop.")
    console.print()

    from ytx.web.app import app as fastapi_app

    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


@cli.command("search")
@click.argument("query")
@click.option("--output", "output_dir", default=DEFAULT_OUTPUT_DIR, help="Folder to search")
def search_cmd(query: str, output_dir: str) -> None:
    """Search saved JSON transcripts and show matching timestamps."""
    needle = query.casefold()
    matches = 0
    for path in Path(output_dir).rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        video = data.get("video", {})
        for segment in data.get("transcript", {}).get("segments", []):
            text = str(segment.get("text", ""))
            if needle in text.casefold():
                timestamp = float(segment.get("start", 0))
                console.print(
                    f"[bold]{video.get('title', path.stem)}[/bold] "
                    f"[{timestamp:.1f}s] {text}\n{video.get('url', '')}"
                )
                matches += 1
    if matches == 0:
        console.print("No matches found.")


def _run_extraction(
    url: str,
    output: str = DEFAULT_OUTPUT_DIR,
    formats: str = "md,json",
    language: str | None = None,
    transcribe_missing: bool = False,
    keep_audio: bool = False,
    timestamps: bool = True,
    latest: int | None = None,
    after: str | None = None,
    before: str | None = None,
    channel_contains: str | None = None,
    title_contains: str | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    skip_existing: bool = False,
    model: str | None = None,
    combine_jsonl: bool = False,
    delay: float = DEFAULT_DELAY,
    verbose: bool = False,
    output_layout: str = "flat",
    youtube_auth: str = "auto",
) -> None:
    """Run the extraction pipeline."""
    format_list = [f.strip().lower() for f in formats.split(",")]
    valid_formats = {"txt", "md", "json", "srt"}
    for fmt in format_list:
        if fmt not in valid_formats:
            valid = ", ".join(sorted(valid_formats))
            console.print(f"[red]Invalid format: {fmt}. Valid: {valid}[/red]")
            raise SystemExit(2)

    after_dt = _parse_date(after, "--after") if after else None
    before_dt = _parse_date(before, "--before") if before else None

    _pipeline_ref: list[Pipeline | None] = [None]

    def _handle_sigint(sig: int, frame: object) -> None:
        console.print("\n[yellow]Interrupted. Finishing current video and saving...[/yellow]")
        if _pipeline_ref[0]:
            _pipeline_ref[0].cancel()
        # Don't call sys.exit() - let the pipeline finish writing combined.md
        # The pipeline will check _cancelled and stop after the current video

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        pipeline = Pipeline(
            output_dir=output,
            formats=format_list,
            language=language,
            transcribe_missing=transcribe_missing,
            keep_audio=keep_audio,
            include_timestamps=timestamps,
            skip_existing=skip_existing,
            model_size=model,
            combine_jsonl=combine_jsonl,
            after=after_dt,
            before=before_dt,
            channel_contains=channel_contains,
            title_contains=title_contains,
            min_duration=min_duration,
            max_duration=max_duration,
            latest=latest,
            delay=delay,
            verbose=verbose,
            output_layout=OutputLayout(output_layout),
            youtube_auth=YouTubeAuthMode(youtube_auth),
        )
        _pipeline_ref[0] = pipeline

        summary = pipeline.run(url)
        pipeline.print_summary()

        if summary.failed > 0 and summary.failed == summary.total_discovered:
            raise SystemExit(1)
        elif summary.failed > 0:
            raise SystemExit(3)

    except SystemExit:
        raise
    except URLError as e:
        console.print(f"[red]URL error: {e}[/red]")
        raise SystemExit(2) from e
    except TranscriptionDependencyError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(2) from e
    except YTXError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        if verbose:
            console.print_exception()
        raise SystemExit(1) from e


def _parse_date(date_str: str, option_name: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        msg = f"Invalid date for {option_name}: {date_str}. Use YYYY-MM-DD."
        console.print(f"[red]{msg}[/red]")
        raise SystemExit(2) from None


def main() -> None:
    """Entry point for the CLI."""
    cli(standalone_mode=True)


if __name__ == "__main__":
    main()
