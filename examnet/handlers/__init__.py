from .fill_gaps import FILL_GAPS_TYPES, process_fill_gaps_question, validate_fill_gaps
from .list_match import LIST_MATCH_TYPES, process_list_match_question, validate_list_match
from .long_answer import (
    LONG_ANSWER_TYPES,
    PYTHON_PROGRAM_TYPES,
    process_long_answer_question,
    process_python_program_question,
    validate_long_answer,
    validate_python_program,
)
from .multiple_choice import MULTIPLE_CHOICE_TYPES, process_multiple_choice_question, validate_multiple_choice

SUPPORTED_QUESTION_TYPES = (
    MULTIPLE_CHOICE_TYPES | LIST_MATCH_TYPES | LONG_ANSWER_TYPES | FILL_GAPS_TYPES | PYTHON_PROGRAM_TYPES
)

__all__ = [
    "MULTIPLE_CHOICE_TYPES",
    "LIST_MATCH_TYPES",
    "LONG_ANSWER_TYPES",
    "FILL_GAPS_TYPES",
    "PYTHON_PROGRAM_TYPES",
    "SUPPORTED_QUESTION_TYPES",
    "validate_multiple_choice",
    "validate_list_match",
    "validate_long_answer",
    "validate_fill_gaps",
    "validate_python_program",
    "process_multiple_choice_question",
    "process_list_match_question",
    "process_long_answer_question",
    "process_fill_gaps_question",
    "process_python_program_question",
]
