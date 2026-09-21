"""Conservative source inventory for numbered, text-based objective papers.

This inventory is independent of model output. It does not claim that numbering
recognition proves complete document coverage. Unrecognised layouts stay on the
legacy parser with an explicit coverage warning.
"""
from __future__ import annotations

import re
from collections import Counter

_START = re.compile(r"(?m)^\s*(?:Q(?:uestion)?\s*\.?\s*)?(\d{1,4})[.)]\s+(?=\S)", re.I)
_KEY_HEADER = re.compile(r"(?im)^\s*(?:answer\s*key|answers)\s*:?\s*$")
_KEY = re.compile(r"(?<!\w)(\d{1,4})\s*[.):=-]\s*([A-H])\b", re.I)
_OPTION = re.compile(r"(?im)^\s*\(?([a-h])[.)]\s*(.+)$")
_INLINE = re.compile(r"(?im)^\s*(?:answer|ans|correct option)\s*[:=-]\s*([a-h])\b")


def inventory(text: str) -> dict:
    header = _KEY_HEADER.search(text)
    body = text[:header.start()] if header else text
    key_text = text[header.end():] if header else ""
    interleaved = bool(_OPTION.search(key_text))
    if interleaved:
        # Keys between sections need section-aware joining. Keep all questions
        # in the inventory, but never apply a global key across those sections.
        body, key_text = text, ""
    matches = list(_START.finditer(body))
    items = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        block = body[match.start():end].strip()
        # Numeric option labels and prose lists cannot reliably be distinguished
        # from question numbering. Inventory only blocks with lettered options.
        options = list(_OPTION.finditer(block))
        if len(options) < 2:
            continue
        stem = _START.sub("", block[:options[0].start()], count=1).strip()
        if not stem:
            continue
        inline = _INLINE.findall(block)
        items.append({"source_id": f"item-{len(items) + 1}", "number": match.group(1),
                      "text": block, "stem": stem, "offset": match.start(),
                      "inline_keys": [key.lower() for key in inline]})
    keys: dict[str, list[str]] = {}
    for line in key_text.splitlines():
        residue = _KEY.sub("", line)
        if residue.strip(" \t,;|"):
            continue
        for number, letter in _KEY.findall(line):
            keys.setdefault(number, []).append(letter.lower())
    frequencies = Counter(item["number"] for item in items)
    for item in items:
        values = item["inline_keys"][:]
        if frequencies[item["number"]] == 1:
            values += keys.get(item["number"], [])
        item["key_ambiguous"] = frequencies[item["number"]] > 1 and item["number"] in keys
        item["keys"] = sorted(set(values))
    return {"items": items, "key_text": key_text,
            "warnings": (["Repeated source numbers: unscoped end-of-paper keys were not joined."]
                         if any(item["key_ambiguous"] for item in items) else [])
                        + (["Answer keys occur between sections; automatic global key joining was disabled."] if interleaved else [])}


def question_chunks(text: str, max_chars: int) -> list[str]:
    """Keep numbered question blocks whole; never silently hard-cut an item."""
    starts = list(_START.finditer(text))
    if not starts:
        units = text.split("\n\n")
    else:
        units = [text[:starts[0].start()]] + [
            text[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
            for i, match in enumerate(starts)]
    chunks, buffer = [], ""
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        if len(unit) > max_chars:
            raise ValueError("A question or unstructured source block exceeds the import limit. Split the paper into smaller complete sections and retry.")
        if buffer and len(buffer) + len(unit) + 2 > max_chars:
            chunks.append(buffer)
            buffer = ""
        buffer = f"{buffer}\n\n{unit}" if buffer else unit
    if buffer:
        chunks.append(buffer)
    return chunks


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


def reconcile(raw: dict, source: dict) -> dict:
    """Join only uniquely identified source occurrences; preserve all candidates."""
    candidates = raw.get("questions")
    if not isinstance(candidates, list):
        return raw
    items = source["items"]
    seen: Counter = Counter()
    records = []
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            continue
        stem = _normal(_START.sub("", str(candidate.get("question_text") or ""), count=1))
        matches = [item for item in items if _normal(item["stem"]) == stem]
        # A model-supplied number can disambiguate stems, but cannot replace
        # exact stem matching or silently associate repeated section numbers.
        number = str(candidate.get("source_number") or "")
        if len(matches) > 1 and number:
            matches = [item for item in matches if item["number"] == number]
        candidate["verification_status"] = "needs_teacher_review"
        warnings = ["Imported answer requires comparison with the original paper."]
        origin = "inferred_or_unconfirmed"
        if len(matches) == 1:
            item = matches[0]
            seen[item["source_id"]] += 1
            candidate["source_excerpt"] = item["text"]
            candidate["source_page_start"] = item.get("page_start")
            candidate["source_page_end"] = item.get("page_end")
            keys = item["keys"]
            if len(keys) == 1 and not item["key_ambiguous"] and candidate.get("type") == "mcq_single":
                # Source letters refer to source option order. Require that
                # output IDs and option texts preserve that same order first.
                source_options = _OPTION.findall(item["text"])
                output_options = candidate.get("options") or []
                faithful = len(source_options) == len(output_options) and all(
                    isinstance(option, dict) and option.get("id") == letter.lower()
                    and _normal(str(option.get("text") or "")) == _normal(value)
                    for (letter, value), option in zip(source_options, output_options))
                if faithful and keys[0] in {option["id"] for option in output_options}:
                    origin = "source_key"
                    if candidate.get("correct_answer") != keys[0]:
                        warnings.append("Model answer differed from the source key; source key retained. Confirm before approval.")
                    candidate["correct_answer"] = keys[0]
                    warnings.append(f"Source answer key: {keys[0].upper()} (question {item['number']}).")
                else:
                    warnings.append("Source key could not be safely joined because option wording/order differs. Compare the original options.")
            elif len(keys) > 1:
                origin = "conflicting_source_keys"
                warnings.append("Conflicting source answer keys. Resolve against the original paper before approval.")
            elif item["key_ambiguous"]:
                warnings.append("Repeated question number: end-of-paper answer key is ambiguous.")
            candidate["source_number"] = item["number"]
            records.append({"source_id": item["source_id"], "source_number": item["number"],
                            "candidate_index": index, "answer_origin": origin})
        else:
            warnings.append("Could not uniquely match this question to the numbered source inventory.")
        candidate["verification_warnings"] = warnings
    missing = [{"source_id": item["source_id"], "source_number": item["number"],
                "question_preview": item["stem"][:240]}
               for item in items if not seen[item["source_id"]]]
    return {**raw, "source_inventory": {
        "detected": len(items), "matched": len(seen), "missing": missing,
        "duplicate_matches": [key for key, count in seen.items() if count > 1],
        "items": records, "warnings": source["warnings"],
        "coverage_verified": False,
        "scope": "Numbered text questions with lettered options; other layouts require manual comparison.",
    }}
