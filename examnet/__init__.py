# Release details. Bump __version__ for every release (see "Releasing" in readme.md) and
# update LAST_VERIFIED whenever a full live run against Exam.net has passed.
__version__ = "1.0.0"
LAST_VERIFIED = "2026-10-11"
APP_NAME = "ExamLoader for Exam.net"
PROJECT_URL = "https://github.com/MrHoran8120/ExamLoader-examdotnet"
DOWNLOAD_URL = f"{PROJECT_URL}/releases"

__all__ = ["ExamNetAutomator", "__version__", "LAST_VERIFIED", "APP_NAME", "PROJECT_URL", "DOWNLOAD_URL"]


def __getattr__(name):
    if name == "ExamNetAutomator":
        from .automator import ExamNetAutomator

        return ExamNetAutomator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
