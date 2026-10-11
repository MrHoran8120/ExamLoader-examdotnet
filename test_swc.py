import sys
import os

# Add the project directory to sys.path so we can import the modules
sys.path.append(r"d:\programming\Antigravity\examdotnet\examdotNet")

from long_answer_probe import extract_question_fields

payload = {
    "question_id": "LA-001",
    "question_type": "long_answer",
    "question_text": "A teacher is designing software to calculate and display student averages. Explain how an IPO diagram would help the programmer design this solution.",
    "suggested_word_count": {
      "recommended": 150,
      "minimum": 120,
      "maximum": 180
    }
}

print("Testing with suggested_word_count:")
qtype, qtext, atext, rtext, rhtml, pairs, points = extract_question_fields(
    payload, "long_answer", "fallback text", "sample answer", None, [], None
)
print(f"Question Text:\n{qtext}")

payload_no_swc = {
    "question_text": "No word count here."
}

print("\nTesting without suggested_word_count:")
qtype, qtext, atext, rtext, rhtml, pairs, points = extract_question_fields(
    payload_no_swc, "long_answer", "fallback text", "sample answer", None, [], None
)
print(f"Question Text:\n{qtext}")
