# Changelog

Version numbers are MAJOR.MINOR.PATCH:

* **PATCH** (1.0.1): fixes only, most often a repair after Exam.net changes its pages.
* **MINOR** (1.1.0): new features such as a new question type. Existing question files still work.
* **MAJOR** (2.0.0): existing question files (JSON) would need changing.

## 1.0.0 (2026-10-11)

First public release.

* Windows installer: installs for your account only (no administrator password), with a Start menu shortcut
  and an uninstaller.
* Tells you when a newer version is available, with a link to download it.

## 0.9.0 (2026-10-11)

First packaged build, for testing before the 1.0.0 release.

* Windows app (`ExamLoader.exe`) that runs without Python installed.
* Uses Google Chrome, or Microsoft Edge if Chrome isn't installed.
* Logs, diagnostics and the browser profile are kept in `%LOCALAPPDATA%\ExamLoader`.
* About window showing the version and when it was last checked against Exam.net; every log file starts with
  the version.
* Question types: multiple choice, list match, fill the gaps (with an optional word bank), long answer and
  Python program. Code in questions keeps its formatting.
