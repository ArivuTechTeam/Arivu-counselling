"""Pure question-reference rules shared by handwritten Stage 1 processing."""
from __future__ import annotations

import re

_ROMAN = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "x": "10", "xi": "11", "xii": "12",
}


def normalize_question_ref(ref: object) -> str:
    """Return ExamApp's collision-safe canonical comparison key."""
    if not ref:
        return ""
    raw = str(ref).strip()
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", raw):
        return ""
    raw = re.sub(
        r"^(?:answer|ans|question|q)\.?\s*[-.]?\s*", "", raw, flags=re.I
    )
    alt = alt_num = ""
    match = re.match(r"^(\d+)([A-Z])(?![A-Za-z])", raw)
    if match:
        alt, alt_num = match.group(2).lower(), match.group(1)
        raw = alt_num + raw[match.end():]
    tokens = re.findall(r"[a-z]+|\d+", raw.lower())
    if not tokens:
        return ""
    folded = [_ROMAN.get(token, token) for token in tokens]
    parts = [folded[0]]
    for previous, current in zip(folded, folded[1:]):
        if previous[-1:].isdigit() and current[:1].isdigit():
            parts.append("_")
        parts.append(current)
    cleaned = "".join(parts)
    if len(cleaned) <= 2 and not cleaned[0:1].isdigit():
        return ""
    if alt and cleaned.startswith(alt_num):
        cleaned = f"{alt_num}!{alt}{cleaned[len(alt_num):].lstrip('_')}"
    return f"q{cleaned}"


def ref_is_descendant(normalized: str, candidate: str) -> bool:
    """True only at a token boundary (Q10 is never a child of Q1)."""
    if not normalized or not candidate or normalized == candidate:
        return False
    if not normalized.startswith(candidate):
        return False
    next_character = normalized[len(candidate):len(candidate) + 1]
    if next_character == "!":
        return False
    return not (candidate[-1:].isdigit() and next_character.isdigit())


def canonical_ref(raw_ref: object, valid_refs: list[str]) -> str:
    normalized = normalize_question_ref(raw_ref)
    if not normalized:
        return ""
    by_normalized = {
        key: ref for ref in valid_refs if (key := normalize_question_ref(ref))
    }
    if normalized in by_normalized:
        return by_normalized[normalized]
    for candidate in sorted(by_normalized, key=len, reverse=True):
        if ref_is_descendant(normalized, candidate):
            return by_normalized[candidate]
    return ""


def plausible_unbound_ref(value: object) -> str:
    """Keep ordinary printed refs on guide-free papers; reject captions/prose."""
    raw = str(value or "").strip()
    if not raw or "|" in raw or len(raw) > 50:
        return ""
    raw = re.sub(
        r"^(?:answer|ans|question|q)\.?\s*[-.:]?\s*", "", raw, flags=re.I
    ).strip()
    if not raw or not raw[:1].isdigit() or re.search(r"[^0-9A-Za-z()._\-\s]", raw):
        return ""
    tokens = re.findall(r"[A-Za-z]+|\d+", raw)
    if not tokens or not tokens[0].isdigit():
        return ""
    for token in tokens[1:]:
        if not token.isdigit() and len(token) != 1 and token.lower() not in _ROMAN:
            return ""
    return raw
