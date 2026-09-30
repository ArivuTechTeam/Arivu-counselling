"""Small, bounded repairs for common JSON-only model response defects."""
from __future__ import annotations

import json
import re
from typing import Any, Literal


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def escape_control_chars_in_json_strings(text: str) -> str:
    output: list[str] = []
    inside = False
    escaped = False
    replacements = {"\n": r"\n", "\r": r"\r", "\t": r"\t"}
    for character in text:
        if inside and character in replacements:
            output.append(replacements[character])
            escaped = False
            continue
        output.append(character)
        if character == '"' and not escaped:
            inside = not inside
        if character == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    return "".join(output)


def extract_first_json(text: str) -> str | None:
    starts = [position for position in (text.find("{"), text.find("[")) if position >= 0]
    if not starts:
        return None
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    inside = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if character == '"' and not escaped:
            inside = not inside
        if not inside:
            if character == opening:
                depth += 1
            elif character == closing:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        if character == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    return None


def parse_repaired_json(text: str, *, expect: Literal["dict", "list"] = "dict") -> Any | None:
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    candidates = [cleaned]
    extracted = extract_first_json(cleaned)
    if extracted and extracted != cleaned:
        candidates.append(extracted)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = json.loads(escape_control_chars_in_json_strings(candidate))
            except (json.JSONDecodeError, TypeError):
                continue
        if expect == "list" and isinstance(parsed, dict):
            inner = next((value for value in parsed.values() if isinstance(value, list)), None)
            return inner if inner is not None else parsed
        return parsed
    return None
