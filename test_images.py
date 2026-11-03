import json
import os
import shutil
import tempfile
import unittest
import zipfile

from examnet.ai_instructions import build_ai_instructions
from examnet.automator import ExamNetAutomator
from examnet.handlers import SUPPORTED_QUESTION_TYPES
from examnet.images import (
    PACKAGE_FORMAT,
    PackageError,
    close_package,
    open_package,
    resolve_question_images,
    validate_question_images,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def mc_question(text, images=None, **extra):
    question = {"question_type": "multiple_choice", "question": text, "options": ["A", "B"], "answer": "A"}
    if images is not None:
        question["images"] = images
    question.update(extra)
    return question


class ImageValidationTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "images"))
        for name in ("one.png", "two.jpg", "notes.txt"):
            with open(os.path.join(self.base, "images", name), "wb") as f:
                f.write(PNG)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def errors(self, question):
        return validate_question_images(question, "Question 1", self.base)

    def test_valid_markers_between_paragraphs(self):
        question = mc_question(
            "Intro\n[[image:one]]\nMiddle\n[[image:two]]\nEnd",
            {"one": {"file": "images/one.png", "alt": "A", "width": 400}, "two": {"file": "images/two.jpg"}},
        )
        self.assertEqual(self.errors(question), [])
        resolved = resolve_question_images(question, self.base)
        self.assertEqual(resolved["one"]["path"], os.path.realpath(os.path.join(self.base, "images", "one.png")))
        self.assertEqual(resolved["one"]["width"], 400)
        self.assertEqual(resolved["two"]["alt"], "")

    def test_question_without_images_is_unaffected(self):
        self.assertEqual(self.errors(mc_question("No pictures here")), [])

    def test_marker_without_entry_and_entry_without_marker(self):
        errors = self.errors(mc_question("[[image:one]]", {"two": {"file": "images/two.jpg"}}))
        self.assertTrue(any("has no entry named 'one'" in e for e in errors))
        self.assertTrue(any("'two' is listed in 'images' but the text has no" in e for e in errors))

    def test_missing_file_bad_type_and_paths_outside_package(self):
        cases = {
            "images/missing.png": "was not found",
            "images/notes.txt": "not a supported image type",
            "../outside.png": "must be a path inside the exam folder",
            "C:/Windows/outside.png": "must be a path inside the exam folder",
        }
        for path, message in cases.items():
            with self.subTest(path=path):
                errors = self.errors(mc_question("[[image:one]]", {"one": {"file": path}}))
                self.assertTrue(any(message in e for e in errors), errors)

    def test_bad_name_width_and_duplicate_marker(self):
        errors = self.errors(mc_question("[[image:One Pic]]", {}))
        self.assertTrue(any("not a valid image name" in e for e in errors))
        errors = self.errors(mc_question("[[image:one]]", {"one": {"file": "images/one.png", "width": 5}}))
        self.assertTrue(any("'width' must be" in e for e in errors))
        errors = self.errors(mc_question("[[image:one]] [[image:one]]", {"one": {"file": "images/one.png"}}))
        self.assertTrue(any("used more than once" in e for e in errors))

    def test_markers_outside_question_text_are_rejected(self):
        question = mc_question("Pick one", {}, options=["[[image:one]]", "B"])
        self.assertTrue(any("'options[0]' contains an image marker" in e for e in self.errors(question)))


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def make_zip(self, files):
        path = os.path.join(self.work, "exam.zip")
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return path

    def test_plain_json_resolves_images_next_to_it(self):
        path = os.path.join(self.work, "questions.json")
        self.assertEqual(open_package(path), (path, self.work, None))

    def test_zip_with_questions_at_top_or_in_one_folder(self):
        for prefix in ("", "My exam/"):
            with self.subTest(prefix=prefix):
                json_path, base_dir, temp_dir = open_package(
                    self.make_zip({f"{prefix}questions.json": "[]", f"{prefix}images/one.png": PNG})
                )
                try:
                    self.assertEqual(os.path.basename(json_path), "questions.json")
                    self.assertTrue(os.path.isfile(os.path.join(base_dir, "images", "one.png")))
                finally:
                    close_package(temp_dir)
                self.assertFalse(os.path.exists(temp_dir))

    def test_rejects_unsafe_paths_missing_json_and_non_zip(self):
        with self.assertRaises(PackageError):
            open_package(self.make_zip({"questions.json": "[]", "../evil.png": PNG}))
        with self.assertRaises(PackageError):
            open_package(self.make_zip({"images/one.png": PNG}))
        bad = os.path.join(self.work, "bad.zip")
        with open(bad, "w") as f:
            f.write("not a zip")
        with self.assertRaises(PackageError):
            open_package(bad)

    def test_automator_validates_a_zip_package(self):
        payload = {
            "format": PACKAGE_FORMAT,
            "questions": [mc_question("See:\n[[image:one]]", {"one": {"file": "images/one.png"}})],
        }
        path = self.make_zip({"questions.json": json.dumps(payload), "images/one.png": PNG})
        automator = ExamNetAutomator(json_file=path, interactive=False)
        automator.open_input()
        try:
            questions = automator.load_questions()
            automator.validate_questions(questions)
            self.assertEqual(len(questions), 1)
        finally:
            automator.close_input()

    def test_automator_reports_missing_image_in_zip(self):
        payload = {"questions": [mc_question("[[image:one]]", {"one": {"file": "images/one.png"}})]}
        automator = ExamNetAutomator(json_file=self.make_zip({"questions.json": json.dumps(payload)}), interactive=False)
        automator.open_input()
        try:
            with self.assertRaisesRegex(ValueError, "images/one.png' was not found"):
                automator.validate_questions(automator.load_questions())
        finally:
            automator.close_input()


class AiInstructionsTests(unittest.TestCase):
    def test_instructions_cover_format_types_and_images(self):
        text = build_ai_instructions()
        self.assertIn(PACKAGE_FORMAT, text)
        self.assertIn("[[image:name]]", text)
        for qtype in ("multiple_choice", "list_match", "fill_gaps", "long_answer", "python_program"):
            self.assertIn(qtype, SUPPORTED_QUESTION_TYPES)
            self.assertIn(f"`{qtype}`", text)

    def test_example_in_instructions_is_valid_json_and_its_image_question_validates(self):
        text = build_ai_instructions()
        start = text.index("## Example") + len("## Example")
        example = json.loads(text[start : text.index("(In the example")])
        self.assertEqual(example["format"], PACKAGE_FORMAT)
        image_question = example["questions"][-1]
        base = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(base, "images"))
            with open(os.path.join(base, "images", "canteen.png"), "wb") as f:
                f.write(PNG)
            automator = ExamNetAutomator(json_file=os.path.join(base, "questions.json"), interactive=False)
            self.assertEqual(automator.validate_question(image_question, 1), [])
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
