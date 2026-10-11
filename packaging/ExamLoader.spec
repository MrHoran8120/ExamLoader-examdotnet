# PyInstaller build for the ExamLoader for Exam.net GUI. Run via build.ps1.
# One-folder, windowed build. Playwright's own hook bundles its driver (node.exe);
# no browsers are bundled because the app drives the installed Chrome or Edge.
import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

with open(os.path.join(ROOT, "examnet", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
version_tuple = tuple(int(part) for part in (VERSION.split(".") + ["0"] * 4)[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("ProductName", "ExamLoader for Exam.net"),
                        StringStruct("FileDescription", "ExamLoader for Exam.net"),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("ProductVersion", VERSION),
                        StringStruct("OriginalFilename", "ExamLoader.exe"),
                        StringStruct("LegalCopyright", "MIT License. Not affiliated with Exam.net."),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    [os.path.join(SPECPATH, "examloader_gui.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "sample_questions.json"), "."),
        (os.path.join(ROOT, "questions_prompt_template.json"), "."),
        (os.path.join(ROOT, "LICENSE"), "."),
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ExamLoader",
    console=False,
    version=version_info,
)

coll = COLLECT(exe, a.binaries, a.datas, name="ExamLoader")
