import json
import logging
import os
import re


def _extract_json_payload(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return text
    # Already valid JSON: never unwrap, even if question text contains ``` code samples.
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    # Only treat ``` as a wrapper when it sits on its own line. Fences inside JSON strings
    # are escaped onto the same physical line as their key, so they never match here.
    fenced_match = re.search(
        r"^[ \t]*```(?:json|jsonc)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*$",
        text,
        flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    if fenced_match:
        return fenced_match.group(1).strip()
    return text

def _strip_jsonc_comments(text):
    # Support question files that include JSONC-style comments.
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    no_line = re.sub(r"(?m)^\s*//.*$", "", no_block)
    return no_line


def run_json_precheck(json_file, interactive=True, bypass=False, logger=None, confirm=None):
    log = logger or logging.getLogger(__name__)

    if bypass:
        log.info("JSON precheck bypassed by user flag.")
        return True

    if not os.path.exists(json_file):
        raise FileNotFoundError(f"Questions file not found: {json_file}")

    with open(json_file, "r", encoding="utf-8-sig") as f:
        raw_text = f.read()

    payload_text = _extract_json_payload(raw_text)
    if not payload_text:
        raise ValueError(f"Questions file is empty: {json_file}")

    try:
        json.loads(payload_text)
        log.info("JSON precheck passed for '%s'.", os.path.basename(json_file))
        return True
    except json.JSONDecodeError:
        pass

    sanitized_payload = _strip_jsonc_comments(payload_text).strip()
    try:
        json.loads(sanitized_payload)
        log.info(
            "JSON precheck passed for '%s' after stripping JSONC comments.",
            os.path.basename(json_file),
        )
        return True
    except json.JSONDecodeError as e:
        log.warning(
            "JSON precheck failed for '%s': %s (line %s, column %s).",
            os.path.basename(json_file),
            e.msg,
            e.lineno,
            e.colno,
        )

        if not interactive:
            log.warning(
                "Non-interactive mode cannot prompt. Canceling run. "
                "Use --bypass-json-precheck to continue anyway."
            )
            return False

        if confirm:
            if confirm(
                f"The JSON file appears malformed:\n{e.msg} (line {e.lineno}, column {e.colno}).\n\n"
                "Proceed anyway? The loader will try to recover valid questions."
            ):
                log.warning("User chose to proceed despite malformed JSON.")
                return True
            log.info("User canceled run due to JSON precheck failure.")
            return False

        try:
            response = input(
                "JSON appears malformed. Type 'p' to proceed anyway, "
                "or press ENTER to cancel: "
            ).strip().lower()
        except EOFError:
            log.warning(
                "No interactive input available. Canceling run. "
                "Use --bypass-json-precheck to continue anyway."
            )
            return False

        if response in {"p", "proceed", "y", "yes"}:
            log.warning("User chose to proceed despite malformed JSON.")
            return True

        log.info("User canceled run due to JSON precheck failure.")
        return False
