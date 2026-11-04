"""The instructions a teacher gives an AI (e.g. a Claude Project) so it returns an exam ExamLoader can load.

Built from the app's own rules (question types, image limits, package format), so the instructions always
match what this version accepts. The GUI's "Copy AI instructions" button and `--print-ai-instructions` use it.
"""

import json

from . import APP_NAME, __version__
from .images import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, MAX_WIDTH, MIN_WIDTH, PACKAGE_FORMAT, QUESTIONS_FILE

IMAGE_EXAMPLE = {
    "question_id": "MC-003",
    "question_type": "multiple_choice",
    "question": "Look at the spreadsheet below.\n[[image:canteen]]\nWhich formula belongs in cell D4?",
    "images": {
        "canteen": {
            "file": "images/canteen.png",
            "alt": "Spreadsheet with item prices in column B and quantities in column C",
            "width": 500,
        }
    },
    "options": ["=B4*C4*B1", "=B4+C4", "=SUM(B4:C4)", "=B1*D4"],
    "answer": "=B4*C4*B1",
    "mark": {"points": 1},
}


def build_ai_instructions():
    from .cli import build_question_schema

    example = {"format": PACKAGE_FORMAT, "questions": build_question_schema() + [IMAGE_EXAMPLE]}
    extensions = ", ".join(IMAGE_EXTENSIONS)
    max_mb = MAX_IMAGE_BYTES // (1024 * 1024)
    return f"""# Instructions: writing exams for {APP_NAME}

You write exam questions that a teacher loads into Exam.net with {APP_NAME} (version {__version__}).
The teacher asks for an exam (topic, year level, question types, number of questions, marks) and you
return ONE file that the app reads. Follow these rules exactly: the app checks every rule before it
creates anything and reports each mistake by question number.

## What to return

- If no question has an image: return a single file named `{QUESTIONS_FILE}`.
- If any question has an image: return a single `.zip` file laid out like this:

      {QUESTIONS_FILE}
      images/
        canteen.png
        circuit.png

  `{QUESTIONS_FILE}` sits at the top of the zip. Every image sits in `images/`. Include only images
  that a question uses. Name the zip after the exam, e.g. `year9-spreadsheets-quiz.zip`.
- Create the file with your file-creation tool so the teacher can download it. If you cannot create
  files, say so and return the JSON as a code block, without images.

## The JSON file

`{QUESTIONS_FILE}` is an object with the format version and an array of questions, in the order
they should appear in the exam:

    {{"format": "{PACKAGE_FORMAT}", "questions": [ ... ]}}

Every question has `question_id` (your label, e.g. "MC-001") and `question_type`, which is one of:

- `multiple_choice`: `question`, `options` (2 or more strings) and either `answer` (one correct
  option) or `answers` (several correct options, for "select all that apply"). Every answer must be
  copied exactly from `options`.
- `list_match`: `question_text` and `pairs`, an array of {{"left": ..., "right": ...}} items that
  students match up. Each correct match is worth 1 mark, so leave out `mark`.
- `fill_gaps`: `question_text` with `___` (three underscores) where each gap goes, and `gaps`, one
  entry per `___` in the same order: {{"answer": "word"}}, or {{"answers": ["word", "alternative"]}}
  when more than one answer is accepted. Optional `word_bank_extras` (wrong words to add to a
  word bank) or `"word_bank_enabled": true` (word bank of just the answers).
- `long_answer`: `question_text`, optional `answer_options` with `sample_answer` (string) and
  `rubric` (a string, or a banded rubric as in the example), optional `suggested_word_count`
  ({{"recommended": "150-200"}}).
- `python_program`: like `long_answer`, for questions students answer by writing Python in
  Exam.net's programming tool. No `suggested_word_count`.

Every question except `list_match` may have `"mark": {{"points": N}}`.

Text rules:
- Put line breaks in text as `\\n`. Use plain text, not HTML or Markdown headings.
- Put code in backticks: `inline code`, or a fenced block (```python ... ```) on its own lines.
  The app keeps code formatting. Don't use backticks in fill_gaps questions.

## Images

Images can only go in the question text (`question` or `question_text`), never in options, pairs,
gaps or answers.

1. Put a marker on its own line where the image belongs: `[[image:name]]`. A question may have
   several images, between paragraphs or after the text.
2. Add an `images` object to the question with one entry per marker, keyed by the same name:

       "images": {{"name": {{"file": "images/name.png", "alt": "...", "width": 500}}}}

   - `file` (required): path inside the zip, always `images/<file name>`.
   - `alt` (recommended): one sentence describing the image for students who cannot see it.
   - `width` (optional): display width in pixels, {MIN_WIDTH} to {MAX_WIDTH}. Default is 300.
3. Names use only lowercase letters, numbers, `-` and `_`. Every marker needs an entry and every
   entry needs a marker. Use each marker once.
4. Supported file types: {extensions}. Each file must be under {max_mb} MB. PNG is best for
   diagrams and screenshots, JPG for photos.

Where images come from:
- Images the teacher attached: copy them into `images/` unchanged, and refer to them by file name.
  Look at each image and write questions about what it actually shows.
- Images you make: draw them with code (for example Python with matplotlib or Pillow) and save them
  as PNG at a readable size (around 800-1200 pixels wide). Good uses: graphs, diagrams, flowcharts,
  circuit layouts, mock spreadsheets, code screenshots. Check each image before adding it: labels
  readable, nothing cut off, and it matches the question and answers.
- Never link to images on the web, and never invent a file you did not put in the zip.

## Example

{json.dumps(example, indent=2, ensure_ascii=False)}

(In the example, angle-bracket text like <Option A> stands for your content. The last question shows
how an image is used; its zip would contain images/canteen.png.)

## Before you return the file, check

- Every question has a valid `question_type` and the fields listed for it.
- Every `answer`/`answers` is copied exactly from `options`.
- Every fill_gaps question has exactly as many `gaps` as `___` markers.
- Every `[[image:name]]` has a matching `images` entry, and every file is in `images/` in the zip.
- The JSON is valid: no comments, no trailing commas.
"""
