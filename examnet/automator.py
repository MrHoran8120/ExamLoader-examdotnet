import json
import logging
import os
import re
import time

from playwright.sync_api import sync_playwright

from .browser import launch_browser
from .json_precheck import _extract_json_payload, _strip_jsonc_comments, run_json_precheck
from .long_answer_probe import LongAnswerProbe
from .paths import data_file, diagnostics_dir
from .question_html import fill_question_html, has_code_marks, strip_markdown_code_marks

from .handlers import (
    FILL_GAPS_TYPES,
    LIST_MATCH_TYPES,
    LONG_ANSWER_TYPES,
    MULTIPLE_CHOICE_TYPES,
    PYTHON_PROGRAM_TYPES,
    SUPPORTED_QUESTION_TYPES,
    process_fill_gaps_question,
    process_list_match_question,
    process_long_answer_question,
    process_multiple_choice_question,
    process_python_program_question,
    validate_fill_gaps,
    validate_list_match,
    validate_long_answer,
    validate_multiple_choice,
    validate_python_program,
)


class ExamNetAutomator:
    def __init__(
        self,
        browser_url="http://127.0.0.1:9222",
        json_file="questions.json",
        interactive=True,
        max_attempts=1,
        stop_on_error=True,
        allow_existing_questions=False,
        start_index=1,
        debug_create_preview=False,
        debug_create_preview_ms=5000,
        debug_create_confirm=False,
        bypass_json_precheck=False,
        logger=None,
        confirm=None,
        should_stop=None,
        on_progress=None,
        pause_at_end=True,
    ):
        self.browser_url = browser_url
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.isabs(json_file):
            self.json_file = json_file
        else:
            self.json_file = os.path.join(os.getcwd(), json_file)
        self.interactive = interactive
        self.max_attempts = max(1, int(max_attempts))
        self.stop_on_error = bool(stop_on_error)
        self.allow_existing_questions = bool(allow_existing_questions)
        self.start_index = max(1, int(start_index))
        self.debug_create_preview = bool(debug_create_preview)
        self.debug_create_preview_ms = max(0, int(debug_create_preview_ms))
        self.debug_create_confirm = bool(debug_create_confirm)
        self.bypass_json_precheck = bool(bypass_json_precheck)
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        # Optional hooks for non-terminal front ends (e.g. the GUI).
        # confirm(message) -> bool replaces input() prompts when provided.
        self.confirm = confirm
        self.should_stop = should_stop
        self.on_progress = on_progress
        self.pause_at_end = bool(pause_at_end)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.long_answer_probe = None

    def _clear_create_button_debug_highlight(self):
        if not self.page:
            return
        try:
            self.page.evaluate(
                """() => {
                    const all = Array.from(document.querySelectorAll('button, [role="button"]'));
                    for (const el of all) {
                        const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (!text.includes('create question')) continue;
                        el.style.outline = '';
                        el.style.background = '';
                        el.style.transition = '';
                    }
                }"""
            )
        except Exception:
            pass

    def _capture_click_create_failure_diagnostics(self, prefix="create_question_click_failed"):
        try:
            out_dir = diagnostics_dir()
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            png_path = os.path.join(out_dir, f"{prefix}_{timestamp}.png")
            html_path = os.path.join(out_dir, f"{prefix}_{timestamp}.html")
            self.page.screenshot(path=png_path, full_page=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.page.content())
            self.logger.info("Saved diagnostics: %s and %s", png_path, html_path)
        except Exception as e:
            self.logger.warning("Failed to save create-click diagnostics: %s", e)

    @staticmethod
    def _is_editor_url(url):
        u = (url or "").lower()
        return "exam.net" in u and "/admin/exam-creator" in u

    @staticmethod
    def _is_print_builder_url(url):
        u = (url or "").lower()
        return "exam.net" in u and "/print-builder/" in u

    def select_exam_editor_page(self):
        if not self.browser:
            return

        best = None
        best_score = -10

        for context in self.browser.contexts:
            for page in context.pages:
                try:
                    url = page.url or ""
                    score = 0
                    if self._is_editor_url(url):
                        score += 100
                    elif "exam.net" in (url or ""):
                        score += 10
                    if self._is_print_builder_url(url):
                        score -= 100

                    has_create = page.locator('button:has-text("Create question"):visible').count() > 0
                    has_chooser = any(
                        page.locator(sel).count() > 0
                        for sel in (
                            '[data-testid="select-multipleChoice"]',
                            '[data-testid="select-fillGaps"]',
                            '[data-testid="select-matchItems"]',
                            '[data-testid="select-freeText"]',
                        )
                    )
                    if has_create or has_chooser:
                        score += 50

                    if score > best_score:
                        best = (context, page)
                        best_score = score
                except Exception:
                    continue

        if best:
            self.context, self.page = best
            try:
                self.page.bring_to_front()
            except Exception:
                pass

    def launch_cdp_browser(self):
        launch_browser(self.browser_url, logger=self.logger)

    def setup_browser(self):
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(self.browser_url)
        except Exception as e:
            self.logger.warning("Failed to connect to CDP browser: %s", e)
            self.logger.debug("Attempting to launch a new CDP Chrome window...")
            self.launch_cdp_browser()
            self.browser = self.playwright.chromium.connect_over_cdp(self.browser_url)

        self.select_exam_editor_page()
        if not self.context:
            contexts = self.browser.contexts
            if contexts:
                self.context = contexts[0]
            else:
                self.context = self.browser.new_context()
        if not self.page:
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = self.context.new_page()

        if "exam.net" not in self.page.url or not self.is_question_creation_ready():
            self.page.goto("https://exam.net")
            self.logger.debug("Navigated to exam.net.")
            if self.interactive and self.confirm:
                if not self.confirm(
                    "Log in to exam.net in the Chrome window and open your exam "
                    "so the 'Create question' button is visible.\n\nClick OK to continue."
                ):
                    raise RuntimeError("Run canceled by user at login prompt.")
            elif self.interactive:
                input("Press ENTER to continue after you have completed the login and setup... ")
            else:
                raise RuntimeError(
                    "Browser is not ready for automation (missing 'Create question' control or question-type chooser). "
                    "Run in interactive mode to complete login/setup first."
                )
        else:
            self.logger.debug("Using existing exam.net page with question creation controls available.")
        self.logger.debug("Continuing automation...")

    def is_question_type_chooser_open(self):
        selectors = [
            '[data-testid="select-multipleChoice"]:visible',
            '[data-testid="select-fillGaps"]:visible',
            '[data-testid="select-matchItems"]:visible',
            '[data-testid="select-freeText"]:visible',
        ]
        for selector in selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def is_question_creation_ready(self):
        try:
            has_create_btn = (
                self.page.locator('button:has-text("Create question"):visible').count() > 0
                or self.page.locator('button:has-text("Create new question"):visible').count() > 0
            )
        except Exception:
            has_create_btn = False
        return has_create_btn or self.is_question_type_chooser_open()

    def is_question_editor_open(self):
        selectors = [
            '[data-testid="question-formulation-input"]:visible',
            'button[aria-label="Save and close this question"]:visible',
            'button:has-text("Save and close this question"):visible',
            'div.question-editor__footer:visible',
        ]
        for selector in selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def wait_for_question_creation_ready(self, timeout_ms=20000, poll_ms=250):
        deadline = time.time() + (timeout_ms / 1000.0)
        last_error = None
        while time.time() < deadline:
            try:
                if self.is_question_creation_ready():
                    return True
            except Exception as e:
                last_error = e
            self.page.wait_for_timeout(poll_ms)
        if last_error:
            self.logger.debug("wait_for_question_creation_ready last error: %s", last_error)
        return False

    def load_questions(self):
        if not os.path.exists(self.json_file):
            raise FileNotFoundError(f"Questions file not found: {self.json_file}")
        with open(self.json_file, "r", encoding="utf-8-sig") as f:
            raw_text = f.read()

        payload_text = _extract_json_payload(raw_text)
        if not payload_text:
            raise ValueError(f"Questions file is empty: {self.json_file}")

        try:
            raw_payload = json.loads(payload_text)
        except json.JSONDecodeError as jde:
            sanitized_payload = _strip_jsonc_comments(payload_text).strip()
            try:
                raw_payload = json.loads(sanitized_payload)
            except json.JSONDecodeError:
                self.logger.warning("Standard JSON parsing failed: %s. Attempting resilient recovery...", jde)
            
                # Scavenging fallback: Find all top-level-like { ... } blocks using balanced braces.
                # This allows recovering valid questions from files with dangling fragments.
                recovered_questions = []
            
                def find_json_objects(text):
                    objs = []
                    stack = []
                    start = -1
                    for i, char in enumerate(text):
                        if char == '{':
                            if not stack:
                                start = i
                            stack.append('{')
                        elif char == '}':
                            if stack:
                                stack.pop()
                                if not stack:
                                    objs.append(text[start : i + 1])
                    return objs

                potentials = find_json_objects(sanitized_payload)
                for p in potentials:
                    try:
                        obj = json.loads(p)
                        # Heuristic to ensure it looks like a question object
                        if isinstance(obj, dict) and any(k in obj for k in ("question", "question_text", "question_id")):
                            recovered_questions.append(obj)
                    except Exception:
                        continue
            
                if recovered_questions:
                    self.logger.info("Resilient loader recovered %d valid question(s) from malformed file.", len(recovered_questions))
                    return recovered_questions
            
                # If scavenger found nothing, re-raise the original JSON error.
                raise jde

        if isinstance(raw_payload, list):
            return raw_payload
        if isinstance(raw_payload, dict):
            if isinstance(raw_payload.get("questions"), list):
                return raw_payload["questions"]
            return [raw_payload]
        raise ValueError("JSON payload must be an array or an object with optional 'questions' array.")

    @staticmethod
    def _is_non_empty_string(value):
        return isinstance(value, str) and bool(value.strip())

    def _validate_points(self, question, errors, idx_label):
        mark_payload = question.get("mark")
        if mark_payload is None:
            return
        if not isinstance(mark_payload, dict):
            errors.append(f"{idx_label}: 'mark' must be an object when provided.")
            return
        if "points" not in mark_payload:
            return
        try:
            points = float(str(mark_payload["points"]).strip())
            if points < 0:
                errors.append(f"{idx_label}: 'mark.points' must be >= 0.")
        except Exception:
            errors.append(f"{idx_label}: 'mark.points' must be numeric.")

    @staticmethod
    def normalize_question_type(question):
        if not isinstance(question, dict):
            raise ValueError(f"Each question entry must be an object. Found: {type(question).__name__}")

        raw_type = str(question.get("question_type", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if raw_type:
            return raw_type

        if isinstance(question.get("options"), list) and ("answer" in question or "answers" in question):
            return "multiple_choice"
        if isinstance(question.get("gaps"), list):
            return "fill_gaps"
        if any(isinstance(question.get(k), list) for k in ("pairs", "matches", "list_match_pairs")):
            return "list_match"
        return "long_answer"

    def validate_question(self, question, index):
        idx_label = f"Question {index}"
        if not isinstance(question, dict):
            return [f"{idx_label}: must be an object."]

        qtype = self.normalize_question_type(question)
        raw_qtype = question.get("question_type")
        if raw_qtype is not None and qtype not in SUPPORTED_QUESTION_TYPES:
            return [
                f"{idx_label}: unsupported question_type '{raw_qtype}'. "
                "Supported: multiple_choice, fill_gaps, long_answer, list_match, python_program."
            ]

        if qtype in MULTIPLE_CHOICE_TYPES:
            return validate_multiple_choice(question, idx_label, self._is_non_empty_string, self._validate_points)
        if qtype in FILL_GAPS_TYPES:
            return validate_fill_gaps(question, idx_label, self._is_non_empty_string, self._validate_points)
        if qtype in LIST_MATCH_TYPES:
            return validate_list_match(question, idx_label, self._is_non_empty_string, self._validate_points)
        if qtype in LONG_ANSWER_TYPES:
            return validate_long_answer(question, idx_label, self._is_non_empty_string, self._validate_points)
        if qtype in PYTHON_PROGRAM_TYPES:
            return validate_python_program(question, idx_label, self._is_non_empty_string, self._validate_points)

        return [
            f"{idx_label}: unsupported normalized type '{qtype}'. "
            "Supported: multiple_choice, fill_gaps, long_answer, list_match, python_program."
        ]

    def validate_questions(self, questions):
        if not isinstance(questions, list) or not questions:
            raise ValueError("Question payload must be a non-empty array of question objects.")

        all_errors = []
        for idx, question in enumerate(questions, start=1):
            all_errors.extend(self.validate_question(question, idx))

        if all_errors:
            details = "\n".join(f"- {msg}" for msg in all_errors)
            raise ValueError(f"Validation failed for '{os.path.basename(self.json_file)}':\n{details}")

    def click_create_question(self):
        self.select_exam_editor_page()
        self._clear_create_button_debug_highlight()
        if self.is_question_editor_open():
            raise RuntimeError(
                "Refusing to click 'Create question' while another question editor is still open."
            )
        if not self.wait_for_question_creation_ready(timeout_ms=20000):
            raise RuntimeError(
                "Timed out waiting for question creation controls (chooser or Create question button)."
            )

        if self.is_question_type_chooser_open():
            self.page.wait_for_timeout(200) # Small UI stability buffer
            self.logger.debug("Question-type chooser already open. Skipping 'Create question' click.")
            return

        if self.debug_create_confirm:
            try:
                self.page.evaluate(
                    """() => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                        const all = Array.from(document.querySelectorAll('button, [role="button"]'));
                        const candidates = all.filter((el) => {
                            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            return isVisible(el) && (text.includes('create question') || text.includes('create new question'));
                        });
                        if (!candidates.length) return;
                        candidates.sort((a, b) => pageY(a) - pageY(b));
                        const target = candidates[candidates.length - 1];
                        target.scrollIntoView({ block: 'center' });
                        target.style.outline = '4px solid #ff1744';
                        target.style.background = '#fff59d';
                        target.style.transition = 'all 120ms linear';
                    }"""
                )
            except Exception:
                pass
            if self.confirm:
                answer = "" if self.confirm("Click the highlighted 'Create question' button?") else "s"
            else:
                try:
                    answer = input(
                        "[Create question debug] Press ENTER to continue or type 's' to skip this click: "
                    ).strip().lower()
                except EOFError as e:
                    raise RuntimeError(
                        "debug_create_confirm is enabled but stdin is not interactive; cannot pause for confirmation."
                    ) from e
            if answer.startswith("s"):
                raise RuntimeError("Create-question click cancelled by user.")

        # Fast path: click the bottom-most visible "Create question" button via DOM.
        # This avoids expensive large-locator scans when many historical nodes exist.
        for fast_attempt in range(1, 3):
            try:
                clicked = self.page.evaluate(
                    """async (opts) => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                        const controls = Array.from(document.querySelectorAll('button, [role="button"]'));
                        const candidates = controls
                            .filter((el) => {
                                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                                return !disabled && isVisible(el) && (text.includes('create question') || text.includes('create new question'));
                            });
                        if (!candidates.length) return false;
                        candidates.sort((a, b) => pageY(a) - pageY(b));
                        const target = candidates[candidates.length - 1];
                        target.scrollIntoView({ block: 'center' });
                        if (opts.preview) {
                            target.style.outline = '4px solid #ff1744';
                            target.style.background = '#fff59d';
                            target.style.transition = 'all 120ms linear';
                            await new Promise((r) => setTimeout(r, opts.pauseMs || 0));
                        }
                        if (opts.confirm) {
                            const ok = window.confirm("Click highlighted 'Create question' button?");
                            if (!ok) return false;
                        }
                        target.click();
                        return true;
                    }""",
                    {"preview": self.debug_create_preview, "pauseMs": self.debug_create_preview_ms, "confirm": False},
                )
                if clicked:
                    # Wait for just the chooser to open, since we already clicked the button.
                    start = time.time()
                    while time.time() - start < 1.8:
                        if self.is_question_type_chooser_open():
                            self._clear_create_button_debug_highlight()
                            self.logger.debug("Opened question creation modal (fast path).")
                            return
                        self.page.wait_for_timeout(100)
            except Exception:
                pass
            self.page.wait_for_timeout(150)

        # Detailed attempt with pageY logging
        try:
            btn_info = self.page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                    const candidates = Array.from(document.querySelectorAll('button, [role="button"]'))
                        .filter(el => {
                            const text = (el.innerText || el.textContent || "").toLowerCase();
                            return (text.includes("create question") || text.includes("create new question")) && isVisible(el);
                        });
                    if (!candidates.length) return null;
                    candidates.sort((a,b) => pageY(a) - pageY(b));
                    const best = candidates[candidates.length - 1];
                    return { y: pageY(best), text: best.innerText.trim() };
                }"""
            )
            if btn_info:
                self.logger.debug("Attempting to click '%s' button at pageY=%.1f", btn_info['text'], btn_info['y'])
        except Exception:
            pass

        candidates = [
            self.page.get_by_role("button", name=re.compile(r"create( new)? question", re.IGNORECASE)),
            self.page.locator('button:has-text("Create question")'),
            self.page.locator('button:has-text("Create new question")'),
            self.page.locator('button span:has-text("Create question")').locator("xpath=ancestor::button[1]"),
            self.page.locator('button span:has-text("Create new question")').locator("xpath=ancestor::button[1]"),
            self.page.locator('button:has(span:has-text("Create question"))'),
            self.page.locator('button:has(span:has-text("Create new question"))'),
        ]

        last_error = None
        for candidate in candidates:
            try:
                # Only consider visible/actionable instances.
                visible_candidate = candidate.locator(":visible")
                count = visible_candidate.count()
                if count == 0:
                    continue
                self.logger.debug(
                    "Found %s candidate 'Create question' button(s). Clicking the bottom-most visible one...",
                    count,
                )
                clicked = visible_candidate.evaluate_all(
                    """async (els, opts) => {
                        const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                        const triggerClick = (el) => {
                            if (!el) return false;
                            if (typeof el.click === 'function') {
                                el.click();
                                return true;
                            }
                            try {
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                                return true;
                            } catch {
                                return false;
                            }
                        };
                        const visible = els.filter((el) => {
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        });
                        if (!visible.length) return false;
                        visible.sort((a, b) => pageY(a) - pageY(b));
                        const target = visible[visible.length - 1];
                        target.scrollIntoView({ block: 'center' });
                        if (opts.preview) {
                            target.style.outline = '4px solid #ff1744';
                            target.style.background = '#fff59d';
                            target.style.transition = 'all 120ms linear';
                            await new Promise((r) => setTimeout(r, opts.pauseMs || 0));
                        }
                        if (opts.confirm) {
                            const ok = window.confirm("Click highlighted 'Create question' button?");
                            if (!ok) return false;
                        }
                        return triggerClick(target);
                    }""",
                    {"preview": self.debug_create_preview, "pauseMs": self.debug_create_preview_ms, "confirm": False},
                )
                if not clicked:
                    continue
                # Wait for just the chooser to open
                start = time.time()
                opened = False
                while time.time() - start < 1.8:
                    if self.is_question_type_chooser_open():
                        opened = True
                        break
                    self.page.wait_for_timeout(100)
                if opened:
                    self._clear_create_button_debug_highlight()
                    self.logger.debug("Opened question creation modal (locator path).")
                    return
                self.logger.debug("Locator click did not open chooser yet; trying next candidate.")
            except Exception as e:
                last_error = e

        # DOM fallback: click the bottom-most visible "Create question" button.
        try:
            clicked = self.page.evaluate(
                """async (opts) => {
                    const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                    const triggerClick = (el) => {
                        if (!el) return false;
                        if (typeof el.click === 'function') {
                            el.click();
                            return true;
                        }
                        try {
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            return true;
                        } catch {
                            return false;
                        }
                    };
                    const controls = Array.from(document.querySelectorAll('button, [role="button"]'));
                    const matches = controls
                        .filter((el) => {
                            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            const visible =
                                style &&
                                style.visibility !== 'hidden' &&
                                style.display !== 'none' &&
                                rect.width > 0 &&
                                rect.height > 0;
                            const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                            return visible && !disabled && (text.includes('create question') || text.includes('create new question'));
                        });
                    if (!matches.length) return false;
                    matches.sort((a, b) => pageY(a) - pageY(b));
                    const target = matches[matches.length - 1];
                    target.scrollIntoView({ block: 'center' });
                    if (opts.preview) {
                        target.style.outline = '4px solid #ff1744';
                        target.style.background = '#fff59d';
                        target.style.transition = 'all 120ms linear';
                        await new Promise((r) => setTimeout(r, opts.pauseMs || 0));
                    }
                    if (opts.confirm) {
                        const ok = window.confirm("Click highlighted 'Create question' button?");
                        if (!ok) return false;
                    }
                    return triggerClick(target);
                }""",
                {"preview": self.debug_create_preview, "pauseMs": self.debug_create_preview_ms, "confirm": False},
            )
            if clicked:
                start = time.time()
                opened = False
                while time.time() - start < 1.8:
                    if self.is_question_type_chooser_open():
                        opened = True
                        break
                    self.page.wait_for_timeout(100)
                if opened:
                    self._clear_create_button_debug_highlight()
                    self.logger.info("Opened question creation modal using DOM fallback click.")
                    return
                self.logger.debug("DOM fallback click executed but chooser did not open.")
        except Exception as e:
            last_error = last_error or e

        # Final recovery: move to bottom of page and retry one quick DOM click.
        clicked = False
        try:
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(300)
            clicked = self.page.evaluate(
                """async (opts) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                    const controls = Array.from(document.querySelectorAll('button, [role="button"]'));
                    const matches = controls
                        .filter((el) => {
                            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            const isVisible = style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                            const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                            return !disabled && isVisible && (text.includes('create question') || text.includes('create new question'));
                        })
                        .sort((a, b) => pageY(a) - pageY(b));
                    if (!matches.length) return false;
                    const target = matches[matches.length - 1];
                    target.scrollIntoView({ block: 'center' });
                    target.click();
                    return true;
                }""",
                {"preview": self.debug_create_preview, "pauseMs": self.debug_create_preview_ms, "confirm": False},
            )
            if clicked:
                start = time.time()
                opened = False
                while time.time() - start < 2.2:
                    if self.is_question_type_chooser_open():
                        opened = True
                        break
                    self.page.wait_for_timeout(100)
                if opened:
                    self._clear_create_button_debug_highlight()
                    self.logger.info("Opened question creation modal using bottom-scroll recovery click.")
                    return
        except Exception as e:
            last_error = last_error or e

        self._capture_click_create_failure_diagnostics()
        try:
            counts = {
                "button_text": self.page.locator('button:has-text("Create question"):visible').count(),
                "button_new_text": self.page.locator('button:has-text("Create new question"):visible').count(),
                "role_button_text": self.page.locator('[role="button"]:has-text("Create question"):visible').count(),
                "role_button_new_text": self.page.locator('[role="button"]:has-text("Create new question"):visible').count(),
                "mc_chooser": self.page.locator('[data-testid="select-multipleChoice"]:visible').count(),
            }
        except Exception:
            counts = {}
        raise RuntimeError(
            "Could not click 'Create question' button and chooser is not open. "
            f"URL={self.page.url} counts={counts} Last error: {last_error}"
        )

    def fill_question_text(self, question_text):
        question_selector = '[data-testid="question-formulation-input"] div.fr-element.fr-view[contenteditable="true"]'
        self.page.wait_for_selector(question_selector, state="visible")
        if has_code_marks(question_text):
            if fill_question_html(self.page, question_text, self.logger):
                return
            question_text = strip_markdown_code_marks(question_text)
        self.page.locator(question_selector).locator(":visible").last.fill(question_text)
        self.logger.debug("Filled in question text.")

    def save_question(self):
        selectors = [
            'button[aria-label="Save and close this question"]',
            'button:has-text("Save and close this question")',
            'div.question-editor__footer button.SecondaryButton',
            'button.SecondaryButton[aria-disabled="false"]',
        ]

        last_error = None
        for selector in selectors:
            try:
                target = self.page.locator(selector).last
                target.wait_for(state="visible", timeout=5000)
                target.scroll_into_view_if_needed()
                target.click(timeout=5000)

                # Verify that the question editor closes after save.
                try:
                    self.page.wait_for_selector(
                        'button[aria-label="Save and close this question"]',
                        state="hidden",
                        timeout=6000,
                    )
                except Exception:
                    pass

                try:
                    self.page.wait_for_selector(
                        '[data-testid="question-formulation-input"]',
                        state="hidden",
                        timeout=6000,
                    )
                except Exception:
                    pass

                # Allow UI settle time before next "Create question" interaction.
                self.page.wait_for_timeout(5000)
                if self.is_question_editor_open():
                    raise RuntimeError(
                        "Save/close was clicked, but the question editor still appears to be open."
                    )
                if not self.wait_for_question_creation_ready(timeout_ms=20000):
                    self.logger.warning(
                        "Clicked save/close via selector '%s', but creation controls were slow to reappear.",
                        selector,
                    )
                else:
                    self.logger.info("Clicked save/close button using selector '%s'.", selector)
                return
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"Could not click 'Save and close this question'. Last error: {last_error}")

    def get_long_answer_probe(self):
        if self.long_answer_probe is None:
            log_level_name = logging.getLevelName(self.logger.getEffectiveLevel())
            self.long_answer_probe = LongAnswerProbe(
                browser_url=self.browser_url,
                interactive=self.interactive,
                log_level=log_level_name if isinstance(log_level_name, str) else "INFO",
                debug_create_preview=self.debug_create_preview,
                debug_create_preview_ms=self.debug_create_preview_ms,
                debug_create_confirm=self.debug_create_confirm,
            )

        self.long_answer_probe.playwright = self.playwright
        self.long_answer_probe.browser = self.browser
        self.long_answer_probe.context = self.context
        self.long_answer_probe.page = self.page
        self.long_answer_probe.debug_create_preview = self.debug_create_preview
        self.long_answer_probe.debug_create_preview_ms = self.debug_create_preview_ms
        self.long_answer_probe.debug_create_confirm = self.debug_create_confirm
        return self.long_answer_probe

    def process_question(self, question, idx=None):
        normalized_type = self.normalize_question_type(question)
        if normalized_type in FILL_GAPS_TYPES:
            # Gap detection works on plain text, so never send code formatting for fill-gaps.
            question = dict(question)
            for key in ("question", "question_text"):
                if key in question:
                    question[key] = strip_markdown_code_marks(question[key])

        if normalized_type in MULTIPLE_CHOICE_TYPES:
            process_multiple_choice_question(self, question, idx=idx)
            return
        if normalized_type in FILL_GAPS_TYPES:
            process_fill_gaps_question(self, question, normalized_type)
            return
        if normalized_type in LIST_MATCH_TYPES:
            process_list_match_question(self, question, normalized_type)
            return
        if normalized_type in LONG_ANSWER_TYPES:
            process_long_answer_question(self, question, normalized_type)
            return
        if normalized_type in PYTHON_PROGRAM_TYPES:
            process_python_program_question(self, question, normalized_type)
            return

        raise ValueError(
            f"Unsupported question_type '{question.get('question_type')}'. "
            "Supported: multiple_choice, fill_gaps, long_answer, list_match, python_program."
        )

    def _attempt_recover_from_question_error(self):
        try:
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(400)
        except Exception:
            pass
        return self.wait_for_question_creation_ready(timeout_ms=8000)

    def count_existing_questions(self):
        # Multiple UI variants exist; count through several robust markers.
        selectors = [
            '[data-testid="question"]:visible',
            '.exam-preview__question:visible',
            '.question-preview:visible',
            '.question-number:visible',
            '[class*="question-number"]:visible',
        ]
        best = 0
        for selector in selectors:
            try:
                count = self.page.locator(selector).count()
                if count > best:
                    best = count
            except Exception:
                continue

        # JS fallback for cases where locator variants miss framework-generated classes.
        if best == 0:
            try:
                best = int(
                    self.page.evaluate(
                        """() => {
                            const isVisible = (el) => {
                                if (!el) return false;
                                const s = window.getComputedStyle(el);
                                const r = el.getBoundingClientRect();
                                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                            };
                            const nodes = Array.from(document.querySelectorAll(
                                '[data-testid="question"], .question-number, [class*="question-number"], [class*="exam-preview__question"]'
                            ));
                            return nodes.filter(isVisible).length;
                        }"""
                    )
                )
            except Exception:
                pass

        return best

    def run(self):
        should_continue = run_json_precheck(
            self.json_file,
            interactive=self.interactive,
            bypass=self.bypass_json_precheck,
            logger=self.logger,
            confirm=self.confirm,
        )
        if not should_continue:
            raise RuntimeError("Run canceled due to JSON precheck failure.")

        questions = self.load_questions()
        self.validate_questions(questions)
        if self.start_index > len(questions):
            raise ValueError(
                f"--start-index {self.start_index} is beyond the {len(questions)} loaded questions."
            )
        self.logger.info("Validation passed for %s question(s).", len(questions))
        self.setup_browser()
        existing_count = self.count_existing_questions()
        self.logger.info("Detected %s existing question(s) before processing.", existing_count)
        failed = []
        # Process questions in JSON order. Exam.net's current editor appends
        # new questions in sequence, and reversing here can cause the runner
        # to populate the wrong editor state with the next question's content.
        processing_list = list(enumerate(questions, start=1))[self.start_index - 1:]
        expected_final_count = existing_count + len(processing_list)
        if self.start_index > 1:
            self.logger.info(
                "Resuming at question %s; skipping %s earlier payload question(s).",
                self.start_index,
                self.start_index - 1,
            )

        stopped = False
        for idx, question in processing_list:
            if self.should_stop and self.should_stop():
                self.logger.warning("Run stopped by user before question %s of %s.", idx, len(questions))
                stopped = True
                break
            if self.on_progress:
                self.on_progress(idx - 1, len(questions))
            label = question.get("question") or question.get("question_text") or question.get("question_id") or "N/A"
            success = False
            last_error = None
            for attempt in range(1, self.max_attempts + 1):
                self.logger.info("Processing question %s of %s (attempt %s/%s): %s", idx, len(questions), attempt, self.max_attempts, label)
                try:
                    self.process_question(question, idx=idx)
                    success = True
                    break
                except Exception as e:
                    last_error = e
                    if attempt < self.max_attempts:
                        self.logger.warning("Question %s attempt %s failed: %s", idx, attempt, e)
                        recovered = self._attempt_recover_from_question_error()
                        if not recovered:
                            self.logger.warning("Recovery after question %s attempt %s was incomplete.", idx, attempt)
                    else:
                        self.logger.error("Error processing question %s after retries: %s", idx, e)
            if not success:
                failed.append({"index": idx, "label": label, "question": question, "error": str(last_error)})
                if self.stop_on_error:
                    self.logger.error(
                        "Stopping run after first failed question (%s) to preserve ordering integrity.",
                        idx,
                    )
                    break

        if failed:
            final_count = self.count_existing_questions()
            self.logger.error(
                "Automation run interrupted. Final question count in exam: %s (Expected: %s)",
                final_count,
                expected_final_count,
            )
            
            failed_path = data_file("failed_questions.json")
            with open(failed_path, "w", encoding="utf-8") as f:
                json.dump([fitem["question"] for fitem in failed], f, indent=2, ensure_ascii=False)
            self.logger.error(
                "Completed with %s failure(s). Failed question indexes: %s. Saved payload to %s",
                len(failed),
                [fitem["index"] for fitem in failed],
                failed_path,
            )
        elif stopped:
            final_count = self.count_existing_questions()
            self.logger.warning(
                "Run stopped early. Final question count: %s (Started with: %s)",
                final_count,
                existing_count,
            )
        else:
            if self.on_progress:
                self.on_progress(len(questions), len(questions))
            final_count = self.count_existing_questions()
            self.logger.info(
                "All %s selected questions were processed successfully. Final question count: %s (Started with: %s)",
                len(processing_list),
                final_count,
                existing_count,
            )
        if self.interactive and self.pause_at_end:
            try:
                input("Press ENTER to end the script. The browser window will remain open...")
            except KeyboardInterrupt:
                self.logger.info("Run ended by user at final prompt.")
