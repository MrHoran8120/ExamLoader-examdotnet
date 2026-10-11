"""Render question text containing Markdown code (``` blocks / `inline`) as formatted HTML in exam.net.

exam.net's question editor is a Froala editor. Typed text shows Markdown literally, so when a
question contains code we switch the editor to Code View and enter HTML instead.

exam.net sanitises question HTML on save: <pre> and <p> become plain <div>s (losing line breaks),
but <code> (monospace), &nbsp; and one-<div>-per-line survive. The HTML is built in that shape.
"""

import html
import re

CODE_FENCE_LINE = re.compile(r"^[ \t]*```[\w+-]*[ \t]*\r?\n?", re.MULTILINE)
FENCE_ONLY = re.compile(r"^[ \t]*```[\w+-]*[ \t]*$")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
BLANK_LINE = "<div><br></div>"
# Makes the block's <code> one box instead of a strip per line (if exam.net keeps the style).
CODE_BLOCK_STYLE = "display: block; padding: 6px 8px;"

QUESTION_CONTAINER = '[data-testid="question-formulation-input"]'


def has_code_marks(text):
    return isinstance(text, str) and "`" in text


def strip_markdown_code_marks(text):
    """Plain-text fallback: drop code fences and inline backticks, keeping the code itself."""
    if not has_code_marks(text):
        return text
    return INLINE_CODE.sub(r"\1", CODE_FENCE_LINE.sub("", text))


def _code_line_html(line):
    line = line.expandtabs(4).rstrip()
    stripped = line.lstrip(" ")
    indent = "&nbsp;" * (len(line) - len(stripped))
    body = html.escape(stripped).replace("  ", " &nbsp;")
    return (indent + body) or "&nbsp;"


def _code_block_html(lines):
    # One <code> box for the whole block; <br> keeps the line breaks.
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None
    return (
        f'<div><code style="{CODE_BLOCK_STYLE}">'
        + "<br>".join(_code_line_html(line) for line in lines)
        + "</code></div>"
    )


def question_text_to_html(text):
    """One <div> per line, blank lines as <div><br></div>, each fenced code block as a single
    <code> box with indentation kept, and `inline` code as <code>."""
    out = []
    in_code = False
    code_lines = []
    for line in str(text).replace("\r\n", "\n").split("\n"):
        if FENCE_ONLY.match(line):
            if in_code:
                block = _code_block_html(code_lines)
                if block:
                    out.append(block)
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
        elif not line.strip():
            out.append(BLANK_LINE)
        else:
            escaped = INLINE_CODE.sub(r"<code>\1</code>", html.escape(line.strip()))
            out.append(f"<div>{escaped}</div>")
    if in_code:  # unclosed fence
        block = _code_block_html(code_lines)
        if block:
            out.append(block)
    while out and out[0] == BLANK_LINE:
        out.pop(0)
    while out and out[-1] == BLANK_LINE:
        out.pop()
    return "".join(out)


def _normalize(text):
    return " ".join(str(text or "").split()).lower()


def _find_code_view_button(page, container, logger):
    scoped = container.locator('button[data-cmd="html"], button[data-title="Code View"], button[title="Code View"]')
    if scoped.count() > 0:
        logger.debug("Found Code View button inside the question container.")
        return scoped.last
    # Toolbar may sit outside the test-id container but inside the same Froala box.
    handle = container.locator('div.fr-element[contenteditable="true"]:visible').last.evaluate_handle(
        """(el) => {
            const box = el.closest('.fr-box');
            return box ? box.querySelector('button[data-cmd="html"]') : null;
        }"""
    )
    element = handle.as_element()
    if element is not None:
        logger.debug("Found Code View button in the question editor's Froala box.")
    return element


def _code_view_open(page):
    try:
        return page.locator("textarea.fr-code:visible").count() > 0
    except Exception:
        return False


def _set_code_view(page, button, want_open, timeout_ms):
    """Toggle Froala Code View. Falls back to raw mouse events when a normal click is blocked
    (Froala reacts to mousedown/mouseup, not to a synthetic click event)."""
    if _code_view_open(page) == want_open:
        return True
    try:
        button.click(timeout=timeout_ms)
    except Exception:
        pass
    page.wait_for_timeout(200)
    if _code_view_open(page) != want_open:
        for event in ("mousedown", "mouseup", "click"):
            button.dispatch_event(event)
        page.wait_for_timeout(300)
    return _code_view_open(page) == want_open


def fill_question_html(page, question_text, logger, timeout_ms=2500):
    """Enter question_text as HTML through the question editor's Code View.

    Returns True on verified success. Returns False (leaving Code View closed) when any step
    fails, so the caller can fall back to plain text.
    """
    container = page.locator(f"{QUESTION_CONTAINER}:visible").last
    button = None
    try:
        if container.count() == 0:
            return False
        editor = container.locator('div.fr-element[contenteditable="true"]:visible').last
        editor.wait_for(state="visible", timeout=timeout_ms)
        editor.scroll_into_view_if_needed()
        editor.click(timeout=timeout_ms)

        button = _find_code_view_button(page, container, logger)
        if button is None:
            logger.debug("Question editor Code View button not found; using plain text.")
            return False
        if not _set_code_view(page, button, True, timeout_ms):
            logger.debug("Question editor Code View did not open; using plain text.")
            return False

        page.locator("textarea.fr-code:visible").last.fill(question_text_to_html(question_text), timeout=timeout_ms)

        if not _set_code_view(page, button, False, timeout_ms):
            logger.debug("Question editor Code View did not close; using plain text.")
            return False
        page.wait_for_timeout(300)

        expected = _normalize(strip_markdown_code_marks(question_text))
        current = _normalize(editor.inner_text(timeout=timeout_ms))
        if expected and expected in current:
            logger.info("Filled question text with formatted code via Code View.")
            return True
        logger.debug(
            "Code View fill mismatch. Expected (partial): '%s...', found (partial): '%s...'",
            expected[:60],
            current[:60],
        )
        return False
    except Exception as e:
        logger.debug("Code View question fill failed: %s", e)
        return False
    finally:
        # Never leave the editor stuck in Code View; saving fails while it is open.
        if button is not None and _code_view_open(page):
            try:
                _set_code_view(page, button, False, 1500)
            except Exception:
                pass
