FILL_GAPS_TYPES = {"fill_gaps", "fillgaps", "fill_in_the_gaps", "fill_in_gaps"}


def validate_fill_gaps(question, idx_label, is_non_empty_string, validate_points):
    errors = []

    question_text = question.get("question_text", question.get("question"))
    if not is_non_empty_string(question_text):
        errors.append(f"{idx_label}: fill_gaps requires non-empty 'question_text' (or 'question').")

    gaps = question.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        errors.append(f"{idx_label}: fill_gaps requires non-empty 'gaps' array.")
    else:
        for gap_idx, gap in enumerate(gaps, start=1):
            if isinstance(gap, str):
                if not is_non_empty_string(gap):
                    errors.append(f"{idx_label}: gap {gap_idx} must be a non-empty string.")
                continue

            if not isinstance(gap, dict):
                errors.append(f"{idx_label}: gap {gap_idx} must be a string or object.")
                continue

            if is_non_empty_string(gap.get("answer")):
                continue

            answers = gap.get("answers")
            if isinstance(answers, list) and any(is_non_empty_string(a) for a in answers):
                continue

            errors.append(f"{idx_label}: gap {gap_idx} requires 'answer' or non-empty 'answers'.")

    validate_points(question, errors, idx_label)
    return errors


def _normalize_gap_answers(gaps):
    normalized = []
    for gap in gaps:
        if isinstance(gap, str):
            normalized.append(gap.strip())
            continue
        if not isinstance(gap, dict):
            continue
        answer = gap.get("answer")
        if isinstance(answer, str) and answer.strip():
            normalized.append(answer.strip())
            continue
        answers = gap.get("answers")
        if isinstance(answers, list):
            first = next((a.strip() for a in answers if isinstance(a, str) and a.strip()), None)
            if first:
                normalized.append(first)
    return normalized


def _normalize_word_bank_extras(question):
    extras = []
    for key in ("word_bank_extra", "word_bank_extras", "distractors", "additional_incorrect_answers"):
        value = question.get(key)
        if isinstance(value, list):
            extras.extend([str(v).strip() for v in value if isinstance(v, str) and str(v).strip()])
    # Keep order, drop duplicates (case-insensitive).
    deduped = []
    seen = set()
    for item in extras:
        k = item.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(item)
    return deduped


def build_word_bank_text(question, answers):
    """Word bank shown as text above the question: correct answers plus distractors,
    de-duplicated and sorted so their order gives nothing away.

    exam.net fill-gaps questions have no built-in word bank, so it is printed in the question.
    """
    extras = _normalize_word_bank_extras(question)
    if question.get("word_bank_enabled") is False:
        return None
    if not extras and question.get("word_bank_enabled") is not True:
        return None
    words = {}
    for word in list(answers) + extras:
        words.setdefault(word.lower(), word)
    ordered = sorted(words.values(), key=str.lower)
    return "Word bank: " + " | ".join(ordered)


def _click_fill_gaps_type(automator):
    # Primary selector from the question-type card in Exam.net.
    primary = automator.page.get_by_test_id("select-fillGaps").first
    try:
        primary.wait_for(state="visible", timeout=5000)
        primary.scroll_into_view_if_needed()
        primary.click(timeout=5000)
        automator.logger.debug("Selected fill-gaps question type using test id 'select-fillGaps'.")
        return
    except Exception as primary_error:
        automator.logger.debug("Primary fill-gaps selector failed: %s", primary_error)

    selectors = [
        '[data-testid="select-fillGaps"][role="button"]',
        '[data-testid="select-fillGaps"]',
        '[role="button"][data-testid*="fillGaps"]',
        '[role="button"]:has-text("Fill the gaps")',
        '[role="button"]:has-text("Fill gaps")',
        'button:has-text("Fill the gaps")',
        'button:has-text("Fill gaps")',
    ]
    last_error = None
    for selector in selectors:
        try:
            target = automator.page.locator(selector).first
            target.wait_for(state="visible", timeout=4000)
            target.scroll_into_view_if_needed()
            target.click(timeout=5000)
            automator.logger.debug("Selected fill-gaps question type using selector '%s'.", selector)
            return
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Could not select fill-gaps question type. Last error: {last_error}")


