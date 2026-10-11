import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime


def build_parser():
    parser = argparse.ArgumentParser(description="Automate exam.net question creation for multiple question types from JSON.")
    parser.add_argument("--json-file", default="questions.json", help="Path to questions JSON file.")
    parser.add_argument("--browser-url", default="http://127.0.0.1:9222", help="Chrome CDP URL.")
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print an example JSON schema/payload for supported question types and exit.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable prompts. Fails if login/setup is still required.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional explicit log file path. If omitted, a timestamped file is created in ./logs/.",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable writing log output to a file.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=1,
        help="Maximum attempts per question. Keep at 1 to avoid duplicate questions on flaky pages.",
    )
    parser.add_argument(
        "--debug-create-preview",
        action="store_true",
        help="Highlight the chosen 'Create question' button before clicking it.",
    )
    parser.add_argument(
        "--debug-create-preview-ms",
        type=int,
        default=5000,
        help="Pause duration in ms while highlighted before clicking 'Create question'.",
    )
    parser.add_argument(
        "--debug-create-confirm",
        action="store_true",
        help="Show a confirmation prompt before each 'Create question' click.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue processing later questions after a failure (can cause apparent order shifts).",
    )
    parser.add_argument(
        "--allow-existing-questions",
        action="store_true",
        help="Allow running on an exam that already contains questions.",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="Start at this 1-based question index (use with --allow-existing-questions to resume a partial run).",
    )
    parser.add_argument(
        "--bypass-json-precheck",
        action="store_true",
        help="Skip strict JSON precheck and continue directly to processing.",
    )
    return parser


def build_question_schema():
    return [
        {
            "question_id": "MC-001",
            "question_type": "multiple_choice",
            "question": "<Write the multiple-choice question>",
            "options": [
                "<Option A>",
                "<Option B>",
                "<Option C>",
                "<Option D>",
            ],
            "answer": "<One correct option exactly matching one item in options>",
            "mark": {
                "points": 1,
            },
        },
        {
            "question_id": "MC-002",
            "question_type": "multiple_choice",
            "question": "<Write a multi-select question>",
            "options": [
                "<Option 1>",
                "<Option 2>",
                "<Option 3>",
                "<Option 4>",
            ],
            "answers": [
                "<Correct option 1>",
                "<Correct option 2>",
            ],
            "mark": {
                "points": 2,
            },
        },
        {
            "question_id": "LM-001",
            "question_type": "list_match",
            "question_text": "<Write the list match instruction>",
            "pairs": [
                {
                    "left": "<Left item 1>",
                    "right": "<Right item 1>",
                },
                {
                    "left": "<Left item 2>",
                    "right": "<Right item 2>",
                },
            ],
            "mark": {
                "points": 2,
            },
        },
        {
            "question_id": "FG-001",
            "question_type": "fill_gaps",
            "question_text": "<Sentence or paragraph where answers will be used as gaps>",
            "gaps": [
                {
                    "answer": "<Gap answer 1>",
                },
                {
                    "answers": [
                        "<Gap answer 2>",
                        "<Optional alternate answer 2>",
                    ],
                },
            ],
            "word_bank_enabled": True,
            "word_bank_extras": [
                "<Optional incorrect word 1>",
                "<Optional incorrect word 2>",
            ],
            "mark": {
                "points": 2,
            },
        },
        {
            "question_id": "LA-001",
            "question_type": "long_answer",
            "question_text": "<Write the long-answer question>",
            "answer_options": {
                "rubric": {
                    "format": "banded",
                    "bands": [
                        {
                            "marks": 5,
                            "criteria": [
                                "<Top-band criterion 1>",
                                "<Top-band criterion 2>",
                            ],
                        },
                        {
                            "marks": 3,
                            "criteria": [
                                "<Mid-band criterion>",
                            ],
                        },
                        {
                            "marks": 1,
                            "criteria": [
                                "<Low-band criterion>",
                            ],
                        },
                    ],
                },
                "sample_answer": "<Optional high-quality sample answer>",
            },
            "suggested_word_count": {
                "recommended": "400-600",
            },
            "mark": {
                "points": 5,
            },
        },
        {
            "question_id": "PY-001",
            "question_type": "python_program",
            "question_text": "<Describe the Python program students must write>",
            "answer_options": {
                "rubric": "<Optional marking criteria>",
                "sample_answer": "<Optional sample Python solution>",
            },
            "mark": {
                "points": 4,
            },
        },
    ]


def build_question_schema_text():
    lines = ["["]
    questions = build_question_schema()
    for index, question in enumerate(questions):
        suffix = "," if index < len(questions) - 1 else ""
        lines.append(f"  {json.dumps(question, ensure_ascii=False, separators=(',', ':'))}{suffix}")
    lines.append("]")
    return "\n".join(lines)


def copy_to_clipboard(text):
    clipboard_commands = []

    if sys.platform.startswith("win"):
        clipboard_commands.append(["clip"])
    elif sys.platform == "darwin":
        clipboard_commands.append(["pbcopy"])
    else:
        clipboard_commands.extend([
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ])

    for command in clipboard_commands:
        executable = command[0]
        if shutil.which(executable) is None:
            continue
        try:
            subprocess.run(command, input=text, text=True, check=True)
            return True
        except Exception:
            continue

    return False


def print_question_schema():
    schema_text = build_question_schema_text()
    print(schema_text)
    return copy_to_clipboard(schema_text)


def configure_logging(log_level, log_file=None, no_log_file=False):
    level = getattr(logging, log_level)
    formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    handlers = [logging.StreamHandler()]
    handlers[0].setFormatter(formatter)

    file_path = None
    if not no_log_file:
        if log_file:
            file_path = log_file
        else:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            logs_dir = os.path.join(os.getcwd(), "logs")
            os.makedirs(logs_dir, exist_ok=True)
            file_path = os.path.join(logs_dir, f"examnet_{timestamp}.log")

        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)
    return file_path


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.print_schema:
        copied = print_question_schema()
        if copied:
            print("Schema copied to clipboard.", file=sys.stderr)
        else:
            print("Schema printed, but clipboard copy was unavailable.", file=sys.stderr)
        return

    from .automator import ExamNetAutomator

    log_file_path = configure_logging(args.log_level, log_file=args.log_file, no_log_file=args.no_log_file)
    if log_file_path:
        logging.getLogger(__name__).debug("Writing run log to: %s", log_file_path)

    automator = ExamNetAutomator(
        browser_url=args.browser_url,
        json_file=args.json_file,
        interactive=not args.non_interactive,
        max_attempts=args.max_attempts,
        stop_on_error=not args.continue_on_error,
        allow_existing_questions=args.allow_existing_questions,
        start_index=args.start_index,
        debug_create_preview=args.debug_create_preview,
        debug_create_preview_ms=args.debug_create_preview_ms,
        debug_create_confirm=args.debug_create_confirm,
        bypass_json_precheck=args.bypass_json_precheck,
    )
    automator.run()
