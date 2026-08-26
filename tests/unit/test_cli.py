"""Tests for the command line interface."""

from click.testing import CliRunner

from ytx.cli import cli


def test_video_url_help_shows_extract_options():
    """A direct video command must still provide help without starting work."""
    runner = CliRunner()

    result = runner.invoke(cli, ["dQw4w9WgXcQ", "--help"])

    assert result.exit_code == 0
    assert "Extract transcripts" in result.output
    assert "--transcribe-missing" in result.output
