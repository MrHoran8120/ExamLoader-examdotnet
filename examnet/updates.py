"""Check GitHub Releases for a newer version.

Exam.net page changes break older versions, so the GUI tells the user when a fix is out.
Only published (non-pre-release) releases count: GitHub's /releases/latest skips pre-releases.
"""

import json
import re
from urllib.request import Request, urlopen

from . import PROJECT_URL, __version__

LATEST_RELEASE_API = PROJECT_URL.replace("https://github.com/", "https://api.github.com/repos/") + "/releases/latest"


def parse_version(text):
    """'v1.2.3' or '1.2' -> (1, 2, 3) / (1, 2, 0). Returns None if it isn't a version number."""
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or "").strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def check_for_update(current_version=__version__, timeout=5.0):
    """Return (latest_version, release_url) if GitHub has a newer release, else None.

    Never raises: no network, no releases yet, or an unexpected reply all count as "no update".
    """
    current = parse_version(current_version)
    try:
        request = Request(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"ExamLoader/{current_version}"},
        )
        with urlopen(request, timeout=timeout) as response:
            release = json.load(response)
        tag = release.get("tag_name", "")
        latest = parse_version(tag)
        if current and latest and latest > current:
            return tag.lstrip("v"), release.get("html_url") or f"{PROJECT_URL}/releases/latest"
    except Exception:
        pass
    return None
