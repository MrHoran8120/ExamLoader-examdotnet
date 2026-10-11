import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

DEFAULT_BROWSER_URL = "http://127.0.0.1:9222"
EXAM_NET_URL = "https://exam.net"


def cdp_port(browser_url=DEFAULT_BROWSER_URL):
    return urlparse(browser_url).port or 9222


def is_cdp_available(browser_url=DEFAULT_BROWSER_URL, timeout=1.0):
    """True when a Chrome with remote debugging is listening at browser_url."""
    try:
        with urlopen(f"{browser_url.rstrip('/')}/json/version", timeout=timeout) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def chrome_launch_args(port=9222, start_url="about:blank"):
    flags = [
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        start_url,
    ]
    if sys.platform.startswith("win"):
        return [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--user-data-dir=C:\\Temp\\chrome-debug-profile",
            *flags,
        ]
    if sys.platform.startswith("darwin"):
        return ["open", "-a", "Google Chrome", "--args", "--user-data-dir=/tmp/chrome-debug-profile", *flags]
    return ["google-chrome", "--user-data-dir=/tmp/chrome-debug-profile", *flags]


def launch_chrome(browser_url=DEFAULT_BROWSER_URL, start_url="about:blank", logger=None, timeout=20, interval=0.5):
    """Start Chrome with remote debugging and wait until its debug port answers."""
    if logger:
        logger.info("Launching Chrome in CDP mode...")
    try:
        subprocess.Popen(chrome_launch_args(cdp_port(browser_url), start_url))
    except Exception as e:
        if logger:
            logger.error("Error launching Chrome in CDP mode: %s", e)
        raise RuntimeError(f"Could not start Chrome: {e}") from e

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_cdp_available(browser_url):
            return
        time.sleep(interval)
    raise RuntimeError("Chrome started but its remote-debugging port did not become available in time.")
