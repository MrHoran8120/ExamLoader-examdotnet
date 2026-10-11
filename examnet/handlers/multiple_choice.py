import time

MULTIPLE_CHOICE_TYPES = {
    "multiple_choice",
    "multiplechoice",
    "multiple_select",
    "multipleselect",
    "multi_select",
    "mcq",
    "multi_answer",
    "multianswer",
}


def _get_active_answer_options_scope(automator):
    scope_selectors = [
        'div.accordion.answer-options:visible',
        '[data-testid="sub-question-answers"]:visible',
        '.MultipleChoiceAnswerOptions:visible',
        'div[class*="AnswerOptions"]:visible',
    ]
    for selector in scope_selectors:
        try:
            scopes = automator.page.locator(selector)
            count = scopes.count()
        except Exception:
            count = 0
        if count == 0:
            continue

        for i in range(count - 1, -1, -1):
            scope = scopes.nth(i)
            try:
                editor_count = scope.locator('div.fr-element.fr-view[contenteditable="true"]:visible').count()
            except Exception:
                editor_count = 0
            if editor_count > 0:
                return scope
    return automator.page.locator("body")


def validate_multiple_choice(question, idx_label, is_non_empty_string, validate_points):
    errors = []

    if not is_non_empty_string(question.get("question")):
        errors.append(f"{idx_label}: multiple_choice requires non-empty 'question'.")

    options = question.get("options")
    if not isinstance(options, list) or len(options) < 2:
        errors.append(f"{idx_label}: multiple_choice requires 'options' as an array with at least 2 entries.")
    else:
        invalid_options = [opt for opt in options if not is_non_empty_string(opt)]
        if invalid_options:
            errors.append(f"{idx_label}: every item in 'options' must be a non-empty string.")

    has_answer = "answer" in question
    has_answers = "answers" in question
    if has_answer and has_answers:
        errors.append(f"{idx_label}: provide only one of 'answer' or 'answers', not both.")
    if not has_answer and not has_answers:
        errors.append(f"{idx_label}: multiple_choice requires 'answer' or 'answers'.")

    option_set = set(opt.strip().lower() for opt in options) if isinstance(options, list) else set()
    if has_answer:
        answer = question.get("answer")
        if not is_non_empty_string(answer):
            errors.append(f"{idx_label}: 'answer' must be a non-empty string.")
        elif option_set and answer.strip().lower() not in option_set:
            errors.append(f"{idx_label}: 'answer' must match one of the provided 'options'.")

    if has_answers:
        answers = question.get("answers")
        if not isinstance(answers, list) or not answers:
            errors.append(f"{idx_label}: 'answers' must be a non-empty array of strings.")
        else:
            bad = [a for a in answers if not is_non_empty_string(a)]
            if bad:
                errors.append(f"{idx_label}: every item in 'answers' must be a non-empty string.")
            elif option_set:
                missing = [a for a in answers if a.strip().lower() not in option_set]
                if missing:
                    errors.append(
                        f"{idx_label}: all items in 'answers' must match provided 'options'. "
                        f"Not found: {missing}"
                    )

    validate_points(question, errors, idx_label)
    return errors


def _add_options(automator, options):
    scope = _get_active_answer_options_scope(automator)

    def get_answer_input_editor():
        selectors = [
            'div.fr-element.fr-view[contenteditable="true"]:visible',
            'div.fr-element[contenteditable="true"]:visible',
        ]
        for selector in selectors:
            try:
                editors = scope.locator(selector)
                count = editors.count()
            except Exception:
                count = 0
            if count > 0:
                return editors.nth(count - 1)

        raise RuntimeError("Could not find the multiple-choice answer input editor.")

    def set_answer_input_value(editor, value):
        try:
            editor.wait_for(state="visible", timeout=5000)
            editor.click(timeout=2000)
            editor.fill(value, timeout=3000)
        except Exception:
            editor.evaluate(
                """(el, text) => {
                    if (typeof el.focus === 'function') el.focus();
                    el.innerHTML = '';
                    const div = document.createElement('div');
                    div.textContent = text;
                    el.appendChild(div);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'End' }));
                }""",
                value,
            )
        automator.page.wait_for_timeout(200)

    def click_add_answer():
        selectors = [
            'button:has-text("Add answer"):visible',
            '[role="button"]:has-text("Add answer"):visible',
            'button:has-text("Add answer")',
            '[role="button"]:has-text("Add answer")',
        ]
        last_error = None
        for selector in selectors:
            try:
                target = scope.locator(selector).first
                if target.count() == 0:
                    continue
                target.wait_for(state="visible", timeout=3000)
                target.click(timeout=3000, force=True)
                return
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Could not click 'Add answer'. Last error: {last_error}")

    def get_option_containers():
        selectors = [
            'div.OptionRow.animation:visible',
            'div.OptionRow.animation',
        ]
        for selector in selectors:
            containers = scope.locator(selector)
            try:
                count = containers.count()
            except Exception:
                count = 0
            if count > 0:
                return containers
        return scope.locator('div.OptionRow.animation')

    def read_option_texts():
        texts = []
        containers = get_option_containers()
        for i in range(containers.count()):
            container = containers.nth(i)
            label = container.locator(".MultipleChoiceAnswerOptions__option-label")
            try:
                texts.append(label.inner_text(timeout=1500).strip())
            except Exception:
                texts.append("")
        return texts

    for idx, option in enumerate(options, start=1):
        before_count = len(read_option_texts())
        editor = get_answer_input_editor()
        set_answer_input_value(editor, option)
        click_add_answer()

        deadline = time.time() + 4
        added = False
        while time.time() < deadline:
            current_texts = read_option_texts()
            if len(current_texts) >= before_count + 1 and option.strip().lower() in {
                text.strip().lower() for text in current_texts
            }:
                added = True
                break
            automator.page.wait_for_timeout(150)

        if not added:
            raise RuntimeError(
                f"Failed to add multiple-choice option {idx}/{len(options)}: {option}"
            )

        automator.logger.debug("Added option %s/%s via answer-input workflow: %s", idx, len(options), option)

    entered_texts = read_option_texts()[: len(options)]
    normalized_entered = [text.strip().lower() for text in entered_texts]
    normalized_expected = [text.strip().lower() for text in options]
    if normalized_entered != normalized_expected:
        raise RuntimeError(
            "Entered multiple-choice options do not match JSON order/content. "
            f"Expected={options} Entered={entered_texts}"
        )


