from long_answer_probe import extract_question_fields

LONG_ANSWER_TYPES = {"long_answer", "free_text", "freetext"}


def validate_long_answer(question, idx_label, is_non_empty_string, validate_points):
    errors = []

    question_text = question.get("question_text", question.get("question"))
    if not is_non_empty_string(question_text):
        errors.append(f"{idx_label}: long_answer requires non-empty 'question_text' (or 'question').")

    answer_options = question.get("answer_options")
    if answer_options is not None and not isinstance(answer_options, dict):
        errors.append(f"{idx_label}: 'answer_options' must be an object when provided.")
    elif isinstance(answer_options, dict):
        if "sample_answer" in answer_options and not is_non_empty_string(answer_options.get("sample_answer")):
            errors.append(f"{idx_label}: 'answer_options.sample_answer' must be a non-empty string when provided.")

    for answer_key in ("sample_answer", "model_answer", "answer"):
        if answer_key in question and not is_non_empty_string(question.get(answer_key)):
            errors.append(f"{idx_label}: '{answer_key}' must be a non-empty string when provided.")

    if "answers" in question:
        answers = question.get("answers")
        if not isinstance(answers, list) or not answers:
            errors.append(f"{idx_label}: 'answers' must be a non-empty array when provided.")
        elif any(not is_non_empty_string(answer) for answer in answers):
            errors.append(f"{idx_label}: every item in 'answers' must be a non-empty string.")

    validate_points(question, errors, idx_label)

    swc = question.get("suggested_word_count")
    if swc is not None:
        if isinstance(swc, (int, float, str)):
            pass
        elif not isinstance(swc, dict):
            errors.append(f"{idx_label}: 'suggested_word_count' must be an object, number, or string when provided.")
        elif "recommended" in swc and not isinstance(swc.get("recommended"), (int, float, str)):
            # We don't strictly require it to be a number since it might be a range string, 
            # but it should be a basic type.
            errors.append(f"{idx_label}: 'suggested_word_count.recommended' must be a number or string.")

    return errors


def process_long_answer_question(automator, payload, normalized_type):
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


# Python program questions are free-text questions that students answer in exam.net's
# built-in programming tool. They never show a suggested word count.
PYTHON_PROGRAM_TYPES = {"python_program", "python_programming", "python", "programming"}
PYTHON_PROGRAM_REMINDER = (
    "STUDENTS MUST OPEN THE PROGRAMMING TOOL ON THE LEFT OF THE SCREEN TO COMPLETE THIS QUESTION"
)


def validate_python_program(question, idx_label, is_non_empty_string, validate_points):
    return [
        error.replace("long_answer requires", "python_program requires")
        for error in validate_long_answer(question, idx_label, is_non_empty_string, validate_points)
    ]


def build_python_program_payload(payload):
    long_answer_payload = dict(payload)
    long_answer_payload.pop("suggested_word_count", None)
    question_text = long_answer_payload.pop("question_text", None) or long_answer_payload.pop("question", "")
    long_answer_payload["question_text"] = f"{question_text.rstrip()}\n\n{PYTHON_PROGRAM_REMINDER}"
    long_answer_payload["question_type"] = "long_answer"
    return long_answer_payload


def process_python_program_question(automator, payload, normalized_type):
    process_long_answer_question(automator, build_python_program_payload(payload), "long_answer")
