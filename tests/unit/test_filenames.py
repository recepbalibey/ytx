"""Tests for filename sanitization."""

from ytx.utils.filenames import safe_video_dirname, sanitize_filename


class TestSanitizeFilename:
    def test_basic_name(self):
        assert sanitize_filename("Hello World") == "Hello World"

    def test_unsafe_chars(self):
        result = sanitize_filename('File: "Name" <test>')
        assert ":" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result

    def test_slashes(self):
        result = sanitize_filename("path/to/file")
        assert "/" not in result
        assert chr(92) not in result

    def test_unicode(self):
        result = sanitize_filename("日本語テスト")
        assert len(result) > 0

    def test_long_name(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_empty_name(self):
        assert sanitize_filename("") == "untitled"
        assert sanitize_filename("...") == "untitled"

    def test_leading_trailing_dots(self):
        result = sanitize_filename(".hidden.")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_windows_reserved(self):
        result = sanitize_filename("CON")
        assert result == "_CON"

    def test_multiple_dashes_collapsed(self):
        result = sanitize_filename("a---b")
        assert "---" not in result


class TestSafeVideoDirname:
    def test_basic(self):
        result = safe_video_dirname("abc123", "Hello World")
        assert "abc123" in result
        assert "Hello" in result

    def test_special_chars(self):
        result = safe_video_dirname("vid123", 'Test: "Video" <Title>')
        assert "vid123" in result
        assert ":" not in result.split("_")[0]