def _set_selection_mode(automator, single_select=True, idx=None, question=None):
    automator.page.wait_for_timeout(500)
    target_label = "single select" if single_select else "multiple select"
    idx_str = f"Question {idx}" if idx is not None else "Question unknown"

    def locate_mode_row():
        row_selectors = [
            "xpath=//div[contains(@class,'icon-toggle')][.//i[contains(normalize-space(.),'Multiple select') or contains(normalize-space(.),'Single select')]]",
            "xpath=//div[contains(@class,'icon-toggle')][contains(normalize-space(.),'Multiple select') or contains(normalize-space(.),'Single select')]",
        ]
        for row_selector in row_selectors:
            try:
                candidate = automator.page.locator(row_selector).first
                if candidate.count() > 0:
                    candidate.wait_for(state="visible", timeout=3000)
                    return candidate
            except Exception:
                continue
        return None

    if locate_mode_row() is None:
        automator.logger.warning("[%s] Could not find selection-mode toggle row for '%s'.", idx_str, target_label)
        return single_select

    desired_index = 1 if single_select else 0

    def get_selected_index():
        row = locate_mode_row()
        if row is None:
            return None
        selected = row.locator(".icon-toggle__icon.icon-toggle__icon--selected")
        if selected.count() == 0:
            return None
        try:
            return selected.first.evaluate(
                """(el) => {
                    const icons = Array.from(el.parentElement.querySelectorAll('.icon-toggle__icon'));
                    return icons.indexOf(el);
                }"""
            )
        except Exception:
            return None

    current_index = get_selected_index()
    if current_index == desired_index:
        automator.logger.debug("%s mode already active.", target_label.title())
        return True

    row = locate_mode_row()
    if row is None:
        automator.logger.warning("[%s] Could not reacquire selection-mode toggle row for '%s'.", idx_str, target_label)
        return False

    target_icon = row.locator(".icon-toggle__icon").nth(desired_index)
    click_error = None
    try:
        target_icon.scroll_into_view_if_needed()
        target_icon.click(timeout=4000, force=True)
    except Exception as e:
        click_error = e
        try:
            box = target_icon.bounding_box()
            if box:
                automator.page.mouse.click(box["x"] + (box["width"] / 2), box["y"] + (box["height"] / 2))
            else:
                raise click_error
        except Exception:
            automator.logger.warning(
                "Could not switch mode to %s; click_error=%s",
                target_label,
                click_error,
            )
            return False

    automator.page.wait_for_timeout(250)
    current_index = get_selected_index()
    if current_index == desired_index:
        automator.logger.debug("Switched mode to %s.", target_label)
        return True

    automator.logger.warning(
        "Attempted to switch mode to %s, but selected index is still %s.",
        target_label,
        current_index,
    )
    return False

    # If no toggle is found, avoid blocking. On current Exam.net UI, single-select
    # is often the default for new multiple-choice questions.
    if single_select:
        automator.logger.info(
            "[%s] Selection-mode toggle not found; assuming default single-select mode and continuing.",
            idx_str,
        )
        return True

    automator.logger.warning(
        "[%s] Selection-mode toggle not found for multiple-select question; continuing without mode switch.",
        idx_str,
    )
    return False


