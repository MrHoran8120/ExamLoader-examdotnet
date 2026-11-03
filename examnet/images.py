"""Images in questions: [[image:name]] markers, exam packages (.zip) and uploading through exam.net.

A question lists its images by name and places each one in its text with a marker:

    "question": "Look at the circuit.\n[[image:circuit]]\nWhich component is the input?",
    "images": {"circuit": {"file": "images/circuit.png", "alt": "A button wired to pin 2"}}

The questions are filled in as text first (markers included). Each marker is then replaced by putting
the cursor where it was and uploading the file through the editor's Insert Image button, which is the
same path a teacher's upload takes, so exam.net stores and serves the image itself.
"""

import os
import re
import shutil
import tempfile
import zipfile

from .question_html import QUESTION_CONTAINER

PACKAGE_FORMAT = "examloader/1"
QUESTIONS_FILE = "questions.json"
IMAGE_MARKER = re.compile(r"\[\[image:([^\]\r\n]*)\]\]")
IMAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# The file types exam.net's image upload accepts.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_WIDTH, MAX_WIDTH = 50, 1200
TEXT_KEYS = ("question", "question_text")
UPLOAD_TIMEOUT_MS = 60000


class PackageError(ValueError):
    pass


# ---------- packages ----------


def open_package(path):
    """Return (questions_json_path, base_dir, temp_dir) for a .json file or a .zip package.

    Image paths are resolved against base_dir. temp_dir is the folder a zip was unpacked into
    (None for a plain .json); remove it with close_package when the run is over.
    """
    if not path.lower().endswith(".zip"):
        return path, os.path.dirname(os.path.abspath(path)), None
    if not os.path.exists(path):
        raise FileNotFoundError(f"Questions file not found: {path}")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise PackageError(f"'{os.path.basename(path)}' is not a valid zip file.") from e

    temp_dir = tempfile.mkdtemp(prefix="examloader-")
    try:
        with archive:
            for member in archive.namelist():
                parts = member.replace("\\", "/").split("/")
                if member.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
                    raise PackageError(f"The zip contains an unsafe path: {member}")
            archive.extractall(temp_dir)
        json_path = _find_questions_json(temp_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return json_path, os.path.dirname(json_path), temp_dir


def close_package(temp_dir):
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _find_questions_json(root):
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__MACOSX"]
        found.extend(os.path.join(folder, f) for f in files if f.lower().endswith(".json"))
    named = [p for p in found if os.path.basename(p).lower() == QUESTIONS_FILE]
    # Prefer questions.json; a zip of a folder puts it one level down, which is fine.
    candidates = named or found
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PackageError(f"The zip does not contain {QUESTIONS_FILE}.")
    shallowest = min(candidates, key=lambda p: p.count(os.sep))
    if sum(1 for p in candidates if p.count(os.sep) == shallowest.count(os.sep)) == 1:
        return shallowest
    names = ", ".join(os.path.relpath(p, root).replace(os.sep, "/") for p in candidates)
    raise PackageError(f"The zip contains more than one questions file ({names}). Keep only {QUESTIONS_FILE}.")


# ---------- validation ----------


def question_text(question):
    for key in TEXT_KEYS:
        if isinstance(question.get(key), str):
            return question[key]
    return ""


def image_markers(text):
    return IMAGE_MARKER.findall(text or "")


def _strings_outside_text(value, path=""):
    """Yield (path, string) for every string in the question except its text and images."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if path == "" and key in TEXT_KEYS + ("images",):
                continue
            yield from _strings_outside_text(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _strings_outside_text(item, f"{path}[{i}]")


def _resolve_file(base_dir, file_value):
    """Absolute path for an image file, or None when it points outside the package folder."""
    relative = file_value.replace("\\", "/")
    if os.path.isabs(relative) or relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        return None
    base = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(base, *relative.split("/")))
    if os.path.commonpath([base, full]) != base:
        return None
    return full


def validate_question_images(question, idx_label, base_dir):
    """Errors for a question's images and markers. Checks the files exist, so base_dir must be real."""
    errors = []
    images = question.get("images")
    if images is not None and not isinstance(images, dict):
        return [f"{idx_label}: 'images' must be an object mapping image names to {{\"file\": ...}}."]
    images = images or {}

    for path, value in _strings_outside_text(question):
        if image_markers(value):
            errors.append(
                f"{idx_label}: '{path}' contains an image marker. Images can only go in the question text."
            )

    used = []
    for name in image_markers(question_text(question)):
        if not IMAGE_NAME.match(name):
            errors.append(
                f"{idx_label}: [[image:{name}]] is not a valid image name. "
                "Use lowercase letters, numbers, '-' and '_' only."
            )
        elif name not in images:
            errors.append(f"{idx_label}: the text uses [[image:{name}]] but 'images' has no entry named '{name}'.")
        elif name in used:
            errors.append(f"{idx_label}: [[image:{name}]] is used more than once. Give each copy its own name.")
        used.append(name)

    for name, spec in images.items():
        label = f"{idx_label}: image '{name}'"
        if not IMAGE_NAME.match(str(name)):
            errors.append(f"{label} has an invalid name. Use lowercase letters, numbers, '-' and '_' only.")
            continue
        if name not in used:
            errors.append(f"{label} is listed in 'images' but the text has no [[image:{name}]] marker.")
        if not isinstance(spec, dict):
            errors.append(f"{label} must be an object such as {{\"file\": \"images/{name}.png\"}}.")
            continue
        file_value = spec.get("file")
        if not isinstance(file_value, str) or not file_value.strip():
            errors.append(f"{label} needs a 'file' path, e.g. \"images/{name}.png\".")
        else:
            errors.extend(_file_errors(label, base_dir, file_value.strip()))
        if "alt" in spec and not isinstance(spec["alt"], str):
            errors.append(f"{label}: 'alt' must be a string.")
        if "width" in spec:
            width = spec["width"]
            if isinstance(width, bool) or not isinstance(width, int) or not MIN_WIDTH <= width <= MAX_WIDTH:
                errors.append(f"{label}: 'width' must be a whole number of pixels from {MIN_WIDTH} to {MAX_WIDTH}.")
    return errors


def _file_errors(label, base_dir, file_value):
    if not file_value.lower().endswith(IMAGE_EXTENSIONS):
        return [f"{label}: '{file_value}' is not a supported image type ({', '.join(IMAGE_EXTENSIONS)})."]
    full = _resolve_file(base_dir, file_value)
    if full is None:
        return [f"{label}: '{file_value}' must be a path inside the exam folder, such as images/{os.path.basename(file_value)}."]
    if not os.path.isfile(full):
        return [f"{label}: file '{file_value}' was not found next to the questions file."]
    if os.path.getsize(full) > MAX_IMAGE_BYTES:
        return [f"{label}: '{file_value}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."]
    return []


def resolve_question_images(question, base_dir):
    """{name: {"path", "alt", "width"}} for a validated question."""
    resolved = {}
    for name, spec in (question.get("images") or {}).items():
        resolved[name] = {
            "path": _resolve_file(base_dir, spec["file"].strip()),
            "alt": spec.get("alt") or "",
            "width": spec.get("width"),
        }
    return resolved


# ---------- uploading ----------

_PLACE_CARET_AT_MARKER = r"""([root, marker]) => {
    root.normalize();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const at = node.data.indexOf(marker);
        if (at < 0) continue;
        node.deleteData(at, marker.length);
        root.focus();
        const range = document.createRange();
        range.setStart(node, at);
        range.collapse(true);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        return true;
    }
    return false;
}"""

_UPLOADED_URLS = "root => Array.from(root.querySelectorAll('img[data-uploaded-image-url]')).map(i => i.dataset.uploadedImageUrl)"

_STYLE_NEW_IMAGE = r"""([root, before, alt, width]) => {
    const img = Array.from(root.querySelectorAll('img[data-uploaded-image-url]'))
        .find(i => !before.includes(i.dataset.uploadedImageUrl));
    if (!img) return false;
    if (alt) img.alt = alt;
    if (width) img.style.width = width + 'px';
    return true;
}"""


def insert_question_images(page, images, logger):
    """Replace every [[image:name]] marker in the open question editor with its uploaded image."""
    if not images:
        return
    container = page.locator(f"{QUESTION_CONTAINER}:visible").last
    editor = container.locator('div.fr-element[contenteditable="true"]').last
    root = editor.element_handle()

    for name in image_markers(editor.inner_text()):
        spec = images.get(name)
        if spec is None:
            raise RuntimeError(f"The question text has [[image:{name}]] but no image named '{name}'.")
        before = page.evaluate(_UPLOADED_URLS, root)
        root.evaluate("el => el.scrollIntoView({block: 'center'})")
        if not page.evaluate(_PLACE_CARET_AT_MARKER, [root, f"[[image:{name}]]"]):
            raise RuntimeError(f"Could not find [[image:{name}]] in the question editor.")

        container.locator('button[data-cmd="insertImage"]').first.click(timeout=5000)
        upload_area = page.locator(".fr-popup.fr-active .fr-image-upload-layer.fr-active").last
        with page.expect_file_chooser(timeout=5000) as chooser:
            upload_area.click(timeout=5000)
        chooser.value.set_files(spec["path"])
        try:
            page.wait_for_function(
                "([root, n]) => root.querySelectorAll('img[data-uploaded-image-url]').length > n",
                arg=[root, len(before)],
                timeout=UPLOAD_TIMEOUT_MS,
            )
        except Exception as e:
            raise RuntimeError(f"Uploading image '{name}' ({os.path.basename(spec['path'])}) did not finish.") from e

        page.evaluate(_STYLE_NEW_IMAGE, [root, before, spec.get("alt"), spec.get("width")])
        # Close the image toolbar Froala opens on the new image; it covers the editor.
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        logger.info("Inserted image '%s' (%s).", name, os.path.basename(spec["path"]))

    if image_markers(editor.inner_text()):
        raise RuntimeError("Some image markers were left in the question text after uploading.")
