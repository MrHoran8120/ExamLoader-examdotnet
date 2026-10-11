import logging
import os
import sys
import json
import re

# Add the current directory to sys.path so we can import examnet
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestResilience")

def find_json_objects(text):
    objs = []
    stack = []
    start = -1
    for i, char in enumerate(text):
        if char == '{':
            if not stack:
                start = i
            stack.append('{')
        elif char == '}':
            if stack:
                stack.pop()
                if not stack:
                    objs.append(text[start : i + 1])
    return objs

def test():
    print("Starting test...")
    if not os.path.exists("questions.json"):
        print("questions.json not found")
        return
    
    with open("questions.json", "r", encoding="utf-8-sig") as f:
        raw_text = f.read()
    
    print(f"Read {len(raw_text)} characters.")
    
    # Try the scavenger logic directly
    potentials = find_json_objects(raw_text)
    print(f"Found {len(potentials)} potential JSON objects.")
    
    valid_count = 0
    for p in potentials:
        try:
            obj = json.loads(p)
            if isinstance(obj, dict) and any(k in obj for k in ("question", "question_text", "question_id")):
                valid_count += 1
        except:
            continue
    
    print(f"Successfully parsed {valid_count} valid questions.")

if __name__ == "__main__":
    test()
