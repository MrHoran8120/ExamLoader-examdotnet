import argparse
import html
import json
import logging
import os
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from .browser import launch_browser
from .paths import diagnostics_dir
from .question_html import fill_question_html, has_code_marks, strip_markdown_code_marks


class LongAnswerProbe:
    def __init__(
        self,
        browser_url="http://127.0.0.1:9222",
        interactive=True,
        log_level="INFO",
        ready_timeout=600,
        debug_create_preview=False,
        debug_create_preview_ms=5000,
        debug_create_confirm=False,
        question_type="long_answer",
        question_text="Sample long-answer question",
        answer_text="Sample answer",
        rubric_text=None,
        rubric_is_html=False,
        list_match_pairs=None,
        points=None,
    ):
        self.browser_url = browser_url
        self.interactive = interactive
        self.ready_timeout = ready_timeout
        self.debug_create_preview = bool(debug_create_preview)
        self.debug_create_preview_ms = max(0, int(debug_create_preview_ms))
        self.debug_create_confirm = bool(debug_create_confirm)
        self.question_type = question_type
        self.question_text = question_text
        self.answer_text = answer_text
        self.rubric_text = rubric_text
        self.rubric_is_html = rubric_is_html
        self.list_match_pairs = list_match_pairs or []
        self.points = points
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(getattr(logging, log_level))

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

    @staticmethod
    def _is_editor_url(url):
        u = (url or "").lower()
        return "exam.net" in u and "/admin/exam-creator" in u

    @staticmethod
    def _is_print_builder_url(url):
        u = (url or "").lower()
        return "exam.net" in u and "/print-builder/" in u

    def launch_cdp_browser(self):
        launch_browser(self.browser_url, logger=self.logger)

    def setup_browser(self, assume_ready=False):
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(self.browser_url)
        except Exception as e:
            self.logger.warning("Could not connect to existing CDP browser: %s", e)
            self.launch_cdp_browser()
            self.browser = self.playwright.chromium.connect_over_cdp(self.browser_url)

        self.attach_best_existing_page()

        if assume_ready:
            self.logger.debug("Assuming current page is already prepared; skipping readiness/navigation checks.")
            return

        if "exam.net" not in self.page.url or not self.has_create_question_button(timeout=3000):
            self.page.goto("https://exam.net")
            self.logger.debug("Opened exam.net. Log in and open your exam page.")
            if self.interactive and sys.stdin and sys.stdin.isatty():
                input("Press ENTER after login when the 'Create question' button is visible... ")
            elif self.interactive:
                self.logger.debug("Non-interactive stdin detected; waiting for 'Create question' to appear...")
                self.wait_for_create_question_ready(timeout=self.ready_timeout)
            else:
                raise RuntimeError("Exam page not ready in non-interactive mode.")
            self.select_exam_page()
        else:
            self.logger.debug("Using existing exam.net page with visible question controls.")

    def attach_best_existing_page(self):
        contexts = self.browser.contexts
        if not contexts:
            self.context = self.browser.new_context()
            self.page = self.context.new_page()
            return

        best = None
        best_score = -10
        for context in contexts:
            for page in context.pages:
                try:
                    url = page.url or ""
                    score = 0
                    if self._is_editor_url(url):
                        score += 100
                    elif "exam.net" in url:
                        score += 10
                    if self._is_print_builder_url(url):
                        score -= 100
                    if page.locator('button:has-text("Create question"):visible').count() > 0:
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
            return

        self.context = contexts[0]
        self.page = self.context.pages[-1] if self.context.pages else self.context.new_page()

    def select_exam_page(self):
        self.attach_best_existing_page()

    def has_create_question_button(self, timeout=2000):
        selectors = [
            'button:has-text("Create question")',
            '[role="button"]:has-text("Create question")',
            'button:has-text("create question")',
            '[role="button"]:has-text("create question")',
        ]
        for selector in selectors:
            try:
                self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)
                return True
            except Exception:
                continue
        return False

    def wait_for_create_question_ready(self, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.select_exam_page()
            if "exam.net" in self.page.url and self.has_create_question_button(timeout=1000):
                return
            time.sleep(1)
        raise RuntimeError("Timed out waiting for a page with visible 'Create question' button.")

    @staticmethod
    def _is_navigation_context_error(error):
        return "Execution context was destroyed" in str(error)

    def click_create_question(self):
        selectors = [
            'button:has-text("Create question")',
            '[role="button"]:has-text("Create question")',
            'button:has-text("create question")',
            '[role="button"]:has-text("create question")',
        ]

        last_error = None
        for attempt in range(1, 6):
            self.select_exam_page()
            self._clear_create_button_debug_highlight()
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=7000)
            except Exception:
                # Keep going; the page can still be usable while loading.
                pass

            if attempt == 1 and self.debug_create_confirm:
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
                                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                                return isVisible(el) && !disabled && text.includes('create question');
                            });
                            if (!candidates.length) return;
                            candidates.sort((a, b) => pageY(b) - pageY(a));
                            const target = candidates[0];
                            target.scrollIntoView({ block: 'center' });
                            target.style.outline = '4px solid #ff1744';
                            target.style.background = '#fff59d';
                            target.style.transition = 'all 120ms linear';
                        }"""
                    )
                except Exception:
                    pass
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

            self.logger.debug("Create question click attempt %s/5 on URL: %s", attempt, self.page.url)
            for selector in selectors:
                try:
                    locator = self.page.locator(selector).locator(":visible")
                    count = locator.count()
                    if count == 0:
                        continue
                    target = locator.evaluate_all(
                        """async (els, opts) => {
                            const pageY = (el) => el.getBoundingClientRect().top + window.scrollY;
                            const trigger = (el) => {
                                if (!el) return false;
                                if (typeof el.click === 'function') { el.click(); return true; }
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
                            visible.sort((a, b) => pageY(b) - pageY(a));
                            const btn = visible[0];
                            btn.scrollIntoView({ block: 'center' });
                            if (opts.preview) {
                                btn.style.outline = '4px solid #ff1744';
                                btn.style.background = '#fff59d';
                                btn.style.transition = 'all 120ms linear';
                                await new Promise((r) => setTimeout(r, opts.pauseMs || 0));
                            }
                            if (opts.confirm) {
                                const ok = window.confirm("Click highlighted 'Create question' button?");
                                if (!ok) return false;
                            }
                            return trigger(btn);
                        }""",
                        {
                            "preview": self.debug_create_preview,
                            "pauseMs": self.debug_create_preview_ms,
                            "confirm": False,
                        },
                    )
                    if not target:
                        continue
                    self.logger.debug("Clicking selector '%s'.", selector)

                    # Basic verification: modal/dialog becomes visible.
                    self.page.wait_for_selector(
                        '[role="dialog"], .Modal, [data-testid*="question"]',
                        timeout=7000,
                    )
                    self._clear_create_button_debug_highlight()
                    self.logger.debug("Create question click succeeded.")
                    return
                except PlaywrightTimeoutError as e:
                    last_error = e
                    self.logger.debug("Selector '%s' did not become actionable yet.", selector)
                except Exception as e:
                    last_error = e
                    if self._is_navigation_context_error(e):
                        self.logger.warning(
                            "Selector '%s' interrupted by navigation; retrying.",
                            selector,
                        )
                        break
                    self.logger.warning("Selector '%s' failed: %s", selector, e)

            time.sleep(0.75)

        self.capture_diagnostics("create_question_click_failed")
        raise RuntimeError(f"Failed to click 'Create question'. Last error: {last_error}")

    def click_free_text(self):
        # Reordered, tightened, and targeted approach to find and activate the
        # 'Free text' control. Try fast page-level selectors first, then
        # dialog-scoped selectors, and finally a targeted JS fallback. Reduce
        # timeouts and retry count to avoid long cumulative waits on slow pages.
        dialog_selectors = [
            '[role="dialog"]:visible',
            '.modal.show:visible',
            '.Modal:visible',
        ]
        free_text_button_selectors = [
            'button:has-text("Free text")',
            '[role="button"]:has-text("Free text")',
            'text=Free text',
        ]
        page_level_free_text_selectors = [
            '[data-testid="select-freeText"]:visible',
            '[role="button"][data-testid="select-freeText"]:visible',
            'button:has-text("Free text")',
            '[role="button"]:has-text("Free text")',
            '[role="menuitem"]:has-text("Free text")',
            'li:has-text("Free text")',
            'a:has-text("Free text")',
            'text=Free Text',
        ]

        last_error = None
        for attempt in range(1, 4):
            self.select_exam_page()

            # If already in free-text mode, short-circuit.
            if self.wait_for_free_text_editor_ready(timeout=1200):
                self.logger.debug("Free text editor already visible before click attempt.")
                return

            self.logger.debug("Free text click attempt %s/3 on URL: %s", attempt, self.page.url)

            # Fast path: page-level selectors (inline menus, header buttons).
            for selector in page_level_free_text_selectors:
                try:
                    target = self.page.locator(selector).first
                    target.wait_for(state="visible", timeout=800)
                    self.logger.debug("Clicking page-level selector '%s'.", selector)
                    target.scroll_into_view_if_needed()
                    target.click(timeout=1500)
                    if self.wait_for_free_text_editor_ready(timeout=3000):
                        self.logger.debug("Free text click succeeded using page-level selector.")
                        return
                except Exception as e:
                    last_error = e
                    continue

            # Modal/dialog path: search visible dialogs and click inside them.
            try:
                self.page.wait_for_selector('[role="dialog"], .Modal, [data-testid*="question"]', timeout=2500)
            except Exception:
                pass

            for dialog_selector in dialog_selectors:
                try:
                    dialog = self.page.locator(dialog_selector).last
                    dialog.wait_for(state="visible", timeout=800)
                except Exception:
                    continue

                for selector in free_text_button_selectors:
                    try:
                        target = dialog.locator(selector).first
                        target.wait_for(state="visible", timeout=800)
                        self.logger.debug("Clicking selector '%s' in dialog '%s'.", selector, dialog_selector)
                        target.scroll_into_view_if_needed()
                        target.click(timeout=1500)
                        if self.wait_for_free_text_editor_ready(timeout=3000):
                            self.logger.debug("Free text click succeeded.")
                            return
                    except Exception as e:
                        last_error = e
                        if self._is_navigation_context_error(e):
                            self.logger.warning("Selector '%s' interrupted by navigation; retrying.", selector)
                            break
                        continue

            # Targeted JS fallback: query only likely interactive elements, not the whole DOM.
            try:
                clicked = self.page.evaluate(
                    """() => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], [role="menuitem"], li'));
                        const norm = (s) => (s || '').trim().replace(/\\s+/g, ' ');
                        for (const el of candidates) {
                            const text = norm(el.textContent || '');
                            if (!text) continue;
                            if (text === 'Free text' || text.includes('Free text')) {
                                if (isVisible(el)) { el.click(); return true; }
                            }
                        }
                        return false;
                    }""",
                )
                if clicked and self.wait_for_free_text_editor_ready(timeout=3000):
                    self.logger.debug("Free text click succeeded using targeted JS fallback.")
                    return
            except Exception as e:
                last_error = e

            # Short pause before retrying.
            time.sleep(0.5)

        self.capture_diagnostics("free_text_click_failed")
        raise RuntimeError(f"Failed to click 'Free text'. Last error: {last_error}")

    def wait_for_list_match_editor_ready(self, timeout=8000):
        selectors = [
            '[data-testid="match-items-edit-answer-option-right"]',
            'b:has-text("Matching option")',
            'button[aria-label="Add answer"]',
            '[class*="MatchItemsAnswerOptions__add-answer"]',
            '[data-testid*="list-match"]',
            'button:has-text("Add pair")',
            'button:has-text("Add row")',
            'button:has-text("Add item")',
        ]
        deadline = time.time() + (timeout / 1000)
        while time.time() < deadline:
            for selector in selectors:
                try:
                    target = self.page.locator(selector).first
                    if target.count() == 0:
                        continue
                    if target.is_visible(timeout=400):
                        return True
                except Exception:
                    continue
            time.sleep(0.25)
        return False

    def click_list_match(self):
        dialog_selectors = [
            '[role="dialog"]:visible',
            '.modal.show:visible',
            '.Modal:visible',
        ]
        type_button_selectors = [
            '[data-testid="select-matchItems"]:visible',
            '[role="button"][data-testid="select-matchItems"]:visible',
            '[role="button"]:has-text("Match answers"):visible',
            '[role="button"]:has-text("List match"):visible',
            'button:has-text("Match answers"):visible',
            'button:has-text("List match"):visible',
        ]
        page_level_selectors = [
            '[data-testid="select-matchItems"]:visible',
            '[role="button"][data-testid="select-matchItems"]:visible',
            '[role="button"]:has-text("Match answers"):visible',
            '[role="button"]:has-text("List match"):visible',
            'button:has-text("Match answers"):visible',
            'button:has-text("List match"):visible',
        ]

        last_error = None
        for attempt in range(1, 4):
            self.select_exam_page()
            if self.wait_for_list_match_editor_ready(timeout=1200):
                self.logger.debug("List-match editor already visible before click attempt.")
                return

            self.logger.debug("List match click attempt %s/3 on URL: %s", attempt, self.page.url)
            for selector in page_level_selectors:
                try:
                    target = self.page.locator(selector).first
                    target.wait_for(state="visible", timeout=800)
                    self.logger.debug("Clicking page-level selector '%s'.", selector)
                    target.scroll_into_view_if_needed()
                    target.click(timeout=1500)
                    if self.wait_for_list_match_editor_ready(timeout=3000):
                        self.logger.debug("List match click succeeded using page-level selector.")
                        return
                except Exception as e:
                    last_error = e
                    continue

            # JS fallback: click bottom-most visible list-match card/button.
            try:
                clicked = self.page.evaluate(
                    """() => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const s = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const trigger = (el) => {
                            if (!el) return false;
                            if (typeof el.click === 'function') { el.click(); return true; }
                            try {
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                                return true;
                            } catch { return false; }
                        };
                        const all = Array.from(document.querySelectorAll('[data-testid=\"select-matchItems\"], button, [role=\"button\"]'));
                        const matches = all.filter((el) => {
                            const id = (el.getAttribute && el.getAttribute('data-testid')) || '';
                            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            return isVisible(el) && (id === 'select-matchItems' || text.includes('match answers') || text.includes('list match'));
                        }).sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                        if (!matches.length) return false;
                        const target = matches[0];
                        target.scrollIntoView({ block: 'center' });
                        return trigger(target);
                    }""",
                )
                if clicked and self.wait_for_list_match_editor_ready(timeout=3000):
                    self.logger.debug("List match click succeeded using JS fallback.")
                    return
            except Exception as e:
                last_error = e

            try:
                self.page.wait_for_selector('[role="dialog"], .Modal, [data-testid*="question"]', timeout=2500)
            except Exception:
                pass

            for dialog_selector in dialog_selectors:
                try:
                    dialog = self.page.locator(dialog_selector).last
                    dialog.wait_for(state="visible", timeout=800)
                except Exception:
                    continue

                for selector in type_button_selectors:
                    try:
                        target = dialog.locator(selector).first
                        target.wait_for(state="visible", timeout=800)
                        self.logger.debug("Clicking selector '%s' in dialog '%s'.", selector, dialog_selector)
                        target.scroll_into_view_if_needed()
                        target.click(timeout=1500)
                        if self.wait_for_list_match_editor_ready(timeout=3000):
                            self.logger.info("List match click succeeded.")
                            return
                    except Exception as e:
                        last_error = e
                        continue

            time.sleep(0.5)

        self.capture_diagnostics("list_match_click_failed")
        raise RuntimeError(f"Failed to click 'List match'. Last error: {last_error}")

    def fill_list_match_pairs(self, pairs):
        if not isinstance(pairs, list) or not pairs:
            raise RuntimeError("List match requires a non-empty 'pairs' array in JSON.")

        normalized_pairs = []
        for idx, pair in enumerate(pairs, start=1):
            if isinstance(pair, dict):
                left = str(pair.get("left", "")).strip()
                right = str(pair.get("right", "")).strip()
            elif isinstance(pair, (list, tuple)) and len(pair) >= 2:
                left = str(pair[0]).strip()
                right = str(pair[1]).strip()
            else:
                raise RuntimeError(f"Invalid list-match pair format at index {idx}: {pair!r}")
            if not left or not right:
                raise RuntimeError(f"List-match pair at index {idx} must have both left and right values.")
            normalized_pairs.append({"left": left, "right": right})

        def fill_editor(selectors, value, field_name):
            for selector in selectors:
                try:
                    target = self.page.locator(selector).last
                    target.wait_for(state="visible", timeout=4000)
                    target.scroll_into_view_if_needed()
                    target.click(timeout=2000)
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.type(value, delay=8)
                    current_text = (target.inner_text(timeout=1500) or "").strip()
                    if value.strip() in current_text:
                        return
                except Exception:
                    continue
            raise RuntimeError(f"Could not fill {field_name} field.")

        option_selectors = [
            'css=[data-testid="match-items-edit-answer-option-left"] div.fr-element.fr-view[contenteditable="true"]',
            'xpath=//b[normalize-space(.)="Option"]/following-sibling::*[1]//div[contains(@class,"fr-element") and @contenteditable="true"]',
            'xpath=//b[contains(normalize-space(.),"Option") and not(contains(normalize-space(.),"Matching"))]/following::div[contains(@class,"fr-element") and @contenteditable="true"][1]',
        ]
        matching_selectors = [
            'css=[data-testid="match-items-edit-answer-option-right"] div.fr-element.fr-view[contenteditable="true"]',
            'xpath=//b[normalize-space(.)="Matching option"]/following-sibling::*[1]//div[contains(@class,"fr-element") and @contenteditable="true"]',
            'xpath=//b[contains(normalize-space(.),"Matching option")]/following::div[contains(@class,"fr-element") and @contenteditable="true"][1]',
        ]
        add_answer_selectors = [
            'button[aria-label="Add answer"]',
            'button.MatchItemsAnswerOptions__add-answer',
            'button:has-text("Add answer")',
        ]

        for idx, pair in enumerate(normalized_pairs, start=1):
            fill_editor(option_selectors, pair["left"], "Option")
            fill_editor(matching_selectors, pair["right"], "Matching option")

            added = False
            for selector in add_answer_selectors:
                try:
                    button = self.page.locator(selector).last
                    button.wait_for(state="visible", timeout=4000)
                    button.scroll_into_view_if_needed()
                    button.click(timeout=3000)
                    added = True
                    break
                except Exception:
                    continue

            if not added:
                self.capture_diagnostics("fill_list_match_pairs_failed")
                raise RuntimeError(f"Could not click 'Add answer' for pair index {idx}.")

        self.logger.info("Filled list-match pairs: %s", len(normalized_pairs))

    def wait_for_free_text_editor_ready(self, timeout=8000):
        selectors = [
            '[data-testid="question-formulation-input"] div.fr-element.fr-view[contenteditable="true"]',
            '[data-testid="question-formulation-input"] textarea',
            '[data-testid="question-formulation-input"] input[type="text"]',
            'xpath=//span[contains(@class,"fr-placeholder") and contains(normalize-space(.),"Enter your exam question")]/ancestor::div[contains(@class,"fr-wrapper")][1]//div[contains(@class,"fr-element") and @contenteditable="true"]',
            'div.fr-element.fr-view[contenteditable="true"]',
        ]
        deadline = time.time() + (timeout / 1000)
        while time.time() < deadline:
            for selector in selectors:
                try:
                    target = self.page.locator(selector).last
                    if target.count() == 0:
                        continue
                    if target.is_visible(timeout=400):
                        return True
                except Exception as e:
                    continue
            time.sleep(0.25)
        return False

    def fill_question_prompt(self, question_text):
        if not self.wait_for_free_text_editor_ready(timeout=5000):
            self.capture_diagnostics("free_text_not_ready_before_fill")
            raise RuntimeError(
                "Free-text editor is not visible after selecting question type. "
                "Please check whether 'Free text' was actually selected."
            )

        if has_code_marks(question_text):
            if fill_question_html(self.page, question_text, self.logger):
                return
            question_text = strip_markdown_code_marks(question_text)

        # Prefer explicit question-formulation container first to avoid writing
        # into unrelated hidden editors left in the DOM.
        try:
            container_selectors = [
                '[data-testid="question-formulation-input"] div.fr-element.fr-view[contenteditable="true"]',
                '[data-testid="question-formulation-input"] div.fr-element[contenteditable="true"]',
                '[data-testid="question-formulation-input"] textarea',
                '[data-testid="question-formulation-input"] input[type="text"]',
            ]
            for selector in container_selectors:
                target = self.page.locator(selector).locator(":visible").last
                if target.count() == 0:
                    continue
                target.wait_for(state="visible", timeout=1200)
                target.scroll_into_view_if_needed()
                target.click(timeout=1200)
                tag = (target.evaluate("el => (el.tagName || '').toLowerCase()") or "").strip()
                if tag in {"textarea", "input"}:
                    target.fill(question_text, timeout=2000)
                    self.page.wait_for_timeout(300)
                    current = (target.input_value(timeout=1200) or "").strip()
                else:
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.press("Backspace") # Ensure it's cleared
                    self.page.keyboard.type(question_text, delay=2) # Faster delay for long questions
                    self.page.wait_for_timeout(500)
                    current = (target.inner_text(timeout=2000) or "").strip()
                
                norm_expected = normalize_for_editor_match(question_text)
                norm_current = normalize_for_editor_match(current)
                
                # Check if it's "mostly" there - long text can be tricky.
                # If at least 90% of the words are there, we'll consider it a success.
                if norm_expected in norm_current or norm_current in norm_expected:
                    self.logger.info("Filled free-text editor using selector '%s'.", selector)
                    return
                else:
                    self.logger.debug("Validation mismatch for selector '%s'. Expected (partial): '%s...', Found (partial): '%s...'", selector, norm_expected[:50], norm_current[:50])

        except Exception as e:
            self.logger.debug("Error filling with container selectors: %s", e)
            pass

        selectors = [
            '[data-testid="question-formulation-input"] div.fr-element.fr-view[contenteditable="true"]',
            'xpath=//span[contains(@class,"fr-placeholder") and contains(normalize-space(.),"Enter your exam question here ...")]/ancestor::div[contains(@class,"fr-wrapper")][1]//div[contains(@class,"fr-element") and @contenteditable="true"]',
            'xpath=//span[contains(@class,"fr-placeholder") and contains(normalize-space(.),"Enter your exam question here")]/ancestor::div[contains(@class,"fr-wrapper")][1]//div[contains(@class,"fr-element") and @contenteditable="true"]',
            'div.fr-element.fr-view[contenteditable="true"]',
        ]

        for selector in selectors:
            try:
                target = self.page.locator(selector).locator(":visible").last
                target.wait_for(state="visible", timeout=1200)
                target.scroll_into_view_if_needed()
                target.click(timeout=1200)
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Backspace")
                self.page.keyboard.type(question_text, delay=2)
                self.page.wait_for_timeout(500)

                current_text = (target.inner_text(timeout=2000) or "").strip()
                norm_expected = normalize_for_editor_match(question_text)
                norm_current = normalize_for_editor_match(current_text)
                
                if norm_expected in norm_current or norm_current in norm_expected:
                    self.logger.info("Filled free-text editor using selector '%s'.", selector)
                    return
                else:
                    self.logger.debug("Validation mismatch for secondary selector '%s'.", selector)
            except Exception:
                continue

        # Last fallback: set content in the editor tied to the placeholder via JS and fire editor-like events.
        try:
            updated = self.page.evaluate(
                """(text) => {
                    const placeholders = Array.from(document.querySelectorAll('span.fr-placeholder'));
                    const ph = placeholders.find(p => (p.textContent || '').includes('Enter your exam question'));
                    if (!ph) return false;
                    const wrapper = ph.closest('div.fr-wrapper');
                    if (!wrapper) return false;
                    const editor = wrapper.querySelector('div.fr-element[contenteditable="true"]');
                    if (!editor) return false;

                    editor.focus();
                    editor.innerHTML = `<p>${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
                    editor.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: text }));
                    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
                    editor.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'a' }));
                    editor.dispatchEvent(new Event('change', { bubbles: true }));
                    editor.dispatchEvent(new Event('blur', { bubbles: true }));
                    const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                    return norm(editor.innerText).includes(norm(text));
                }""",
                question_text,
            )
            if updated:
                self.logger.debug("Filled free-text editor using DOM fallback.")
                return
        except Exception:
            pass

        self.capture_diagnostics("fill_question_prompt_failed")
        raise RuntimeError(
            "Could not find the free-text editor field with placeholder 'Enter your exam question here'."
        )

    def expand_accordion_by_title(self, title, timeout=8000):
        deadline = time.time() + (timeout / 1000)
        while time.time() < deadline:
            try:
                header = self.page.locator(
                    f'xpath=//div[contains(@class,"accordion")]'
                    f'[.//h4[normalize-space()="{title}"]]'
                    f'//div[contains(@class,"accordion__header")]'
                ).first
                header.wait_for(state="visible", timeout=1000)
            except Exception:
                time.sleep(0.2)
                continue

            try:
                accordion = self.page.locator(
                    f'xpath=//div[contains(@class,"accordion")]'
                    f'[.//h4[normalize-space()="{title}"]]'
                ).first
                classes = (accordion.get_attribute("class") or "")
                if "accordion--closed" not in classes:
                    return
            except Exception:
                pass

            try:
                header.scroll_into_view_if_needed()
                header.click(timeout=2000)
            except Exception:
                pass

            try:
                accordion = self.page.locator(
                    f'xpath=//div[contains(@class,"accordion")]'
                    f'[.//h4[normalize-space()="{title}"]]'
                ).first
                classes = (accordion.get_attribute("class") or "")
                if "accordion--closed" not in classes:
                    return
            except Exception:
                pass

            time.sleep(0.2)

        self.capture_diagnostics(f"expand_accordion_{title.lower().replace(' ', '_')}_failed")
        raise RuntimeError(f"Could not expand accordion '{title}'.")

    def expand_accordion_by_title_candidates(self, titles, timeout=8000):
        deadline = time.time() + (timeout / 1000)
        normalized_titles = [(t or "").strip().lower() for t in titles if (t or "").strip()]
        if not normalized_titles:
            raise RuntimeError("No accordion titles provided.")

        while time.time() < deadline:
            try:
                matched = self.page.evaluate(
                    """(candidates) => {
                        const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                        const isVisible = (el) => {
                            const style = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        };
                        const accordions = Array.from(document.querySelectorAll('div.accordion'));
                        for (const accordion of accordions) {
                            const titleEl = accordion.querySelector('h1, h2, h3, h4, h5, label, span');
                            const titleText = norm(titleEl ? titleEl.textContent : '');
                            if (!titleText) continue;
                            const matches = candidates.some(c => titleText.includes(c));
                            if (!matches) continue;
                            const header = accordion.querySelector('div.accordion__header') || titleEl;
                            if (!header || !isVisible(header)) continue;
                            if ((accordion.className || '').includes('accordion--closed')) {
                                header.click();
                            }
                            return titleText;
                        }
                        return null;
                    }""",
                    normalized_titles,
                )
                if matched:
                    return matched
            except Exception:
                pass
            time.sleep(0.2)

        self.capture_diagnostics("expand_accordion_candidates_failed")
        raise RuntimeError(f"Could not expand accordion using titles: {titles}")

    def fill_first_editable_in_accordion(self, title, text_value):
        accordion_xpath = (
            f'xpath=//div[contains(@class,"accordion")]'
            f'[.//h4[normalize-space()="{title}"]]'
        )
        field_selectors = [
            f'{accordion_xpath}//section[contains(@class,"accordion__content")]'
            f'//div[@contenteditable="true"]',
            f'{accordion_xpath}//section[contains(@class,"accordion__content")]//textarea',
            f'{accordion_xpath}//section[contains(@class,"accordion__content")]'
            f'//input[not(@type="checkbox") and not(@type="radio")]',
        ]

        for selector in field_selectors:
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=5000)
                target.scroll_into_view_if_needed()
                target.click(timeout=2000)

                tag = (target.evaluate("el => el.tagName.toLowerCase()") or "").strip()
                is_content_editable = bool(target.evaluate("el => el.isContentEditable"))

                if tag == "input" or tag == "textarea":
                    target.fill(text_value, timeout=3000)
                    current = (target.input_value(timeout=2000) or "").strip()
                    if text_value.strip() in current:
                        self.logger.debug("Filled '%s' accordion field using selector '%s'.", title, selector)
                        return
                elif is_content_editable:
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.type(text_value, delay=8)
                    current = (target.inner_text(timeout=2000) or "").strip()
                    if text_value.strip() in current:
                        self.logger.debug("Filled '%s' accordion editor using selector '%s'.", title, selector)
                        return
            except Exception:
                continue

        # JS fallback: write to the first editable element in accordion content.
        try:
            updated = self.page.evaluate(
                """(payload) => {
                    const title = payload.title;
                    const value = payload.value;
                    const accordions = Array.from(document.querySelectorAll('div.accordion'));
                    const accordion = accordions.find(a => {
                        const h = a.querySelector('h4');
                        return h && (h.textContent || '').trim() === title;
                    });
                    if (!accordion) return false;
                    const content = accordion.querySelector('section.accordion__content');
                    if (!content) return false;

                    const editable =
                        content.querySelector('div[contenteditable="true"]') ||
                        content.querySelector('textarea') ||
                        content.querySelector('input:not([type="checkbox"]):not([type="radio"])');
                    if (!editable) return false;

                    editable.focus();
                    const tag = (editable.tagName || '').toLowerCase();
                    if (tag === 'textarea' || tag === 'input') {
                        editable.value = value;
                        editable.dispatchEvent(new Event('input', { bubbles: true }));
                        editable.dispatchEvent(new Event('change', { bubbles: true }));
                        return (editable.value || '').includes(value);
                    }

                    editable.innerHTML = `<p>${value.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
                    editable.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                    editable.dispatchEvent(new Event('change', { bubbles: true }));
                    return (editable.innerText || '').includes(value);
                }""",
                {"title": title, "value": text_value},
            )
            if updated:
                self.logger.debug("Filled '%s' accordion field using DOM fallback.", title)
                return
        except Exception:
            pass

        self.capture_diagnostics(f"fill_{title.lower().replace(' ', '_')}_failed")
        raise RuntimeError(f"Could not fill editable field inside '{title}' accordion.")

    def fill_first_editable_in_accordion_candidates(self, titles, text_value):
        normalized_titles = [(t or "").strip().lower() for t in titles if (t or "").strip()]
        if not normalized_titles:
            raise RuntimeError("No accordion titles provided.")

        # Primary path: locate first matching accordion and fill first editable field.
        try:
            updated = self.page.evaluate(
                """(payload) => {
                    const candidates = payload.candidates;
                    const value = payload.value;
                    const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                    const accordions = Array.from(document.querySelectorAll('div.accordion'));
                    const accordion = accordions.find(a => {
                        const titleEl = a.querySelector('h1, h2, h3, h4, h5, label, span');
                        const t = norm(titleEl ? titleEl.textContent : '');
                        return t && candidates.some(c => t.includes(c));
                    });
                    if (!accordion) return false;

                    const content = accordion.querySelector('section.accordion__content') || accordion;
                    const editable =
                        content.querySelector('div[contenteditable=\"true\"]') ||
                        content.querySelector('textarea') ||
                        content.querySelector('input:not([type=\"checkbox\"]):not([type=\"radio\"])');
                    if (!editable) return false;

                    editable.focus();
                    const tag = (editable.tagName || '').toLowerCase();
                    if (tag === 'textarea' || tag === 'input') {
                        editable.value = value;
                        editable.dispatchEvent(new Event('input', { bubbles: true }));
                        editable.dispatchEvent(new Event('change', { bubbles: true }));
                        return (editable.value || '').includes(value);
                    }

                    editable.innerHTML = `<p>${value.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
                    editable.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: value }));
                    editable.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                    editable.dispatchEvent(new Event('change', { bubbles: true }));
                    return (editable.innerText || '').includes(value);
                }""",
                {"candidates": normalized_titles, "value": text_value},
            )
            if updated:
                return
        except Exception:
            pass

        raise RuntimeError(f"Could not fill editable field in accordion candidates: {titles}")

    def fill_answer_options(self, answer_text):
        # Keep this strict to avoid writing into the main free-text editor
        # where "Sample answer" can appear as normal content.
        accordion_titles = ["Answer options", "Answer option"]
        try:
            self.expand_accordion_by_title_candidates(accordion_titles, timeout=6000)
            self.fill_first_editable_in_accordion_candidates(accordion_titles, answer_text)
            self.logger.debug("Filled answer options using accordion matching.")
            return
        except Exception:
            pass

        # Try a targeted JS fallback that finds a heading with one of the
        # candidate labels and writes into the nearest editable element. This
        # is more robust on pages where the DOM structure doesn't match our
        # XPath-based locators.
        try:
            written = self.page.evaluate(
                """(payload) => {
                    const candidates = payload.candidates.map(c => (c || '').toLowerCase().trim());
                    const value = payload.value || '';
                    const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();

                    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,label,span'));
                    for (const h of headings) {
                        const text = norm(h.textContent || '');
                        if (!text) continue;
                        if (!candidates.some(c => text.includes(c))) continue;

                        // Search nearby for an editable field inside the same section.
                        const section = h.closest('section') || h.closest('div') || document.body;
                        const editable = section.querySelector('div[contenteditable="true"], textarea, input:not([type="checkbox"]):not([type="radio"])');
                        if (!editable) continue;

                        const tag = (editable.tagName || '').toLowerCase();
                        if (tag === 'input' || tag === 'textarea') {
                            editable.value = value;
                            editable.dispatchEvent(new Event('input', { bubbles: true }));
                            editable.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }

                        // contenteditable: escape HTML and set as plain text in a paragraph
                        editable.focus();
                        editable.innerHTML = '<p>' + value.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</p>';
                        editable.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                        editable.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    return false;
                }""",
                {"candidates": ["Answer options", "Answer option"], "value": answer_text},
            )
            if written:
                self.logger.debug("Filled answer options using targeted JS heading fallback.")
                return
        except Exception:
            pass

        self.fill_first_editable_by_headings(
            headings=["Answer options", "Answer option"],
            text_value=answer_text,
            diagnostic_prefix="fill_sample_answer_failed",
        )

    def click_answer_options_field_toggle(self):
        # Keep answer-options accordion open before attempting to click controls inside it.
        try:
            self.expand_accordion_by_title_candidates(
                ["Answer options", "Answer option"],
                timeout=4000,
            )
        except Exception:
            pass

        selectors = [
            'css=[data-testid="sub-question-answers"] button[data-testid="maxbutton"]',
            'css=div.accordion.answer-options button[data-testid="maxbutton"]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options")]]//section[contains(@class,"accordion__content")]//input[not(@type="number")])[1]/following::button[1]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options")]]//section[contains(@class,"accordion__content")]//button)[last()]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options")]]//*[contains(@class,"BaseSelect")]//button)[last()]',
        ]
        for selector in selectors:
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=2500)
                target.scroll_into_view_if_needed()
                target.click(timeout=3000)
                self.logger.debug("Clicked answer-options field toggle using selector '%s'.", selector)
                return
            except Exception:
                continue

        # DOM fallback: find the first non-points input in the Answer options accordion
        # and click the nearest visible button to its right.
        try:
            clicked = self.page.evaluate(
                """() => {
                    const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                    const isVisible = el => {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };

                    const accordions = Array.from(document.querySelectorAll('div.accordion'));
                    const accordion = accordions.find(a => {
                        const h = a.querySelector('h1,h2,h3,h4,h5,label,span');
                        const t = norm(h ? h.textContent : '');
                        return t.includes('answer options') || t.includes('answer option');
                    });
                    if (!accordion) return false;

                    const content = accordion.querySelector('section.accordion__content') || accordion;
                    const input = content.querySelector(
                        'input:not([type="number"]):not([data-testid="points-input"]), textarea, div[contenteditable="true"]'
                    );
                    if (!input || !isVisible(input)) return false;

                    const inRect = input.getBoundingClientRect();
                    const buttons = Array.from(content.querySelectorAll('button, [role="button"]'))
                        .filter(isVisible);
                    let best = null;
                    let bestScore = Number.POSITIVE_INFINITY;
                    for (const btn of buttons) {
                        const r = btn.getBoundingClientRect();
                        const sameRow = Math.abs((r.top + r.height / 2) - (inRect.top + inRect.height / 2)) < 40;
                        if (!sameRow) continue;
                        if (r.left < inRect.left) continue;
                        const score = Math.abs(r.left - inRect.right);
                        if (score < bestScore) {
                            best = btn;
                            bestScore = score;
                        }
                    }
                    if (!best) return false;
                    best.click();
                    return true;
                }"""
            )
            if clicked:
                self.logger.debug("Clicked answer-options field toggle using DOM fallback.")
                return
        except Exception:
            pass

        self.capture_diagnostics("click_answer_options_toggle_failed")
        raise RuntimeError("Could not click the Answer options field toggle button.")

    def _click_latest_visible_code_view_button(self):
        selectors = [
            'button[data-title="Code View"]:visible',
            'button[title="Code View"]:visible',
            'button[data-cmd="html"]:visible',
            'button.fr-command[data-cmd="html"]:visible',
            'button[id^="html-"]:visible',
        ]
        for selector in selectors:
            try:
                loc = self.page.locator(selector)
                if loc.count() == 0:
                    continue
                target = loc.last
                target.scroll_into_view_if_needed()
                target.click(timeout=2500)
                self.logger.debug("Clicked code-view button using selector '%s'.", selector)
                return True
            except Exception:
                continue
        return False

    def _close_open_code_view_if_needed(self):
        # Save can fail while a Froala code-view textarea is active.
        # Only click the toolbar toggle when code view is actually open.
        for _ in range(3):
            try:
                if self.page.locator("textarea.fr-code:visible").count() == 0:
                    return
            except Exception:
                return

            if not self._click_latest_visible_code_view_button():
                return
            self.page.wait_for_timeout(150)

    def click_answer_options_code_view(self, close_only=False):
        # On open path, ensure answer-options row is prepared first.
        if not close_only:
            try:
                self.click_answer_options_field_toggle()
                self.page.wait_for_timeout(50)
            except Exception:
                # Continue to selector attempts below.
                pass

        # Click a code-view button inside the Answer options accordion first.
        scoped_selectors = [
            'css=[data-testid="sub-question-answers"] button[data-title="Code View"]',
            'css=[data-testid="sub-question-answers"] button[title="Code View"]',
            'css=[data-testid="sub-question-answers"] button[data-cmd="html"]',
            'css=[data-testid="sub-question-answers"] button[id^="html-"]',
            'css=div.accordion.answer-options button[data-title="Code View"]',
            'css=div.accordion.answer-options button[title="Code View"]',
            'css=div.accordion.answer-options button[data-cmd="html"]',
            'css=div.accordion.answer-options button[id^="html-"]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Answer option")]]//*[self::button or @role="button"][@data-title="Code View"])[last()]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Answer option")]]//*[self::button or @role="button"][@title="Code View"])[last()]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Answer option")]]//*[self::button or @role="button"][@data-cmd="html"])[last()]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Answer option")]]//*[self::button or @role="button"][starts-with(@id,"html-")])[last()]',
        ]
        for selector in scoped_selectors:
            try:
                target = self.page.locator(selector).last
                if target.count() == 0:
                    continue
                target.wait_for(state="visible", timeout=1200 if close_only else 2000)
                target.scroll_into_view_if_needed()
                target.click(timeout=1200 if close_only else 2000)
                self.logger.debug("Clicked code-view button in Answer options using selector '%s'.", selector)
                code_areas = self.page.locator(
                    'css=[data-testid="sub-question-answers"] textarea.fr-code'
                )
                if code_areas.count() > 0:
                    return
                code_areas = self.page.locator(
                    'css=div.accordion.answer-options textarea.fr-code'
                )
                if code_areas.count() > 0:
                    return
                code_areas = self.page.locator(
                    'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Answer option")]]//textarea[contains(@class,"fr-code")])[last()]'
                )
                if code_areas.count() > 0:
                    return
            except Exception:
                continue

        self.capture_diagnostics("click_answer_options_code_view_failed")
        raise RuntimeError("Could not click Answer options Code View without targeting Free text.")

    def fill_answer_options_code_html(self, html_text):
        self.logger.debug("Filling Answer options via Code View.")
        value = str(html_text or "").strip()
        if not value:
            raise RuntimeError("HTML text for code view cannot be empty.")

        selectors = [
            'css=[data-testid="sub-question-answers"] textarea.fr-code',
            'css=div.accordion.answer-options textarea.fr-code',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options")]]//textarea[contains(@class,"fr-code")])[last()]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer option")]]//textarea[contains(@class,"fr-code")])[last()]',
        ]
        for selector in selectors:
            try:
                loc = self.page.locator(selector)
                if loc.count() == 0:
                    continue
                target = loc.last
                target.wait_for(state="visible", timeout=2000)
                target.scroll_into_view_if_needed()
                target.click(timeout=2000)
                target.fill(value, timeout=2000)
                current = (target.input_value(timeout=2000) or "").strip()
                if value in current or current == value:
                    self.logger.debug("Filled Answer options code textarea using selector '%s'.", selector)
                    return
            except Exception:
                continue

        # JS fallback scoped to the Answer options accordion only.
        try:
            updated = self.page.evaluate(
                """(value) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                    const accordions = Array.from(document.querySelectorAll('div.accordion'));
                    const accordion = accordions.find(a => {
                        const h = a.querySelector('h1,h2,h3,h4,h5,label,span');
                        const t = norm(h ? h.textContent : '');
                        return t.includes('answer options') || t.includes('answer option');
                    });
                    if (!accordion) return false;
                    const areas = Array.from(accordion.querySelectorAll('textarea.fr-code')).filter(isVisible);
                    const area = areas[areas.length - 1];
                    if (!area) return false;
                    area.focus();
                    area.value = value;
                    area.dispatchEvent(new Event('input', { bubbles: true }));
                    area.dispatchEvent(new Event('change', { bubbles: true }));
                    return (area.value || '') === value;
                }""",
                value,
            )
            if updated:
                self.logger.info("Filled Answer options code textarea using DOM fallback.")
                return
        except Exception:
            pass

        self.capture_diagnostics("fill_answer_options_code_html_failed")
        raise RuntimeError("Could not fill Answer options HTML in code-view textarea.")

    def fill_rubric(self, rubric_text):
        rubric_text = str(rubric_text or "").strip()
        if not rubric_text:
            return

        # Keep the expected grading accordion open when possible.
        try:
            self.expand_accordion_by_title_candidates(
                ["Marking instructions", "Rubric", "Grading rules"],
                timeout=4000,
            )
        except Exception:
            pass

        def _try_fill_text_field():
            selectors = [
                'div.accordion.grading-rules input:not([data-testid="points-input"]):not([type="number"])',
                'div.accordion.grading-rules textarea',
                'xpath=(//div[contains(@class,"accordion") and contains(@class,"grading-rules")]//*[self::input or self::textarea][not(@data-testid="points-input") and not(@type="number")])[1]',
            ]
            for selector in selectors:
                try:
                    locator = self.page.locator(selector)
                    if locator.count() == 0:
                        continue
                    target = locator.first
                    target.wait_for(state="visible", timeout=3000)
                    target.scroll_into_view_if_needed()
                    target.click(timeout=2000)
                    target.fill(rubric_text, timeout=3000)
                    target.blur()
                    current = (target.input_value(timeout=2000) or "").strip()
                    if current == rubric_text or rubric_text[:24] in current:
                        self.logger.debug("Filled rubric using selector '%s'.", selector)
                        return True
                except Exception:
                    continue
            return False

        if _try_fill_text_field():
            return

        # Do not create new marking-instruction rows automatically; avoid accidental
        # clicks on UI controls like "+ Add marking instruction". If no suitable
        # text field is present, capture diagnostics and fail so the caller can
        # decide (and a human can add the row if desired).
        if _try_fill_text_field():
            return

        self.capture_diagnostics("fill_rubric_failed")
        raise RuntimeError("Could not find an existing rubric text field in grading rules. Not adding rows automatically.")

    def set_question_points(self, points_value):
        self.logger.debug("Setting question points to: %s", points_value)
        value = str(points_value).strip()
        if not value:
            raise RuntimeError("Points value cannot be empty.")

        try:
            self.expand_accordion_by_title_candidates(
                ["Answer options", "Sample answer", "Sample answers", "Grading rules"],
                timeout=4000,
            )
        except Exception:
            # Continue; points can still be visible in some layouts.
            pass

        def values_match(current_value, expected_value):
            current = (current_value or "").strip()
            expected = (expected_value or "").strip()
            if current == expected:
                return True
            try:
                return abs(float(current) - float(expected)) < 1e-9
            except Exception:
                return False

        selectors = [
            'div.accordion.grading-rules input[data-testid="points-input"]',
            'xpath=(//div[contains(@class,"accordion")][.//h4[contains(normalize-space(.),"Answer options") or contains(normalize-space(.),"Sample answer") or contains(normalize-space(.),"Grading")]]//input[@data-testid="points-input"])[last()]',
            'xpath=(//section[contains(@class,"accordion__content")]//input[@data-testid="points-input"])[last()]',
            'input[data-testid="points-input"]:visible',
            'input[data-testid="points-input"]',
            'input.GradingInstructions__points-input',
            'input[type="number"][step="0.5"]',
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                if locator.count() == 0:
                    continue
                target = locator.last
                target.wait_for(state="visible", timeout=5000)
                target.scroll_into_view_if_needed()
                target.click(timeout=2000)
                before = (target.input_value(timeout=1500) or "").strip()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(value, delay=20)
                target.press("Tab")
                target.blur()
                self.page.wait_for_timeout(250)

                current = (target.input_value(timeout=2000) or "").strip()
                self.logger.info(
                    "Points attempt selector='%s' before='%s' after='%s' target='%s'.",
                    selector,
                    before,
                    current,
                    value,
                )
                if values_match(current, value):
                    self.logger.debug("Set question points to '%s' using selector '%s'.", value, selector)
                    return
            except Exception:
                continue

        # DOM fallback with native value setter (important for framework-controlled inputs).
        try:
            updated = self.page.evaluate(
                """(value) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const candidates = Array.from(document.querySelectorAll(
                        'input[data-testid="points-input"], input.GradingInstructions__points-input, input[type="number"][step="0.5"]'
                    )).filter(isVisible);
                    const input = candidates[candidates.length - 1] || null;
                    if (!input) return false;

                    const sameValue = (a, b) => {
                        const x = (a || '').trim();
                        const y = (b || '').trim();
                        if (x === y) return true;
                        const fx = Number.parseFloat(x);
                        const fy = Number.parseFloat(y);
                        return Number.isFinite(fx) && Number.isFinite(fy) && Math.abs(fx - fy) < 1e-9;
                    };

                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    if (setter) {
                        setter.call(input, value);
                    } else {
                        input.value = value;
                    }
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('blur', { bubbles: true }));
                    return sameValue(input.value || '', value);
                }""",
                value,
            )
            if updated:
                self.logger.debug("Set question points to '%s' using DOM fallback.", value)
                return
        except Exception:
            pass

        self.capture_diagnostics("set_question_points_failed")
        raise RuntimeError(f"Could not set question points to '{value}'.")

    def fill_first_editable_by_headings(self, headings, text_value, diagnostic_prefix):
        for heading in headings:
            selector = (
                'xpath=('
                f'//*[self::h1 or self::h2 or self::h3 or self::h4 or self::label or self::span]'
                f'[contains(normalize-space(.),"{heading}")]'
                '/following::*['
                'self::div[@contenteditable="true"] or self::textarea or '
                '(self::input and not(@type="checkbox") and not(@type="radio"))'
                '][1]'
                ')[1]'
            )
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=3500)
                target.scroll_into_view_if_needed()
                target.click(timeout=2000)

                tag = (target.evaluate("el => el.tagName.toLowerCase()") or "").strip()
                is_content_editable = bool(target.evaluate("el => el.isContentEditable"))

                if tag == "input" or tag == "textarea":
                    target.fill(text_value, timeout=3000)
                    current = (target.input_value(timeout=2000) or "").strip()
                    if text_value.strip() in current:
                        self.logger.info("Filled field after heading '%s'.", heading)
                        return
                elif is_content_editable:
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.type(text_value, delay=8)
                    current = (target.inner_text(timeout=2500) or "").strip()
                    if text_value.strip() in current:
                        self.logger.info("Filled rich-text field after heading '%s'.", heading)
                        return
            except Exception:
                continue

        self.capture_diagnostics(diagnostic_prefix)
        raise RuntimeError(f"Could not fill field using headings: {headings}")

    def capture_diagnostics(self, prefix):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        screenshot_path = os.path.join(diagnostics_dir(), f"{prefix}_{timestamp}.png")
        html_path = os.path.join(diagnostics_dir(), f"{prefix}_{timestamp}.html")
        try:
            self.page.screenshot(path=screenshot_path, full_page=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.page.content())
            self.logger.info("Saved diagnostics: %s and %s", screenshot_path, html_path)
        except Exception as e:
            self.logger.warning("Could not capture diagnostics: %s", e)

    def click_save_and_close_question(self):
        try:
            self._close_open_code_view_if_needed()
        except Exception:
            # Best effort only; continue with save attempts.
            pass

        selectors = [
            'button[aria-label="Save and close this question"]',
            'button:has-text("Save and close this question")',
            'div.question-editor__footer button.SecondaryButton',
            'button.SecondaryButton[aria-disabled="false"]',
        ]

        for selector in selectors:
            try:
                target = self.page.locator(selector).last
                target.wait_for(state="visible", timeout=5000)
                target.scroll_into_view_if_needed()
                target.click(timeout=5000)

                # Best-effort check that the editor closes.
                try:
                    self.page.wait_for_selector(
                        'button[aria-label="Save and close this question"]',
                        state="hidden",
                        timeout=5000,
                    )
                except Exception:
                    pass

                # Enforce a minimum post-save delay to allow exam.net UI to settle.
                self.page.wait_for_timeout(5000)
                self.logger.info("Clicked save/close button using selector '%s'.", selector)
                return
            except Exception:
                continue

        self.capture_diagnostics("save_and_close_question_failed")
        raise RuntimeError("Could not click 'Save and close this question'.")

    def run(self):
        self.setup_browser()
        self._run_payload_by_type(self.question_type, self.list_match_pairs)
        self.logger.info("Probe step complete. Browser remains open for the next run.")

    def _run_one_question(self):
        self.click_create_question()
        self.click_free_text()
        self.fill_question_prompt(self.question_text)
        answer_options_html = build_answer_options_html(
            rubric_text=self.rubric_text,
            answer_text=self.answer_text,
            rubric_is_html=self.rubric_is_html,
        )
        if answer_options_html.strip():
            self.click_answer_options_code_view()
            self.fill_answer_options_code_html(answer_options_html)
            self.click_answer_options_code_view(close_only=True)
        if self.points is not None:
            self.set_question_points(self.points)
        self.click_save_and_close_question()

    def run_many(self, question_payloads):
        if not question_payloads:
            raise RuntimeError("No question payloads were provided.")
        self.setup_browser()
        total = len(question_payloads)
        for idx, payload in enumerate(question_payloads, start=1):
            question_type, question_text, answer_text, rubric_text, rubric_is_html, list_match_pairs, points = extract_question_fields(
                payload,
                self.question_type,
                self.question_text,
                self.answer_text,
                self.rubric_text,
                self.list_match_pairs,
                self.points,
            )
            self.question_type = question_type
            self.question_text = question_text
            self.answer_text = answer_text
            self.rubric_text = rubric_text
            self.rubric_is_html = rubric_is_html
            self.list_match_pairs = list_match_pairs
            self.points = points
            self.logger.info("Processing question %s/%s type='%s'", idx, total, self.question_type)
            self._run_payload_by_type(self.question_type, self.list_match_pairs)
        self.logger.info("Batch run complete. Browser remains open for the next run.")

    def _run_payload_by_type(self, question_type, list_match_pairs, skip_create_question=False):
        qtype = str(question_type or "long_answer").strip().lower().replace("-", "_").replace(" ", "_")
        if qtype in {"long_answer", "free_text", "freetext"}:
            if not skip_create_question:
                self.click_create_question()
            self.click_free_text()
            self.fill_question_prompt(self.question_text)
            answer_options_html = build_answer_options_html(
                rubric_text=self.rubric_text,
                answer_text=self.answer_text,
                rubric_is_html=self.rubric_is_html,
            )
            if answer_options_html.strip():
                self.click_answer_options_code_view()
                self.fill_answer_options_code_html(answer_options_html)
                self.click_answer_options_code_view(close_only=True)
            if self.points is not None:
                self.set_question_points(self.points)
            self.click_save_and_close_question()
            return
        if qtype in {"list_match", "match_list"}:
            if not skip_create_question:
                self.click_create_question()
            self.click_list_match()
            self.fill_question_prompt(self.question_text)
            self.fill_list_match_pairs(list_match_pairs)
            if self.points is not None:
                self.set_question_points(self.points)
            self.click_save_and_close_question()
            return
        raise RuntimeError(f"Unsupported question_type '{question_type}'. Supported: long_answer, list_match.")

    def run_points_only(self):
        if self.points is None:
            raise RuntimeError("Points-only mode requires --points (or points=...).")
        self.setup_browser(assume_ready=True)
        self.set_question_points(self.points)
        self.click_save_and_close_question()
        self.logger.info("Points-only step complete. Browser remains open for the next run.")

    def run_click_answer_toggle_only(self):
        self.setup_browser(assume_ready=True)
        self.click_answer_options_field_toggle()
        self.logger.info("Answer-options toggle click test complete.")

    def run_click_code_view_only(self):
        self.setup_browser(assume_ready=True)
        self.click_answer_options_code_view()
        self.logger.info("Answer-options code-view click test complete.")

    def run_code_view_roundtrip_only(self, html_text):
        self.setup_browser(assume_ready=True)
        self.click_answer_options_code_view()
        self.fill_answer_options_code_html(html_text)
        self.click_answer_options_code_view(close_only=True)
        self.logger.info("Answer-options code-view roundtrip test complete.")

    def run_answer_options_smoke(self, html_text):
        # Assumes user has already created/opened the question editor.
        self.setup_browser(assume_ready=True)
        self.click_answer_options_code_view()
        self.fill_answer_options_code_html(html_text)
        self.click_answer_options_code_view(close_only=True)
        if self.points is not None:
            self.set_question_points(self.points)
        self.logger.info("Answer-options smoke test complete.")


def parse_args():
    parser = argparse.ArgumentParser(description="Probe script for long-answer UI automation in exam.net.")
    parser.add_argument("--browser-url", default="http://127.0.0.1:9222", help="Chrome CDP URL")
    parser.add_argument("--non-interactive", action="store_true", help="Disable prompts")
    parser.add_argument(
        "--ready-timeout",
        type=int,
        default=600,
        help="Seconds to wait for the exam page to show 'Create question' when stdin is non-interactive.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--question-text",
        default="Sample long-answer question",
        help="Question text to place in the prompt field (replacing default text like 'ncvbn').",
    )
    parser.add_argument(
        "--answer-text",
        default="Sample answer",
        help="Text to place in the 'Answer options' accordion field.",
    )
    parser.add_argument(
        "--rubric-text",
        default=None,
        help="Optional text to place in the 'Rubric' accordion field.",
    )
    parser.add_argument(
        "--points",
        default=None,
        help="Optional mark/points to set for the question (for example: 1, 1.5, 2).",
    )
    parser.add_argument(
        "--points-only",
        action="store_true",
        help="Only set question points on the current already-open page; skip create/free-text/prompt steps.",
    )
    parser.add_argument(
        "--json-file",
        default=None,
        help="Path to JSON file with long_answer/list_match payload(s), including question_type and mark.points.",
    )
    parser.add_argument(
        "--click-answer-toggle-only",
        action="store_true",
        help="Only click the button at the right side of the Answer options field on the current open editor page.",
    )
    parser.add_argument(
        "--click-code-view-only",
        action="store_true",
        help="Only click Answer options toggle, then click the Code View toolbar button.",
    )
    parser.add_argument(
        "--code-view-roundtrip-only",
        action="store_true",
        help="Click Code View, fill HTML into code textarea, then click Code View again to exit.",
    )
    parser.add_argument(
        "--answer-options-html",
        default=(
            "<p><strong>Rubric</strong></p>"
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%;'>"
            "<thead><tr><th>Criteria</th><th>Marks</th></tr></thead>"
            "<tbody>"
            "<tr><td>Provides a correct SQL query; extracts required statuses/categories; counts correctly; outputs descending order.</td><td>4</td></tr>"
            "<tr><td>Addresses most requirements of the problem.</td><td>3</td></tr>"
            "<tr><td>Shows some understanding of the problem.</td><td>2</td></tr>"
            "<tr><td>Shows some understanding of SQL or the problem.</td><td>1</td></tr>"
            "</tbody></table>"
            "<p><strong>Sample answer</strong></p>"
            "<p>SELECT category, status, COUNT(*) AS job_count FROM jobs WHERE status IN ('Pending','Escalated') "
            "AND category IN ('Software','Hardware') GROUP BY category, status ORDER BY job_count DESC;</p>"
        ),
        help="HTML payload used with --code-view-roundtrip-only.",
    )
    parser.add_argument(
        "--answer-options-smoke",
        action="store_true",
        help="Assume question editor is already open; only run Answer options HTML code-view roundtrip (and optional points).",
    )
    return parser.parse_args()


def format_rubric_plain_text(rubric_payload):
    if isinstance(rubric_payload, str):
        return rubric_payload
    if rubric_payload is None:
        return None
    if not isinstance(rubric_payload, dict):
        return str(rubric_payload)

    if rubric_payload.get("format") == "banded" and isinstance(rubric_payload.get("bands"), list):
        lines = []
        for band in rubric_payload.get("bands", []):
            marks = band.get("marks", "")
            mark_label = "mark" if str(marks).strip() == "1" else "marks"
            lines.append(f"{marks} {mark_label}")

            criteria = band.get("criteria", [])
            if isinstance(criteria, list):
                for criterion in criteria:
                    lines.append(f"- {criterion}")
            elif criteria:
                lines.append(f"- {criteria}")
            lines.append("")

        if rubric_payload.get("grading_notes"):
            lines.append("Notes")
            lines.append(f"- {rubric_payload['grading_notes']}")

        # Remove trailing blank lines.
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)

    return json.dumps(rubric_payload, indent=2)


def flatten_newlines_for_single_line_input(text_value):
    text = str(text_value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n\n", " || ")
    text = text.replace("\n", " | ")
    return " ".join(text.split()).strip()


def build_rubric_html(rubric_payload):
    if not isinstance(rubric_payload, dict):
        return None

    if rubric_payload.get("format") == "banded" and isinstance(rubric_payload.get("bands"), list):
        rows = []
        for band in rubric_payload.get("bands", []):
            marks = html.escape(str(band.get("marks", "")).strip())
            criteria_items = band.get("criteria", [])
            if isinstance(criteria_items, list):
                items = [f"<li>{html.escape(str(item))}</li>" for item in criteria_items if str(item).strip()]
            elif criteria_items:
                items = [f"<li>{html.escape(str(criteria_items))}</li>"]
            else:
                items = []

            criteria_html = f"<ul>{''.join(items)}</ul>" if items else ""
            rows.append(f"<tr><td>{criteria_html}</td><td>{marks}</td></tr>")

        parts = [
            "<p><strong>Rubric</strong></p>",
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%;'>",
            "<thead><tr><th>Criteria</th><th>Marks</th></tr></thead>",
            f"<tbody>{''.join(rows)}</tbody>",
            "</table>",
        ]

        grading_notes = str(rubric_payload.get("grading_notes", "")).strip()
        if grading_notes:
            parts.append(f"<p><strong>Notes</strong><br/>{html.escape(grading_notes)}</p>")

        return "".join(parts)

    return None


def preserve_leading_indent(line):
    expanded = line.expandtabs(4)
    stripped = expanded.lstrip(" ")
    return "&nbsp;" * (len(expanded) - len(stripped)) + stripped


def build_answer_options_html(rubric_text, answer_text, rubric_is_html=False):
    parts = []
    if str(rubric_text or "").strip():
        if rubric_is_html:
            parts.append(str(rubric_text).strip())
        else:
            rubric_lines = html.escape(str(rubric_text).strip()).splitlines()
            rubric_html = "<br/>".join(line for line in rubric_lines if line is not None)
            parts.append("<p><strong>Rubric</strong></p>")
            parts.append(f"<p>{rubric_html}</p>")

    if str(answer_text or "").strip():
        parts.append("<p><strong>Sample answer</strong></p>")
        sample_lines = html.escape(str(answer_text or "").strip()).splitlines()
        # Keep leading indentation (e.g. Python code) which HTML would otherwise collapse.
        sample_html = "<br/>".join(preserve_leading_indent(line) for line in sample_lines if line is not None)
        parts.append(f"<p>{sample_html}</p>")
    return "".join(parts)


def coerce_answer_text(value):
    if value is None:
        return None
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(lines) if lines else None
    text = str(value).strip()
    return text or None


def normalize_for_editor_match(text):
    """Normalize text for comparison with editor inner_text.
    Strips excess whitespace, collapses newlines, and removes predictable artifacts.
    """
    if not text:
        return ""
    # Collapse all whitespace sequences into a single space.
    return " ".join(str(text).split()).strip()


def extract_question_fields(
    payload,
    default_question_type,
    default_question_text,
    default_answer_text,
    default_rubric_text,
    default_list_match_pairs,
    default_points,
):
    question_type = default_question_type
    question_text = default_question_text
    answer_text = default_answer_text
    rubric_text = default_rubric_text
    rubric_is_html = False
    list_match_pairs = default_list_match_pairs
    points = default_points

    if not isinstance(payload, dict):
        return question_type, question_text, answer_text, rubric_text, rubric_is_html, list_match_pairs, points

    question_type = payload.get("question_type", question_type)
    question_text = payload.get("question_text", question_text)

    answer_options = payload.get("answer_options") or {}
    if isinstance(answer_options, dict):
        option_answer = coerce_answer_text(answer_options.get("sample_answer"))
        if option_answer is not None:
            answer_text = option_answer
        rubric_payload = answer_options.get("rubric", rubric_text)
    else:
        rubric_payload = rubric_text

    for answer_key in ("sample_answer", "model_answer", "answer", "answers"):
        payload_answer = coerce_answer_text(payload.get(answer_key))
        if payload_answer is not None:
            answer_text = payload_answer
            break

    if isinstance(rubric_payload, str) or rubric_payload is None:
        rubric_text = rubric_payload
    else:
        rubric_html = build_rubric_html(rubric_payload)
        if rubric_html:
            rubric_text = rubric_html
            rubric_is_html = True
        else:
            rubric_text = format_rubric_plain_text(rubric_payload)

    mark_payload = payload.get("mark") or {}
    if isinstance(mark_payload, dict):
        points = mark_payload.get("points", points)

    if isinstance(payload.get("pairs"), list):
        list_match_pairs = payload.get("pairs")
    elif isinstance(payload.get("matches"), list):
        list_match_pairs = payload.get("matches")
    elif isinstance(payload.get("list_match_pairs"), list):
        list_match_pairs = payload.get("list_match_pairs")

    # Add suggested word count if present
    swc = payload.get("suggested_word_count")
    if isinstance(swc, (int, float, str)):
        recommended = swc
        if recommended:
            question_text = f"{question_text}\n\nSuggested Word Count\n{recommended}"
    elif isinstance(swc, dict):
        recommended = swc.get("recommended")
        if recommended:
            question_text = f"{question_text}\n\nSuggested Word Count\n{recommended}"

    return question_type, question_text, answer_text, rubric_text, rubric_is_html, list_match_pairs, points


def normalize_question_payloads(raw_payload):
    if isinstance(raw_payload, list):
        return raw_payload
    if isinstance(raw_payload, dict):
        questions = raw_payload.get("questions")
        if isinstance(questions, list):
            return questions
        problems = raw_payload.get("problems")
        if isinstance(problems, list):
            return problems
        return [raw_payload]
    raise ValueError("JSON payload must be an object, an array of objects, or an object with a 'questions'/'problems' array.")


def main():
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    question_text = args.question_text
    answer_text = args.answer_text
    rubric_text = args.rubric_text
    rubric_is_html = False
    question_type = "long_answer"
    list_match_pairs = []
    points = args.points

    question_payloads = None

    if args.json_file:
        with open(args.json_file, "r", encoding="utf-8-sig") as f:
            raw_payload = json.load(f)
        question_payloads = normalize_question_payloads(raw_payload)
        if question_payloads:
            question_type, question_text, answer_text, rubric_text, rubric_is_html, list_match_pairs, points = extract_question_fields(
                question_payloads[0],
                question_type,
                question_text,
                answer_text,
                rubric_text,
                list_match_pairs,
                points,
            )

    probe = LongAnswerProbe(
        browser_url=args.browser_url,
        interactive=not args.non_interactive,
        log_level=args.log_level,
        ready_timeout=args.ready_timeout,
        question_type=question_type,
        question_text=question_text,
        answer_text=answer_text,
        rubric_text=rubric_text,
        rubric_is_html=rubric_is_html,
        list_match_pairs=list_match_pairs,
        points=points,
    )
    if args.answer_options_smoke:
        probe.run_answer_options_smoke(args.answer_options_html)
    elif args.code_view_roundtrip_only:
        probe.run_code_view_roundtrip_only(args.answer_options_html)
    elif args.click_code_view_only:
        probe.run_click_code_view_only()
    elif args.click_answer_toggle_only:
        probe.run_click_answer_toggle_only()
    elif args.points_only:
        probe.run_points_only()
    elif question_payloads and len(question_payloads) > 1:
        probe.run_many(question_payloads)
    else:
        probe.run()


if __name__ == "__main__":
    main()