def _mark_correct_option(automator, correct_answers, expected_count):
    scope = _get_active_answer_options_scope(automator)
    if not isinstance(correct_answers, list):
        correct_answers = [correct_answers]

    normalized_correct_answers = [ans.strip().lower() for ans in correct_answers]
    scope.locator("div.OptionRow.animation").first.wait_for(timeout=30000)
    option_containers = scope.locator("div.OptionRow.animation:visible")
    count = option_containers.count()
    if count == 0:
        option_containers = scope.locator("div.OptionRow.animation")
        count = option_containers.count()
    if count != expected_count:
        automator.logger.debug(
            "Expected %s options based on JSON but found %s visible option container(s).",
            expected_count,
            count,
        )

    marked_count = 0
    missing_answers = set(normalized_correct_answers)

    for i in range(count):
        container = option_containers.nth(i)
        option_label = container.locator(".MultipleChoiceAnswerOptions__option-label")
        try:
            option_text = option_label.inner_text().strip()
        except Exception:
            option_text = ""
        normalized_option_text = option_text.lower()

        if normalized_option_text in normalized_correct_answers:
            toggle_button = container.locator('[data-testid="correct-answer-toggle"] input[type="checkbox"]')
            try:
                toggle_button.wait_for(state="attached", timeout=10000)
            except Exception as e:
                automator.logger.debug("Correct-answer toggle did not reach attached state: %s", e)

            if not toggle_button.is_checked():
                try:
                    toggle_button.click(force=True)
                    marked_count += 1
                    if normalized_option_text in missing_answers:
                        missing_answers.remove(normalized_option_text)
                except Exception as click_e:
                    raise RuntimeError(
                        f"Error clicking correct-answer toggle for option '{option_text}': {click_e}"
                    ) from click_e
            else:
                marked_count += 1
                if normalized_option_text in missing_answers:
                    missing_answers.remove(normalized_option_text)

    if missing_answers:
        message = (
            f"The following correct answer option(s) from JSON were not found among the "
            f"{count} containers on the page: {missing_answers}"
        )
        raise RuntimeError(message)

    if marked_count != len(normalized_correct_answers):
        automator.logger.warning(
            "Marked %s correct options, but expected %s.",
            marked_count,
            len(normalized_correct_answers),
        )


def process_multiple_choice_question(automator, question, idx=None):
    type_clicked = False
    click_errors = []
    type_selectors = [
        '[data-testid="select-multipleChoice"]:visible',
        '[role="button"][data-testid="select-multipleChoice"]:visible',
        '[role="button"]:has-text("Multiple choice"):visible',
        'button:has-text("Multiple choice"):visible',
    ]

    # Important: open chooser only once per question. Re-opening on every retry can
    # create duplicate questions if a partial click succeeded.
    automator.click_create_question()

    for click_cycle in range(1, 4):
        for selector in type_selectors:
            try:
                target = automator.page.locator(selector).first
                target.wait_for(state="visible", timeout=2000)

                # Forceful scroll via JS for reliability in modals
                try:
                    target.evaluate("el => el.scrollIntoView({block: 'center'})")
                except Exception:
                    pass

                # Attempt standard click with force
                try:
                    target.click(timeout=2000, force=True)
                except Exception:
                    # A successful SPA transition can detach the chooser card before
                    # Playwright considers the click complete. Treat a visible editor
                    # as success instead of waiting on the now-detached card.
                    if not automator.is_question_editor_open():
                        # Keep this timeout short: the chooser card may disappear as
                        # soon as the question editor starts opening.
                        box = target.bounding_box(timeout=1500)
                        if box:
                            automator.page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )

                automator.page.wait_for_timeout(300) # Give it a moment to render
                automator.page.wait_for_selector(
                    '[data-testid="question-formulation-input"]',
                    state="visible",
                    timeout=8000,
                )
                automator.logger.debug("Selected multiple choice question type.")
                type_clicked = True
                break
            except Exception as e:
                click_errors.append(f"cycle {click_cycle} {selector}: {e}")

        if type_clicked:
            break

        # If chooser disappeared, stop instead of clicking "Create question" again.
        # The caller will handle retry policy.
        try:
            if not automator.is_question_type_chooser_open():
                break
        except Exception:
            break

        automator.logger.debug("Multiple-choice type click cycle %s failed; retrying selector set.", click_cycle)
        automator.page.wait_for_timeout(180)

    if not type_clicked:
        raise RuntimeError(
            "Could not open multiple-choice editor after clicking question type. "
            f"Attempts: {' | '.join(click_errors)}"
        )

    if "answer" in question:
        correct_answers = question["answer"]
        single_select = True
        automator.logger.debug("Found 'answer' key (single correct answer).")
    elif "answers" in question:
        correct_answers = question["answers"]
        single_select = False
        automator.logger.debug("Found 'answers' key (multiple correct answers).")
    else:
        raise ValueError(f"Question is missing both 'answer' and 'answers' keys: {question}")

    _set_selection_mode(automator, single_select=single_select, idx=idx, question=question)
    automator.page.wait_for_selector('[data-testid="question-formulation-input"]', state="visible", timeout=30000)
    automator.fill_question_text(question["question"])
    _add_options(automator, question["options"])
    _mark_correct_option(automator, correct_answers, len(question["options"]))
    automator.save_question()
