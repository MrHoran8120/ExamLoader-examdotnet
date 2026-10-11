from long_answer_probe import extract_question_fields

LIST_MATCH_TYPES = {"list_match", "match_list"}


def validate_list_match(question, idx_label, is_non_empty_string, validate_points):
    errors = []

    question_text = question.get("question_text", question.get("question"))
    if not is_non_empty_string(question_text):
        errors.append(f"{idx_label}: list_match requires non-empty 'question_text' (or 'question').")

    pairs = question.get("pairs")
    if not isinstance(pairs, list):
        if isinstance(question.get("matches"), list):
            pairs = question.get("matches")
        elif isinstance(question.get("list_match_pairs"), list):
            pairs = question.get("list_match_pairs")

    if not isinstance(pairs, list) or not pairs:
        errors.append(f"{idx_label}: list_match requires non-empty 'pairs' (or 'matches'/'list_match_pairs').")
    else:
        for pair_index, pair in enumerate(pairs, start=1):
            if not isinstance(pair, dict):
                errors.append(f"{idx_label}: pair {pair_index} must be an object.")
                continue
            if not is_non_empty_string(pair.get("left")):
                errors.append(f"{idx_label}: pair {pair_index} requires non-empty 'left'.")
            if not is_non_empty_string(pair.get("right")):
                errors.append(f"{idx_label}: pair {pair_index} requires non-empty 'right'.")

    validate_points(question, errors, idx_label)
    return errors


def process_list_match_question(automator, payload, normalized_type):
    # Use the shared create-click routine to avoid duplicate blank questions.
    automator.click_create_question()

    probe = automator.get_long_answer_probe()
    default_question_text = payload.get("question_text") or payload.get("question") or "Question text"
    (
        question_type,
        question_text,
        answer_text,
        rubric_text,
        rubric_is_html,
        list_match_pairs,
        points,
    ) = extract_question_fields(
        payload,
        normalized_type,
        default_question_text,
        "Sample answer",
        None,
        [],
        None,
    )

    probe.question_type = question_type
    probe.question_text = question_text
    probe.answer_text = answer_text
    probe.rubric_text = rubric_text
    probe.rubric_is_html = rubric_is_html
    probe.list_match_pairs = list_match_pairs
    probe.points = points
    probe._run_payload_by_type(question_type, list_match_pairs, skip_create_question=True)

    automator.context = probe.context
    automator.page = probe.page
