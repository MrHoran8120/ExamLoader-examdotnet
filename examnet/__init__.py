__all__ = ["ExamNetAutomator"]


def __getattr__(name):
    if name == "ExamNetAutomator":
        from .automator import ExamNetAutomator

        return ExamNetAutomator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
