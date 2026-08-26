"""Tests for language fallback behavior."""

from ytx.transcripts.captions import _fetched_to_transcript


class TestLanguageFallbackMetadata:
    def test_requested_language_preserved(self):
        """When requested language matches, requested_language is set."""
        # Simulate a fetched transcript
        class FakeSnippet:
            def __init__(self):
                self.start = 0.0
                self.duration = 1.0
                self.text = "hello"

        class FakeTranscript:
            def __init__(self):
                self.language_code = "en"
                self.language = "English"
                self.is_generated = False

            def __iter__(self):
                return iter([FakeSnippet()])

        result = _fetched_to_transcript(FakeTranscript(), requested_language="en")
        assert result.language == "en"
        assert result.requested_language == "en"

    def test_fallback_language_recorded(self):
        """When fallback occurs, requested_language differs from language."""
        class FakeSnippet:
            def __init__(self):
                self.start = 0.0
                self.duration = 1.0
                self.text = "hallo"

        class FakeTranscript:
            def __init__(self):
                self.language_code = "de"
                self.language = "German"
                self.is_generated = False

            def __iter__(self):
                return iter([FakeSnippet()])

        result = _fetched_to_transcript(FakeTranscript(), requested_language="fr")
        assert result.language == "de"
        assert result.requested_language == "fr"
        assert result.language != result.requested_language

    def test_no_requested_language(self):
        """When no language was requested, requested_language is None."""
        class FakeSnippet:
            def __init__(self):
                self.start = 0.0
                self.duration = 1.0
                self.text = "hello"

        class FakeTranscript:
            def __init__(self):
                self.language_code = "en"
                self.language = "English"
                self.is_generated = False

            def __iter__(self):
                return iter([FakeSnippet()])

        result = _fetched_to_transcript(FakeTranscript())
        assert result.requested_language is None
