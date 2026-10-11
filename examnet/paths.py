"""Per-user folders for everything the app writes (logs, diagnostics, browser profile, etc.).

Nothing is written next to the code, so the app works the same from a source checkout
and from an installed copy (e.g. under %LOCALAPPDATA%\\Programs, or a read-only folder).
"""

import os
import sys

APP_DIR_NAME = "ExamLoader"


def app_data_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_DIR_NAME)


def _subdir(*parts):
    path = os.path.join(app_data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def logs_dir():
    return _subdir("logs")


def diagnostics_dir():
    return _subdir("diagnostics")


def browser_profile_dir(browser_name):
    """Separate profile per browser: Chrome and Edge profiles are not interchangeable."""
    return _subdir(f"browser-profile-{browser_name.lower()}")


def data_file(name):
    """Path for an app-written data file such as failed_questions.json."""
    return os.path.join(_subdir(), name)


def documents_dir():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return docs if os.path.isdir(docs) else os.path.expanduser("~")
