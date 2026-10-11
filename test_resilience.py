import logging
import os
import sys

# Add the current directory to sys.path so we can import examnet
sys.path.append(os.getcwd())

from examnet.automator import ExamNetAutomator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestResilience")

def test():
    # Attempt to load the presumably broken questions.json
    automator = ExamNetAutomator(json_file="questions.json", logger=logger)
    try:
        questions = automator.load_questions()
        print(f"\nSUCCESS: Loaded {len(questions)} questions.")
        for i, q in enumerate(questions[:3]):
            print(f"  Q{i+1}: {q.get('question_id', 'N/A')} - {q.get('question', 'N/A')[:50]}...")
    except Exception as e:
        print(f"\nFAILED: {e}")

if __name__ == "__main__":
    test()
