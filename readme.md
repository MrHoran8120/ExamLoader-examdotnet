# ExamLoader for Exam.net

ExamLoader loads exam questions from a JSON file into [Exam.net](https://exam.net), using Playwright and a
Chrome (or Microsoft Edge) CDP (remote debugging) connection. It is part of the ExamLoader family of tools for teachers
(see also ExamLoader for Gradeo).

> ExamLoader is an independent tool and is not affiliated with, or endorsed by, Exam.net.

## Overview

* **Launch/Connect to the browser**: Opens Chrome in CDP mode (port 9222), falling back to Microsoft Edge if Chrome
  isn't installed, or connects to an existing session.
* **Read & Validate JSON**: Loads one JSON file that can contain multiple-choice, list-match, and long-answer payloads.
  Invalid payloads fail fast before browser automation starts, with per-question field errors.
* **Automate Question Creation**: Navigates the exam.net UI and creates each question based on `question_type`.
* **Logging and Error Handling**: Uses structured log levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`) and raises runtime errors for blocking failures.

## Prerequisites

* **Python 3.8+**
* **Google Chrome** or **Microsoft Edge** installed on your system. ExamLoader drives your installed browser, so
  Playwright's own browser downloads (`playwright install`) are not needed.

## Installation

1. **Clone or Download** this repository.
2. **Install dependencies** (the Windows launchers do this for you in `.venv`):

   ```bash
   pip install -r requirements.txt
   ```
3. **Ensure** no other process is using port `9222` (or pass a different value with `--browser-url`).

## Where files are saved

ExamLoader writes everything to a per-user folder, never next to the code:

* Windows: `%LOCALAPPDATA%\ExamLoader\` (macOS: `~/Library/Application Support/ExamLoader/`)
  * `logs\`: one log file per run (the GUI's **Open logs folder** button opens it)
  * `diagnostics\`: screenshots and page HTML saved when a step fails
  * `failed_questions.json`: the questions from the last run that failed, ready to re-run
  * `clipboard_questions.json`: the last JSON pasted into the GUI
  * `browser-profile-chrome\` / `browser-profile-edge\`: the separate browser profile ExamLoader opens, so you stay
    logged in to Exam.net between runs without touching your normal browser profile

## Usage

### Quick Start (Windows, no manual venv activation)

Use the launcher script from the project root:

```powershell
.\launch_examdotnet.ps1
```

Or from `cmd` / double-click:

```bat
launch_examdotnet.bat
```

The launcher will automatically:

* create `.venv` if missing
* install/update dependencies from `requirements.txt`
* skip Playwright browser downloads in the launcher
* run `python -m examnet`

### GUI (Windows)

Double-click `launch_examdotnet_gui.bat` (or run `.\launch_examdotnet.ps1 -Gui`, or `python -m examnet.gui`).

The window lets you pick the questions JSON file (or **Paste from clipboard**, e.g. straight from a ChatGPT reply,
which is saved to `clipboard_questions.json` in the ExamLoader folder), **Validate** it without opening a browser, set the run options,
**Start** the run and watch progress and the log. Login and confirmation prompts appear as dialog boxes instead of
"Press ENTER" terminal prompts. **Stop after current question** ends a run cleanly between questions.
The command-line interface below is unchanged.

Project code is organized as a package in `examnet/`, with one handler file per question type:

* `examnet/handlers/multiple_choice.py`
* `examnet/handlers/list_match.py`
* `examnet/handlers/long_answer.py`
* `examnet/handlers/fill_gaps.py`

`examnet/automator.py` handles shared orchestration/dispatch, and `python -m examnet` is the CLI entrypoint.

Pass any app arguments through the launcher, for example:

```powershell
.\launch_examdotnet.ps1 --log-level DEBUG --json-file questions.json
```

1. **Prepare your JSON** file (default: `questions.json`) in the project root.
2. **Run** the automation (interactive mode, default):

   ```bash
   python -m examnet
   ```
3. **Login Prompt**: If the current page is not already ready, log in to Exam.net and open the desired exam, then press **ENTER**.
4. **Automation**: The script processes each question in your JSON and creates it on exam.net.

### CLI Options

```bash
python -m examnet [--json-file PATH] [--browser-url URL] [--non-interactive] [--log-level LEVEL]
```

* `--json-file PATH`: Path to the questions JSON file (default: `questions.json`).
* `--browser-url URL`: Chrome CDP URL (default: `http://127.0.0.1:9222`).
* `--print-schema`: Print a valid JSON array example for supported question types, copy it to the clipboard when possible, and exit.
* `--non-interactive`: Disables prompts. The run fails fast if login/setup is still required.
* `--log-level LEVEL`: One of `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`).

### Example Commands

Interactive with debug logs:

```bash
python -m examnet --log-level DEBUG
```

Non-interactive with custom JSON:

```bash
python -m examnet --json-file questions.json --non-interactive
```

Print the expected schema as a valid JSON template:

```bash
python -m examnet --print-schema
```

Validation-only pre-flight (no browser automation):

```bash
python -c "from examnet import ExamNetAutomator; a=ExamNetAutomator(json_file='questions.json', interactive=False); q=a.load_questions(); a.validate_questions(q); print('Validation OK:', len(q))"
```

## JSON File Format

The JSON should be an array of question objects (or an object containing a `questions` array).

Supported question types:

* `multiple_choice`:
  * `question` (string)
  * `options` (array of strings)
  * `answer` (single correct option) or `answers` (multiple correct options)
* `list_match`:
  * `question_text` (string)
  * `pairs` (array of `{ "left": "...", "right": "..." }`)
  * optional `mark.points`
