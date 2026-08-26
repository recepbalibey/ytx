"""Privacy-safe browser detection for YouTube authentication.

Detects which supported browsers are installed locally WITHOUT accessing
any browser data (cookies, history, profiles, etc.).

Only checks for application presence using known safe paths.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Browsers supported by yt-dlp cookiesfrombrowser
# Source: yt_dlp.cookies.SUPPORTED_BROWSERS
YT_DLP_SUPPORTED_BROWSERS = frozenset({
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
})

# Display names for supported browsers
BROWSER_DISPLAY_NAMES: dict[str, str] = {
    "brave": "Brave",
    "chrome": "Chrome",
    "chromium": "Chromium",
    "edge": "Edge",
    "firefox": "Firefox",
    "opera": "Opera",
    "safari": "Safari",
    "vivaldi": "Vivaldi",
    "whale": "Whale",
}

# Browsers we actively check for (commonly used subset)
# We only expose browsers that are both installed AND supported by yt-dlp
_BROWSERS_TO_CHECK = ["firefox", "brave", "safari", "chrome", "edge"]


@dataclass(frozen=True)
class DetectedBrowser:
    """A detected browser that is both installed and yt-dlp supported."""

    id: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _check_app_bundle(bundle_name: str) -> bool:
    """Check if a macOS .app bundle exists in /Applications."""
    app_path = f"/Applications/{bundle_name}"
    return os.path.isdir(app_path)


def _check_command_exists(command: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil.which(command) is not None


def _check_linux_desktop_entry(desktop_file: str) -> bool:
    """Check if a Linux .desktop file exists."""
    paths = [
        f"/usr/share/applications/{desktop_file}",
        f"/usr/local/share/applications/{desktop_file}",
    ]
    home = os.path.expanduser("~")
    paths.append(f"{home}/.local/share/applications/{desktop_file}")
    return any(os.path.exists(p) for p in paths)


def _detect_firefox() -> bool:
    """Detect if Firefox is installed."""
    if _is_macos():
        return _check_app_bundle("Firefox.app")
    if _is_linux():
        return (
            _check_command_exists("firefox")
            or _check_linux_desktop_entry("firefox.desktop")
        )
    if _is_windows():
        # Check common Windows paths
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        paths = [
            os.path.join(program_files, "Mozilla Firefox", "firefox.exe"),
            os.path.join(program_files_x86, "Mozilla Firefox", "firefox.exe"),
        ]
        return any(os.path.exists(p) for p in paths)
    return False


def _detect_brave() -> bool:
    """Detect if Brave Browser is installed."""
    if _is_macos():
        return _check_app_bundle("Brave Browser.app")
    if _is_linux():
        return (
            _check_command_exists("brave-browser")
            or _check_command_exists("brave")
            or _check_linux_desktop_entry("brave-browser.desktop")
        )
    if _is_windows():
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LOCALAPPDATA", "")
        brave_path = os.path.join(
            "BraveSoftware", "Brave-Browser", "Application", "brave.exe"
        )
        paths = [
            os.path.join(program_files, brave_path),
            os.path.join(program_files_x86, brave_path),
            os.path.join(local_app, brave_path),
        ]
        return any(os.path.exists(p) for p in paths)
    return False


def _detect_safari() -> bool:
    """Detect if Safari is installed (macOS only)."""
    if _is_macos():
        return _check_app_bundle("Safari.app")
    return False


def _detect_chrome() -> bool:
    """Detect if Google Chrome is installed."""
    if _is_macos():
        return _check_app_bundle("Google Chrome.app")
    if _is_linux():
        return (
            _check_command_exists("google-chrome")
            or _check_command_exists("google-chrome-stable")
            or _check_linux_desktop_entry("google-chrome.desktop")
        )
    if _is_windows():
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LOCALAPPDATA", "")
        chrome_path = os.path.join("Google", "Chrome", "Application", "chrome.exe")
        paths = [
            os.path.join(program_files, chrome_path),
            os.path.join(program_files_x86, chrome_path),
            os.path.join(local_app, chrome_path),
        ]
        return any(os.path.exists(p) for p in paths)
    return False


def _detect_edge() -> bool:
    """Detect if Microsoft Edge is installed."""
    if _is_macos():
        return _check_app_bundle("Microsoft Edge.app")
    if _is_linux():
        return (
            _check_command_exists("microsoft-edge")
            or _check_command_exists("microsoft-edge-stable")
            or _check_linux_desktop_entry("microsoft-edge.desktop")
        )
    if _is_windows():
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        edge_path = os.path.join("Microsoft", "Edge", "Application", "msedge.exe")
        paths = [
            os.path.join(program_files, edge_path),
            os.path.join(program_files_x86, edge_path),
        ]
        return any(os.path.exists(p) for p in paths)
    return False


# Map browser IDs to detection functions
_DETECTORS: dict[str, callable] = {
    "firefox": _detect_firefox,
    "brave": _detect_brave,
    "safari": _detect_safari,
    "chrome": _detect_chrome,
    "edge": _detect_edge,
}


def detect_supported_browsers() -> list[DetectedBrowser]:
    """Detect browsers that are both installed locally AND supported by yt-dlp.

    Returns a list of DetectedBrowser with id and display name.
    Only checks for application presence - never accesses cookies, profiles,
    or any browser data.

    The order reflects typical user preference (Firefox first as most privacy-friendly).
    """
    detected = []

    for browser_id in _BROWSERS_TO_CHECK:
        # Must be supported by yt-dlp
        if browser_id not in YT_DLP_SUPPORTED_BROWSERS:
            continue

        # Check if installed
        detector = _DETECTORS.get(browser_id)
        if detector and detector():
            display_name = BROWSER_DISPLAY_NAMES.get(browser_id, browser_id.title())
            detected.append(DetectedBrowser(id=browser_id, name=display_name))

    return detected
