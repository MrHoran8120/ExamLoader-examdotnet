import json
from long_answer_probe import extract_question_fields

def test_extraction():
    with open("completequestions.json", "r", encoding="utf-8-sig") as f:
        questions = json.load(f)
    
    for i, q in enumerate(questions):
        if q.get("question_type") == "long_answer":
            print(f"Testing Q{i+1}: {q.get('question_id')}")
            res = extract_question_fields(
                q,
                "long_answer",
                "Default Question",
                "Default Answer",
                None,
                [],
                None
            )
            # res: question_type, question_text, answer_text, rubric_text, rubric_is_html, list_match_pairs, points
            print(f"  Type: {res[0]}")
            print(f"  Answer Text: {res[2][:50]}...")
            print(f"  Rubric Text: {str(res[3])[:50]}...")
            print("-" * 20)

if __name__ == "__main__":
    test_extraction()