* `fill_gaps`:
  * `question_text` (string)
  * `gaps` (array of strings or objects with `answer` / `answers`)
  * optional `word_bank_extras` (array of incorrect words) and/or `word_bank_enabled: true`:
    exam.net has no built-in word bank, so a line such as `Word bank: CPU | GPU | RAM | ROM`
    (correct answers plus extras, sorted alphabetically) is printed above the question text
  * optional `mark.points`
* `long_answer`:
  * `question_text` (string)
  * optional `answer_options.sample_answer`
  * optional `answer_options.rubric`
  * optional `mark.points`
* `python_program` (a free-text question students answer in exam.net's programming tool):
  * same fields as `long_answer`, without `suggested_word_count` (it is ignored if present)
  * the reminder "STUDENTS MUST OPEN THE PROGRAMMING TOOL ON THE LEFT OF THE SCREEN TO COMPLETE THIS QUESTION"
    is appended to the question text automatically

If `question_type` is omitted, the script infers it:

* with `options` + `answer`/`answers` -> multiple-choice
* with `gaps` -> fill-gaps
* with `pairs`/`matches`/`list_match_pairs` -> list-match
* otherwise -> long-answer

### Example

```json
[
  {
    "question_type": "multiple_choice",
    "question": "How do you start a formula in Excel?",
    "options": [
      "With a colon (:)",
      "With an equal sign (=)",
      "With a question mark (?)",
      "With an exclamation mark (!)"
    ],
    "answer": "With an equal sign (=)"
  },
  {
    "question_type": "multiple_choice",
    "question": "Select all harmonious colour schemes:",
    "options": [
      "Complementary",
      "Analogous",
      "Triadic",
      "Clashing"
    ],
    "answers": [
      "Complementary",
      "Analogous",
      "Triadic"
    ]
  },
  {
    "question_type": "list_match",
    "question_text": "Match each programming term to its definition.",
    "pairs": [
      { "left": "Variable", "right": "A named storage location for data" },
      { "left": "Loop", "right": "A structure that repeats code" }
    ],
    "mark": { "points": 1 }
  },
  {
    "question_type": "fill_gaps",
    "question_text": "Complete: Batman protects ____ City.",
    "gaps": [
      { "answer": "Gotham" }
    ],
    "mark": { "points": 1 }
  },
  {
    "question_type": "long_answer",
    "question_text": "Explain how UX principles improve interactive systems.",
    "answer_options": {
      "rubric": {
        "format": "banded",
        "bands": [
          {
            "marks": 5,
            "criteria": ["Accurate principles", "Clear explanation", "Relevant examples"]
          }
        ]
      },
      "sample_answer": "Good UX improves usability, accessibility, and task completion."
    },
    "mark": { "points": 5 }
  },
  {
    "question_type": "python_program",
    "question_text": "Write a Python program that asks for 5 numbers and prints their average.",
    "answer_options": {
      "sample_answer": "total = 0
for i in range(5):
    total += float(input('Number: '))
print(total / 5)"
    },
    "mark": { "points": 4 }
  }
]
```

## Troubleshooting

* **Port Conflicts**: Ensure no other Chrome or Edge instance uses `--remote-debugging-port=9222`.
* **Browser Not Found**: ExamLoader looks for Chrome (machine-wide or per-user install), then Edge. Install Chrome
  if neither is found.
* **Selector Mismatches**: If elements are not found, inspect the exam.net UI and update selectors in:
  * `examnet/handlers/multiple_choice.py` (multiple choice)
  * `examnet/handlers/fill_gaps.py` (fill gaps)
  * `examnet/long_answer_probe.py` (long answer and list match controls)
* **Non-Interactive Failures**: If `--non-interactive` fails with setup/login readiness errors, run once in interactive mode first.

## Adding Question Types

To add a new `question_type`:

1. Create a handler module, for example `examnet/handlers/true_false.py`.
2. Add:
   * `validate_<type>(question, idx_label, is_non_empty_string, validate_points)`
   * `process_<type>_question(automator, payload, normalized_type)`
3. Export the new type set/functions in `examnet/handlers/__init__.py`.
4. Wire dispatch in `examnet/automator.py`:
   * `validate_question` -> call your new validator
   * `process_question` -> call your new processor
5. Add one sample item to `questions.json` and run the validation-only command first.

## Tests

```bash
python -m unittest test_cli test_automator test_browser
```

## Building the Windows app

```powershell
.\build.ps1
```

This installs the build tools from `requirements-build.txt` into `.venv`, runs the unit tests and builds
`dist\ExamLoader\ExamLoader.exe` with PyInstaller (`packaging\ExamLoader.spec`). The build bundles Playwright's
driver but no browsers. Test the exe from a different folder before releasing it.

## Releasing

The version lives in one place: `__version__` in `examnet/__init__.py`. The window title, About window, log files,
the exe's file properties and the installer all read it from there. See `CHANGELOG.md` for what each part of the
version number means.

1. Fix or add the feature, then do a full live run against Exam.net (use "DUMMY ... delete me" questions).
2. Update `examnet/__init__.py`: bump `__version__`, and set `LAST_VERIFIED` to the date of that live run.
3. Add a `CHANGELOG.md` entry written for teachers ("Fixes list-match questions after Exam.net's October update").
4. Run `.\build.ps1` and test `dist\ExamLoader\ExamLoader.exe`.
5. Commit, tag and push: `git tag v1.0.1` then `git push --follow-tags`.
6. Publish a GitHub Release for the tag with the installer attached and the changelog entry as its notes.

## License

MIT. See [LICENSE](LICENSE).
