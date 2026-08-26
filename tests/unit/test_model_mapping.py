"""Tests for centralized model mapping."""

from __future__ import annotations

from ytx.transcription.model_mapping import (
    DEFAULT_CLI_MODEL,
    DEFAULT_WEB_QUALITY,
    QUALITY_TO_MODEL,
    VALID_WHISPER_MODELS,
    resolve_model_size,
    resolve_web_model,
)


class TestResolveModelSize:
    """Test resolve_model_size (used by CLI and pipeline)."""

    def test_none_returns_cli_default(self):
        assert resolve_model_size(None) == DEFAULT_CLI_MODEL

    def test_fast_maps_to_tiny(self):
        assert resolve_model_size("fast") == "tiny"

    def test_balanced_maps_to_base(self):
        assert resolve_model_size("balanced") == "base"

    def test_best_maps_to_small(self):
        assert resolve_model_size("best") == "small"

    def test_direct_model_passthrough(self):
        assert resolve_model_size("base") == "base"
        assert resolve_model_size("small") == "small"
        assert resolve_model_size("medium") == "medium"
        assert resolve_model_size("large-v3") == "large-v3"

    def test_case_insensitive(self):
        assert resolve_model_size("Fast") == "tiny"
        assert resolve_model_size("BALANCED") == "base"
        assert resolve_model_size("Best") == "small"

    def test_whitespace_trimmed(self):
        assert resolve_model_size("  balanced  ") == "base"

    def test_unknown_passes_through(self):
        # Unknown values are passed through for faster-whisper to validate
        assert resolve_model_size("unknown-model") == "unknown-model"


class TestResolveWebModel:
    """Test resolve_web_model (used by web UI)."""

    def test_none_returns_balanced_default(self):
        """When no model specified (user left default), should return 'base'."""
        result = resolve_web_model(None)
        assert result == "base"
        assert result == QUALITY_TO_MODEL[DEFAULT_WEB_QUALITY]

    def test_fast_maps_to_tiny(self):
        assert resolve_web_model("fast") == "tiny"

    def test_balanced_maps_to_base(self):
        assert resolve_web_model("balanced") == "base"

    def test_best_maps_to_small(self):
        assert resolve_web_model("best") == "small"

    def test_direct_model_passthrough(self):
        assert resolve_web_model("base") == "base"
        assert resolve_web_model("small") == "small"


class TestMappingConsistency:
    """Verify mapping consistency and completeness."""

    def test_all_quality_names_map_to_valid_models(self):
        for quality, model in QUALITY_TO_MODEL.items():
            assert model in VALID_WHISPER_MODELS, (
                f"Quality '{quality}' maps to '{model}' which is not a valid whisper model"
            )

    def test_default_web_quality_is_in_mapping(self):
        assert DEFAULT_WEB_QUALITY in QUALITY_TO_MODEL

    def test_default_cli_model_is_valid(self):
        assert DEFAULT_CLI_MODEL in VALID_WHISPER_MODELS

    def test_balanced_never_reaches_whisper(self):
        """Critical: 'balanced' must NEVER be passed to faster-whisper."""
        resolved = resolve_model_size("balanced")
        assert resolved != "balanced"
        assert resolved in VALID_WHISPER_MODELS

    def test_fast_never_reaches_whisper(self):
        resolved = resolve_model_size("fast")
        assert resolved != "fast"
        assert resolved in VALID_WHISPER_MODELS

    def test_best_never_reaches_whisper(self):
        resolved = resolve_model_size("best")
        assert resolved != "best"
        assert resolved in VALID_WHISPER_MODELS

    def test_default_web_quality_resolves_to_base(self):
        """Default web quality 'balanced' should resolve to 'base'."""
        from ytx.transcription.model_mapping import resolve_web_model
        result = resolve_web_model(None)
        assert result == "base"

    def test_direct_model_names_still_work(self):
        """Direct CLI model names should still be supported."""
        assert resolve_model_size("tiny") == "tiny"
        assert resolve_model_size("base") == "base"
        assert resolve_model_size("small") == "small"
        assert resolve_model_size("medium") == "medium"
        assert resolve_model_size("large-v3") == "large-v3"