def _fill_gap_answers(automator, gaps, word_bank_text=None):
    answers = _normalize_gap_answers(gaps)
    if not answers:
        return

    editor_selector = '[data-testid="question-formulation-input"] div.fr-element.fr-view[contenteditable="true"]'
    add_gap_selectors = [
        'button[aria-label="Add gap"]',
        'button:has-text("Add gap")',
        'div.FillGaps__addGap button',
    ]

    automator.page.wait_for_selector(editor_selector, timeout=30000)
    min_start = 0
    if word_bank_text:
        bank_index = automator.page.evaluate(
            """({ editorSelector, bank }) => {
                const root = document.querySelector(editorSelector);
                if (!root) return -1;
                return String(root.textContent || "").toLowerCase().indexOf(bank.toLowerCase());
            }""",
            {"editorSelector": editor_selector, "bank": word_bank_text},
        )
        if bank_index < 0:
            raise RuntimeError("Could not find the word bank text in the question editor.")
        min_start = bank_index + len(word_bank_text)
    search_start = min_start

    for idx, answer in enumerate(answers, start=1):
        result = automator.page.evaluate(
            """({ editorSelector, needle, startIndex, minStart }) => {
                const root = document.querySelector(editorSelector);
                if (!root) return { ok: false, error: "editor_not_found" };

                const fullText = String(root.textContent || "");
                const source = fullText.toLowerCase();
                const target = String(needle || "").toLowerCase();
                if (!target) return { ok: false, error: "empty_target" };

                // Never search inside the word bank at the top of the question.
                const floor = minStart || 0;
                let matchIndex = source.indexOf(target, Math.max(startIndex || 0, floor));
                if (matchIndex < 0 && (startIndex || 0) > floor) {
                    matchIndex = source.indexOf(target, floor);
                }
                if (matchIndex < 0) {
                    return { ok: false, error: "text_not_found", target: needle };
                }

                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                let node = null;
                let offset = 0;
                let startNode = null;
                let startOffset = 0;
                let endNode = null;
                let endOffset = 0;
                const endIndex = matchIndex + target.length;

                while ((node = walker.nextNode())) {
                    const t = String(node.textContent || "");
                    const nextOffset = offset + t.length;

                    if (!startNode && matchIndex <= nextOffset) {
                        startNode = node;
                        startOffset = Math.max(0, matchIndex - offset);
                    }
                    if (!endNode && endIndex <= nextOffset) {
                        endNode = node;
                        endOffset = Math.max(0, endIndex - offset);
                        break;
                    }
                    offset = nextOffset;
                }

                if (!startNode || !endNode) {
                    return { ok: false, error: "range_resolution_failed", target: needle };
                }

                const range = document.createRange();
                range.setStart(startNode, startOffset);
                range.setEnd(endNode, endOffset);

                const sel = window.getSelection();
                if (!sel) return { ok: false, error: "selection_api_unavailable" };
                sel.removeAllRanges();
                sel.addRange(range);

                if (typeof root.focus === "function") root.focus();
                return { ok: true, index: matchIndex, nextStart: endIndex };
            }""",
            {"editorSelector": editor_selector, "needle": answer, "startIndex": search_start, "minStart": min_start},
        )

        if not result.get("ok"):
            raise RuntimeError(
                f"Could not select fill-gaps answer {idx} ('{answer}'). "
                f"Reason: {result.get('error')}"
            )

        clicked = False
        last_error = None
        for selector in add_gap_selectors:
            try:
                btn = automator.page.locator(selector).first
                btn.wait_for(state="visible", timeout=3000)
                btn.click(timeout=3000)
                clicked = True
                break
            except Exception as e:
                last_error = e

        if not clicked:
            raise RuntimeError(
                f"Selected '{answer}' but failed to click Add gap button. Last error: {last_error}"
            )

        search_start = int(result.get("nextStart", 0))
        automator.logger.debug("Added fill-gaps answer %s/%s: %s", idx, len(answers), answer)
        automator.page.wait_for_timeout(200)


def process_fill_gaps_question(automator, question, normalized_type):
    _ = normalized_type
    automator.click_create_question()
    _click_fill_gaps_type(automator)

    prompt = question.get("question_text", question.get("question"))
    gaps = question.get("gaps", [])
    answers = _normalize_gap_answers(gaps)

    # Reconstruct full text if placeholders are used
    if "___" in prompt and answers:
        for ans in answers:
            # Replace each placeholder with subsequent gap answers
            prompt = prompt.replace("___", ans, 1)

    word_bank_text = build_word_bank_text(question, answers)
    if word_bank_text:
        prompt = f"{word_bank_text}\n\n{prompt}"

    automator.page.wait_for_selector('[data-testid="question-formulation-input"]', timeout=30000)
    automator.fill_question_text(prompt)

    _fill_gap_answers(automator, gaps, word_bank_text)
    automator.save_question()
