import os
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from .paths import browser_profile_dir

DEFAULT_BROWSER_URL = "http://127.0.0.1:9222"
EXAM_NET_URL = "https://exam.net"

# Tried in this order; Edge is the fallback because every Windows PC has it.
_WINDOWS_BROWSERS = [
    ("Chrome", "chrome.exe", r"Google\Chrome\Application\chrome.exe"),
    ("Edge", "msedge.exe", r"Microsoft\Edge\Application\msedge.exe"),
]
_MAC_BROWSERS = [
    ("Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
]
_LINUX_BROWSERS = [
    ("Chrome", ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")),
    ("Edge", ("microsoft-edge", "microsoft-edge-stable")),
]

BROWSER_NOT_FOUND_MESSAGE = (
    "Could not find Google Chrome or Microsoft Edge on this computer.\n\n"
    "Install Google Chrome (https://www.google.com/chrome/) and try again."
)


class BrowserNotFoundError(RuntimeError):
    pass


def cdp_port(browser_url=DEFAULT_BROWSER_URL):
    return urlparse(browser_url).port or 9222


def is_cdp_available(browser_url=DEFAULT_BROWSER_URL, timeout=1.0):
    """True when a browser with remote debugging is listening at browser_url."""
    try:
        with urlopen(f"{browser_url.rstrip('/')}/json/version", timeout=timeout) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def _registry_app_path(exe_name):
    """Look up an exe under 'App Paths', where Chrome and Edge register themselves (per-user or machine-wide)."""
    import winreg

    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        path = os.path.expandvars(str(value).strip().strip('"'))
        if os.path.isfile(path):
            return path
    return None


def _find_windows_browser(exe_name, relative_path):
    path = _registry_app_path(exe_name)
    if path:
        return path
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_var)
        if base:
            candidate = os.path.join(base, relative_path)
            if os.path.isfile(candidate):
                return candidate
    return None


def find_browser():
    """Return (name, executable) for Chrome, falling back to Edge. Raises BrowserNotFoundError."""
    if sys.platform.startswith("win"):
        for name, exe_name, relative_path in _WINDOWS_BROWSERS:
            path = _find_windows_browser(exe_name, relative_path)
            if path:
                return name, path
    elif sys.platform == "darwin":
        for name, path in _MAC_BROWSERS:
            if os.path.isfile(path):
                return name, path
    else:
        for name, commands in _LINUX_BROWSERS:
            for command in commands:
                path = shutil.which(command)
                if path:
                    return name, path
    raise BrowserNotFoundError(BROWSER_NOT_FOUND_MESSAGE)


def browser_launch_args(executable, browser_name, port=9222, start_url="about:blank"):
    return [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={browser_profile_dir(browser_name)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        start_url,
    ]


def launch_browser(browser_url=DEFAULT_BROWSER_URL, start_url="about:blank", logger=None, timeout=20, interval=0.5):
    """Start Chrome (or Edge) with remote debugging and wait until its debug port answers.

    Returns the browser name ("Chrome" or "Edge").
    """
    name, executable = find_browser()
    if logger:
        logger.info("Launching %s with remote debugging (%s)...", name, executable)
    try:
        subprocess.Popen(browser_launch_args(executable, name, cdp_port(browser_url), start_url))
    except Exception as e:
        if logger:
            logger.error("Error launching %s: %s", name, e)
        raise RuntimeError(f"Could not start {name}: {e}") from e

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_cdp_available(browser_url):
            return name
        time.sleep(interval)
    raise RuntimeError(
        f"{name} started but its remote-debugging port did not become available in time.\n\n"
        f"If {name} was already open with an ExamLoader window, close that window and try again."
    )
