#!/bin/bash
# Builds dist/ExamLoader.app and dist/ExamLoader-examdotnet-mac-<version>.dmg with PyInstaller.
# Usage: ./build_mac.sh             (add --skip-tests to skip the unit tests)
# Needs Python 3.10+ with Tk 8.6 or newer: Apple's built-in Python 3.9 (Tk 8.5) draws blank windows.
# With uv installed, the venv is created from uv's Python 3.12.
set -euo pipefail

cd "$(dirname "$0")"
VENV_PY=".venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "Creating virtual environment in .venv ..."
    if command -v uv >/dev/null 2>&1; then
        uv venv --python 3.12 .venv
    else
        python3 -m venv .venv
    fi
fi

echo "Installing build dependencies ..."
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
if command -v uv >/dev/null 2>&1; then
    uv pip install -q --python "$VENV_PY" -r requirements-build.txt
else
    "$VENV_PY" -m pip install -q -r requirements-build.txt
fi

if [ "${1:-}" != "--skip-tests" ]; then
    echo "Running unit tests ..."
    # test_browser's Windows install-path test only passes on Windows.
    "$VENV_PY" -m unittest test_cli test_automator test_updates
fi

VERSION=$("$VENV_PY" -c "import examnet; print(examnet.__version__)")
echo "Building ExamLoader $VERSION ..."
"$VENV_PY" -m PyInstaller --noconfirm --clean --log-level WARN \
    --distpath dist --workpath build packaging/ExamLoader.spec

APP="dist/ExamLoader.app"
# Only the .app is wanted; PyInstaller also leaves the one-folder build next to it.
rm -rf dist/ExamLoader

DMG="dist/ExamLoader-examdotnet-mac-$VERSION.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "ExamLoader $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

echo "Built $APP ($(du -sh "$APP" | cut -f1))"
echo "Built $DMG ($(du -sh "$DMG" | cut -f1))"
