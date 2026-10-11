from unittest.mock import Mock
import unittest

from examnet.automator import ExamNetAutomator


class AutomatorRunOrderTests(unittest.TestCase):
    def test_run_processes_questions_in_json_order(self):
        automator = ExamNetAutomator(interactive=False)
        questions = [
            {"question_type": "multiple_choice", "question": "Question 1", "options": ["A", "B"], "answer": "A"},
            {"question_type": "multiple_choice", "question": "Question 2", "options": ["A", "B"], "answer": "A"},
            {"question_type": "multiple_choice", "question": "Question 3", "options": ["A", "B"], "answer": "A"},
        ]
        seen = []

        automator.load_questions = Mock(return_value=questions)
        automator.validate_questions = Mock()
        automator.setup_browser = Mock()
        automator.count_existing_questions = Mock(side_effect=[0, 3])
        automator.process_question = Mock(side_effect=lambda question, idx=None: seen.append((idx, question["question"])))
        automator.logger = Mock()

        automator.run()

        self.assertEqual(
            seen,
            [
                (1, "Question 1"),
                (2, "Question 2"),
                (3, "Question 3"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
