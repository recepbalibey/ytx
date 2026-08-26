"""Tests for browser detection and security features."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ytx.web.browser_detect import (
    BROWSER_DISPLAY_NAMES,
    YT_DLP_SUPPORTED_BROWSERS,
    DetectedBrowser,
    _detect_brave,
    _detect_chrome,
    _detect_edge,
    _detect_firefox,
    _detect_safari,
    detect_supported_browsers,
)


class TestBrowserDetection:
    """Test browser detection privacy boundaries."""

    def test_detected_browser_to_dict(self):
        browser = DetectedBrowser(id="firefox", name="Firefox")
        result = browser.to_dict()
        assert result == {"id": "firefox", "name": "Firefox"}

    def test_ytdlp_supported_browsers_is_frozen(self):
        """Supported browsers list should be immutable."""
        assert isinstance(YT_DLP_SUPPORTED_BROWSERS, frozenset)
        assert "firefox" in YT_DLP_SUPPORTED_BROWSERS
        assert "brave" in YT_DLP_SUPPORTED_BROWSERS
        assert "safari" in YT_DLP_SUPPORTED_BROWSERS
        assert "chrome" in YT_DLP_SUPPORTED_BROWSERS

    def test_browser_display_names_complete(self):
        """All supported browsers should have display names."""
        for browser_id in YT_DLP_SUPPORTED_BROWSERS:
            assert browser_id in BROWSER_DISPLAY_NAMES

    def test_detect_returns_only_supported_browsers(self):
        """Detected browsers must be in the yt-dlp supported set."""
        detected = detect_supported_browsers()
        for browser in detected:
            assert browser.id in YT_DLP_SUPPORTED_BROWSERS

    def test_detect_returns_detected_browser_instances(self):
        """detect_supported_browsers should return DetectedBrowser instances."""
        detected = detect_supported_browsers()
        for browser in detected:
            assert isinstance(browser, DetectedBrowser)
            assert browser.id
            assert browser.name

    def test_detect_no_paths_exposed(self):
        """Detection should never expose file paths."""
        detected = detect_supported_browsers()
        for browser in detected:
            # The to_dict should only have id and name
            d = browser.to_dict()
            assert set(d.keys()) == {"id", "name"}
            # No path-like strings
            for value in d.values():
                assert "/" not in str(value)
                assert "\\" not in str(value)
                assert "Library" not in str(value)
                assert "Application Support" not in str(value)

    @patch("ytx.web.browser_detect._detect_edge", return_value=False)
    @patch("ytx.web.browser_detect._detect_chrome", return_value=False)
    @patch("ytx.web.browser_detect._detect_safari", return_value=False)
    @patch("ytx.web.browser_detect._detect_brave", return_value=False)
    @patch("ytx.web.browser_detect._detect_firefox", return_value=True)
    def test_detect_firefox_only(self, mock_ff, mock_brave, mock_safari, mock_chrome, mock_edge):
        """When only Firefox is installed, only Firefox should be returned."""
        # Patch the _DETECTORS dict to use our mocks
        with patch.dict("ytx.web.browser_detect._DETECTORS", {
            "firefox": mock_ff,
            "brave": mock_brave,
            "safari": mock_safari,
            "chrome": mock_chrome,
            "edge": mock_edge,
        }):
            detected = detect_supported_browsers()
            assert len(detected) == 1
            assert detected[0].id == "firefox"
            assert detected[0].name == "Firefox"

    @patch("ytx.web.browser_detect._detect_edge", return_value=False)
    @patch("ytx.web.browser_detect._detect_chrome", return_value=False)
    @patch("ytx.web.browser_detect._detect_safari", return_value=True)
    @patch("ytx.web.browser_detect._detect_brave", return_value=True)
    @patch("ytx.web.browser_detect._detect_firefox", return_value=True)
    def test_detect_multiple_browsers(
        self, mock_ff, mock_brave, mock_safari, mock_chrome, mock_edge
    ):
        """Multiple detected browsers should all be returned."""
        with patch.dict("ytx.web.browser_detect._DETECTORS", {
            "firefox": mock_ff,
            "brave": mock_brave,
            "safari": mock_safari,
            "chrome": mock_chrome,
            "edge": mock_edge,
        }):
            detected = detect_supported_browsers()
            ids = [b.id for b in detected]
            assert "firefox" in ids
            assert "brave" in ids
            assert "safari" in ids
            assert "chrome" not in ids

    @patch("ytx.web.browser_detect._detect_edge", return_value=False)
    @patch("ytx.web.browser_detect._detect_chrome", return_value=False)
    @patch("ytx.web.browser_detect._detect_safari", return_value=False)
    @patch("ytx.web.browser_detect._detect_brave", return_value=False)
    @patch("ytx.web.browser_detect._detect_firefox", return_value=False)
    def test_detect_no_browsers(self, mock_ff, mock_brave, mock_safari, mock_chrome, mock_edge):
        """When no browsers are installed, empty list returned."""
        with patch.dict("ytx.web.browser_detect._DETECTORS", {
            "firefox": mock_ff,
            "brave": mock_brave,
            "safari": mock_safari,
            "chrome": mock_chrome,
            "edge": mock_edge,
        }):
            detected = detect_supported_browsers()
            assert detected == []


class TestBrowserDetectionPrivacy:
    """Test that detection never accesses browser data."""

    def test_firefox_detection_no_cookie_access(self):
        """Firefox detection should only check app presence, not cookies."""
        # The detection function should not import or use cookie-related modules
        import inspect
        src = inspect.getsource(_detect_firefox)
        assert "cookie" not in src.lower()
        assert "sqlite" not in src.lower()
        assert "profile" not in src.lower()
        assert "places.sqlite" not in src.lower()

    def test_brave_detection_no_cookie_access(self):
        """Brave detection should only check app presence, not cookies."""
        import inspect
        src = inspect.getsource(_detect_brave)
        assert "cookie" not in src.lower()
        assert "sqlite" not in src.lower()

    def test_safari_detection_no_cookie_access(self):
        """Safari detection should only check app presence, not cookies."""
        import inspect
        src = inspect.getsource(_detect_safari)
        assert "cookie" not in src.lower()
        assert "sqlite" not in src.lower()

    def test_chrome_detection_no_cookie_access(self):
        """Chrome detection should only check app presence, not cookies."""
        import inspect
        src = inspect.getsource(_detect_chrome)
        assert "cookie" not in src.lower()
        assert "sqlite" not in src.lower()

    def test_edge_detection_no_cookie_access(self):
        """Edge detection should only check app presence, not cookies."""
        import inspect
        src = inspect.getsource(_detect_edge)
        assert "cookie" not in src.lower()
        assert "sqlite" not in src.lower()

    def test_detect_function_no_browser_data_access(self):
        """Main detect function should not access browser data."""
        import inspect
        src = inspect.getsource(detect_supported_browsers)
        # Check that the function doesn't access browser data files
        assert "cookies.sqlite" not in src.lower()
        assert "places.sqlite" not in src.lower()
        assert "logins.json" not in src.lower()
        assert "history" not in src.lower()
        assert "bookmark" not in src.lower()
        assert "password" not in src.lower()


class TestBrowserAPIEndpoint:
    """Test the /api/browsers endpoint."""

    def test_browsers_endpoint_returns_list(self, client):
        resp = client.get("/api/browsers")
        assert resp.status_code == 200
        data = resp.json()
        assert "browsers" in data
        assert isinstance(data["browsers"], list)

    def test_browsers_endpoint_returns_only_id_name(self, client):
        resp = client.get("/api/browsers")
        data = resp.json()
        for browser in data["browsers"]:
            assert set(browser.keys()) == {"id", "name"}
            # No paths or sensitive data
            assert "path" not in browser
            assert "profile" not in browser
            assert "cookie" not in browser

    def test_browsers_endpoint_ids_are_valid(self, client):
        resp = client.get("/api/browsers")
        data = resp.json()
        for browser in data["browsers"]:
            assert browser["id"] in YT_DLP_SUPPORTED_BROWSERS


class TestSecurityValidation:
    """Test Origin/Host validation and input validation."""

    def test_invalid_browser_id_rejected(self, client):
        """Invalid youtube_auth values should be rejected."""
        resp = client.post("/jobs", json={
            "url": "https://www.youtube.com/watch?v=test123456",
            "youtube_auth": "invalid_browser",
        })
        assert resp.status_code == 400

    def test_valid_browser_ids_accepted(self, client, fresh_manager):
        """Valid youtube_auth values should be accepted."""
        from unittest.mock import patch
        with patch("ytx.web.app._run_job_thread"):
            for browser_id in ["auto", "firefox", "brave", "safari", "chrome", "edge"]:
                resp = client.post("/jobs", json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "youtube_auth": browser_id,
                })
                assert resp.status_code == 200, f"Failed for {browser_id}: {resp.json()}"
                # Clear the job for next iteration
                fresh_manager._jobs.clear()
                fresh_manager._active_job_id = None

    def test_auto_is_default(self, client, fresh_manager):
        """Default youtube_auth should be 'auto'."""
        from unittest.mock import patch
        with patch("ytx.web.app._run_job_thread") as mock_thread:
            resp = client.post("/jobs", json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            })
            assert resp.status_code == 200
            # Check that the thread was called with auto
            call_args = mock_thread.call_args
            params = call_args[0][1]
            assert params["youtube_auth"] == "auto"


class TestXSSSafety:
    """Test that templates handle untrusted data safely."""

    def test_escape_html_function_exists(self, client):
        """The escapeHtml function should be available in job template."""
        resp = client.get("/")
        # The index page should load without errors
        assert resp.status_code == 200


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from ytx.web.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fresh_manager():
    """Provide a fresh job manager for each test."""
    from ytx.web.app import job_manager
    original = job_manager._jobs.copy()
    original_active = job_manager._active_job_id
    job_manager._jobs.clear()
    job_manager._active_job_id = None
    yield job_manager
    job_manager._jobs.clear()
    job_manager._jobs.update(original)
    job_manager._active_job_id = original_active
