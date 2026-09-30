"""Stage 1 handwritten-script transcription and deterministic repair pipeline."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import mimetypes
import re
from typing import Callable

import fitz

from app.lib.config import get_settings
from app.lib.storage import EVALUATION_SUBMISSIONS_BUCKET, download_bytes
from app.services.ai_call_logging import ai_call_context
from app.services.evaluation_references import (
    canonical_ref,
    normalize_question_ref,
    plausible_unbound_ref,
)
from app.services.evaluation_stage1_contract import (
    STAGE1_EXTRACTION_SCHEMA,
    build_stage1_prompt,
)
from app.services.llm.structured import gemini_json_multimodal

logger = logging.getLogger(__name__)
REQUIRED_KEYS = tuple(STAGE1_EXTRACTION_SCHEMA["required"])
PAID_GAP_REASONS = {"missing", "duplicate", "unreadable"}
MAX_REPAIR_PAGES = 6


class Stage1RetryableError(RuntimeError):
    """A transient/model-contract failure that may be retried by the queue."""


class Stage1PermanentError(RuntimeError):
    """A bad stored input that retrying cannot fix."""


@dataclass(frozen=True)
class Stage1Outcome:
    extraction: dict
    source: str
    page_mapping: dict
    requires_review: bool


def stage1_blocks_grading(extraction: dict) -> bool:
    """Only a wholly illegible script stops before Stage 2, matching ExamApp."""
    legibility = extraction.get("legibility_report") or {}
    return str(legibility.get("overall_legibility") or "").strip().lower() == "illegible"


def stage1_requires_review(extraction: dict) -> bool:
    """Return whether a completed evaluation must be routed to human review."""
    verification = extraction.get("page_verification") or {}
    return bool(
        stage1_blocks_grading(extraction)
        or (isinstance(verification, dict) and verification.get("requires_review") is True)
        or extraction.get("legibility_metadata_uncertain") is True
    )


def _validate_contract(value: object) -> dict:
    if not isinstance(value, dict):
        raise Stage1RetryableError("Stage 1 returned a non-object JSON value.")
    missing = [key for key in REQUIRED_KEYS if key not in value]
    if missing:
        raise Stage1RetryableError("Stage 1 omitted required keys: " + ", ".join(missing))
    for key in ("text_answers", "tables", "numerical_workings", "page_manifest"):
        if not isinstance(value[key], list):
            raise Stage1RetryableError(f"Stage 1 field {key} is not an array.")
    if not isinstance(value["legibility_report"], dict):
        raise Stage1RetryableError("Stage 1 legibility_report is not an object.")
    return deepcopy(value)


def _valid_map(valid_refs: list[str]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    for ref in valid_refs:
        normalized = normalize_question_ref(ref)
        if normalized and normalized not in mapping:
            mapping[normalized] = ref
    return mapping, sorted(mapping, key=len, reverse=True)


def apply_visible_question_refs(data: dict, valid_refs: list[str]) -> dict:
    if not valid_refs:
        return data
    result = deepcopy(data)
    conflicts = 0

    def reconcile(item: object) -> None:
        nonlocal conflicts
        if not isinstance(item, dict):
            return
        visible = canonical_ref(item.get("visible_question_ref"), valid_refs)
        if not visible:
            return
        mapped = canonical_ref(item.get("question_ref"), valid_refs)
        if mapped and normalize_question_ref(mapped) != normalize_question_ref(visible):
            item["mapping_conflict"] = {
                "content_mapped_ref": mapped, "visible_ref": visible,
            }
            conflicts += 1
        item["question_ref"] = visible

    for section in ("text_answers", "tables", "numerical_workings"):
        for item in result.get(section, []) or []:
            reconcile(item)
    for table in result.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows")
        semantic = table.get("row_question_refs")
        visible = table.get("row_visible_question_refs")
        if not all(isinstance(value, list) for value in (rows, semantic, visible)):
            continue
        semantic = list(semantic[:len(rows)]) + [""] * max(0, len(rows) - len(semantic))
        visible = list(visible[:len(rows)]) + [""] * max(0, len(rows) - len(visible))
        row_conflicts = []
        for index, raw_visible in enumerate(visible):
            canonical_visible = canonical_ref(raw_visible, valid_refs)
            if not canonical_visible:
                continue
            mapped = canonical_ref(semantic[index], valid_refs)
            if mapped and normalize_question_ref(mapped) != normalize_question_ref(canonical_visible):
                row_conflicts.append({"row_index": index, "content_mapped_ref": mapped,
                                      "visible_ref": canonical_visible})
                conflicts += 1
            semantic[index] = canonical_visible
        table["row_question_refs"] = semantic
        if row_conflicts:
            table["row_mapping_conflicts"] = row_conflicts
    if conflicts:
        logger.info("Stage 1 visible-heading precedence resolved %d conflicts", conflicts)
    return result


def apply_page_manifest_refs(data: dict, valid_refs: list[str]) -> dict:
    if not valid_refs:
        return data
    result = deepcopy(data)
    refs_by_page: dict[tuple[int, int], set[str]] = {}
    for row in result.get("page_manifest", []) or []:
        try:
            key = (int(row["document_index"]), int(row["page_number"]))
        except (KeyError, TypeError, ValueError):
            continue
        refs = {mapped for raw in row.get("question_refs", [])
                if (mapped := canonical_ref(raw, valid_refs))}
        if refs:
            refs_by_page.setdefault(key, set()).update(refs)
    for section in ("text_answers", "tables", "numerical_workings"):
        for item in result.get(section, []) or []:
            if not isinstance(item, dict) or canonical_ref(item.get("question_ref"), valid_refs):
                continue
            try:
                document = int(item["source_document_index"])
                pages = {int(page) for page in item.get("source_pages", [])}
            except (KeyError, TypeError, ValueError):
                continue
            candidates: set[str] = set()
            for page in pages:
                candidates.update(refs_by_page.get((document, page), set()))
            if len(candidates) != 1:
                continue
            recovered = next(iter(candidates))
            item["question_ref"] = recovered
            item["mapping_recovered_from_page_manifest"] = True
            if section == "tables" and isinstance(item.get("row_question_refs"), list):
                item["row_question_refs"] = [
                    raw if canonical_ref(raw, valid_refs) else recovered
                    for raw in item["row_question_refs"]
                ]
    return result


def merge_leading_continuations(data: dict, valid_refs: list[str]) -> dict:
    """Merge only exact declared prefixes into an earlier same-document block."""
    result = deepcopy(data)
    rows = result.get("text_answers")
    if not isinstance(rows, list):
        return result
    output: list = []
    for row in rows:
        if not isinstance(row, dict):
            output.append(row)
            continue
        prefix = str(row.get("leading_continuation_text") or "")
        target = canonical_ref(row.get("leading_continuation_ref"), valid_refs)
        raw_text = str(row.get("raw_text") or "")
        if not prefix or not target or not raw_text.startswith(prefix):
            output.append(row)
            continue
        try:
            document = int(row.get("source_document_index"))
            current_page = min(int(page) for page in row.get("source_pages", []))
        except (TypeError, ValueError):
            output.append(row)
            continue
        previous = next((candidate for candidate in reversed(output)
            if isinstance(candidate, dict)
            and int(candidate.get("source_document_index", -1)) == document
            and canonical_ref(candidate.get("question_ref"), valid_refs) == target
            and any(int(page) < current_page for page in candidate.get("source_pages", []))), None)
        if previous is None:
            row["continuation_merge_unresolved"] = True
            output.append(row)
            continue
        previous["raw_text"] = (str(previous.get("raw_text") or "").rstrip() + "\n" + prefix).strip()
        previous["source_pages"] = sorted(set(previous.get("source_pages", [])) | set(row.get("source_pages", [])))
        previous["continuation_merged"] = True
        remainder = raw_text[len(prefix):].lstrip("\n")
        if remainder:
            row["raw_text"] = remainder
            row["leading_continuation_ref"] = ""
            row["leading_continuation_text"] = ""
            output.append(row)
    result["text_answers"] = output
    return result


def _amount(value: object) -> float:
    raw = str(value or "").strip().replace(",", "")
    if not raw or not re.search(r"\d", raw):
        return 0.0
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    match = re.search(r"\d+(?:\.\d+)?", raw)
    return (-1 if negative else 1) * float(match.group(0)) if match else 0.0


def _amount_column(headers: list, kind: str) -> int | None:
    pattern = {"dr": r"(^|\W)(dr|debit)(\W|$)", "cr": r"(^|\W)(cr|credit)(\W|$)"}[kind]
    return next((index for index, header in enumerate(headers or [])
                 if re.search(pattern, str(header or ""), flags=re.I)), None)


def split_tables_by_row_ref(data: dict, valid_refs: list[str]) -> dict:
    result = deepcopy(data)
    output: list = []
    for table in result.get("tables", []) or []:
        if not isinstance(table, dict) or not isinstance(table.get("rows"), list) \
                or not isinstance(table.get("row_question_refs"), list) or not valid_refs:
            output.append(table)
            continue
        rows = table["rows"]
        aligned = list(table["row_question_refs"][:len(rows)]) + [""] * max(0, len(rows) - len(table["row_question_refs"]))
        canonical = [canonical_ref(ref, valid_refs) for ref in aligned]
        for index, row in enumerate(rows):
            if canonical[index]:
                continue
            previous = canonical[index - 1] if index else ""
            following = next((ref for ref in canonical[index + 1:] if ref), "")
            cells = row if isinstance(row, list) else [row]
            text = " ".join(str(cell or "") for cell in cells).strip()
            has_amount = any(re.search(r"\d", str(cell or "")) for cell in cells[1:])
            narration = (text.startswith("(") or text.lower().startswith(("being ", "narration "))) and not has_amount
            if previous and (narration or previous == following):
                canonical[index] = previous
        distinct = list(dict.fromkeys(ref for ref in canonical if ref))
        if not distinct:
            output.append(table)
            continue
        if len(distinct) == 1:
            canonical = [ref or distinct[0] for ref in canonical]
        groups: dict[str, dict] = {}
        for original_index, (row, ref) in enumerate(zip(rows, canonical)):
            group = groups.setdefault(ref, {"rows": [], "indices": []})
            group["rows"].append(row); group["indices"].append(original_index)
        headers = table.get("headers", [])
        dr_index, cr_index = _amount_column(headers, "dr"), _amount_column(headers, "cr")
        for ref, group in groups.items():
            dr_total = sum(_amount(row[dr_index]) for row in group["rows"]
                           if dr_index is not None and isinstance(row, list) and dr_index < len(row))
            cr_total = sum(_amount(row[cr_index]) for row in group["rows"]
                           if cr_index is not None and isinstance(row, list) and cr_index < len(row))
            split = {**table, "question_ref": ref, "rows": group["rows"],
                "row_question_refs": [ref] * len(group["rows"]), "dr_total_by_student": "",
                "cr_total_by_student": "", "computed_dr_total": dr_total,
                "computed_cr_total": cr_total, "totals_match_student": False,
                "totals_balance": abs(dr_total - cr_total) < 0.005,
                "balance_difference": dr_total - cr_total}
            row_lookup = {old + 1: new + 1 for new, old in enumerate(group["indices"])}
            difficult = []
            for note in table.get("difficult_cells", []) or []:
                text = str(note or "")
                match = re.search(r"\bRow\s+(\d+)\b", text, flags=re.I)
                if not match:
                    difficult.append(text)
                elif int(match.group(1)) in row_lookup:
                    difficult.append(text[:match.start(1)] + str(row_lookup[int(match.group(1))]) + text[match.end(1):])
            split["difficult_cells"] = difficult
            if not ref:
                split["question_ref_unresolved"] = True
            output.append(split)
    result["tables"] = output
    return result


def snap_refs_to_paper(data: dict, valid_refs: list[str]) -> dict:
    result = deepcopy(data)
    if not valid_refs:
        for section in ("text_answers", "tables", "numerical_workings"):
            for item in result.get(section, []) or []:
                if not isinstance(item, dict):
                    continue
                raw = item.get("question_ref", "")
                item["question_ref"] = plausible_unbound_ref(raw)
                if raw and not item["question_ref"]:
                    item["question_ref_unresolved"] = raw
        return result
    for section in ("text_answers", "tables", "numerical_workings"):
        for item in result.get(section, []) or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("question_ref", "")
            snapped = canonical_ref(raw, valid_refs)
            if snapped:
                item["question_ref"] = snapped
            elif raw:
                item["question_ref_unresolved"] = raw
                item["question_ref"] = ""
    return result


def sanitize_legibility(data: dict, valid_refs: list[str]) -> dict:
    result = deepcopy(data)
    report = result.get("legibility_report")
    if not isinstance(report, dict):
        result["legibility_report"] = {}
        result["legibility_metadata_uncertain"] = True
        return result
    for field in ("difficult_questions", "illegible_questions"):
        values = report.get(field)
        if not isinstance(values, list):
            report[field] = []
            result["legibility_metadata_uncertain"] = True
            continue
        cleaned = []
        for raw in values:
            mapped = (canonical_ref(raw, valid_refs) if valid_refs
                      else plausible_unbound_ref(raw))
            if mapped and mapped not in cleaned:
                cleaned.append(mapped)
        if len(cleaned) != len(values):
            result["legibility_metadata_uncertain"] = True
        report[field] = cleaned
    return result


def postprocess_stage1(data: dict, valid_refs: list[str]) -> dict:
    value = apply_visible_question_refs(data, valid_refs)
    value = apply_page_manifest_refs(value, valid_refs)
    value = merge_leading_continuations(value, valid_refs)
    value = split_tables_by_row_ref(value, valid_refs)
    value = snap_refs_to_paper(value, valid_refs)
    return sanitize_legibility(value, valid_refs)


def expected_page_keys(inventory: list[dict]) -> set[tuple[int, int]]:
    expected = set()
    for item in inventory or []:
        try:
            document = int(item["document_index"])
            pages = item.get("page_numbers")
            if pages is None:
                pages = range(1, int(item["page_count"]) + 1)
            expected.update((document, int(page)) for page in pages
                            if document > 0 and int(page) > 0)
        except (KeyError, TypeError, ValueError):
            continue
    return expected


def inventory_errors(data: dict, inventory: list[dict], *, allowed_images: set[int] | None = None) -> list[str]:
    expected = expected_page_keys(inventory)
    expected_documents = {document for document, _ in expected}
    allowed_images = {int(value) for value in (allowed_images or set())}
    known_documents = expected_documents | allowed_images
    errors: list[str] = []
    for position, row in enumerate(data.get("page_manifest", []) or [], 1):
        if not isinstance(row, dict):
            errors.append(f"page_manifest[{position}] is not an object"); continue
        try:
            key = (int(row.get("document_index")), int(row.get("page_number")))
        except (TypeError, ValueError):
            errors.append(f"page_manifest[{position}] has an invalid page key"); continue
        if key not in expected:
            errors.append(f"page_manifest[{position}] references absent document/page {key}")
    for section in ("text_answers", "tables", "numerical_workings"):
        for position, item in enumerate(data.get(section, []) or [], 1):
            if not isinstance(item, dict):
                continue
            try:
                document = int(item.get("source_document_index"))
            except (TypeError, ValueError):
                errors.append(f"{section}[{position}] has an invalid source document"); continue
            if document not in known_documents:
                errors.append(f"{section}[{position}] references absent document {document}"); continue
            try:
                pages = [int(page) for page in (item.get("source_pages") or [])]
            except (TypeError, ValueError):
                errors.append(f"{section}[{position}] has invalid source pages"); continue
            if not pages:
                errors.append(f"{section}[{position}] has no source page"); continue
            if document in allowed_images:
                continue
            invalid = [page for page in pages if (document, page) not in expected]
            if invalid:
                errors.append(f"{section}[{position}] references absent page(s) {invalid}")
    return errors


def _page_ref_key(value: object) -> str:
    raw = str(value or "").strip()
    raw = re.sub(r"^(?:answer|ans|question|q)\.?\s*[-.:]?\s*", "", raw, flags=re.I)
    if not raw:
        return ""
    alternative = re.match(r"^(\d+)([A-Z])(?![A-Za-z])", raw)
    if alternative:
        tokens = [alternative.group(1), f"!{alternative.group(2).lower()}",
                  *re.findall(r"[0-9]+|[A-Za-z]+", raw[alternative.end():])]
    else:
        tokens = re.findall(r"[0-9]+|[A-Za-z]+", raw)
    if not tokens or not tokens[0].isdigit():
        return ""
    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
             "vii": "7", "viii": "8", "ix": "9", "x": "10", "xi": "11", "xii": "12"}
    return "|".join(token if token.startswith("!") else roman.get(token.lower(), token.lower())
                    for token in tokens)


def page_gaps(data: dict, inventory: list[dict]) -> list[dict]:
    expected = expected_page_keys(inventory)
    observed: dict[tuple[int, int], list[dict]] = {}
    for row in data.get("page_manifest", []) or []:
        if not isinstance(row, dict):
            continue
        try:
            key = (int(row.get("document_index")), int(row.get("page_number")))
        except (TypeError, ValueError):
            continue
        if key in expected:
            observed.setdefault(key, []).append(row)
    evidence: dict[tuple[int, int], dict] = {}
    for section in ("text_answers", "tables", "numerical_workings"):
        for item in data.get(section, []) or []:
            if not isinstance(item, dict):
                continue
            try:
                document = int(item.get("source_document_index"))
                pages = {int(page) for page in item.get("source_pages", [])}
            except (TypeError, ValueError):
                continue
            if section == "text_answers":
                has_content = bool(str(item.get("raw_text") or "").strip()
                    or item.get("selected_options") or item.get("has_diagrams") or item.get("has_tables"))
            elif section == "tables":
                has_content = bool(item.get("headers") or item.get("rows"))
            else:
                has_content = bool(str(item.get("formula_used") or "").strip()
                    or item.get("figures_substituted") or str(item.get("final_answer") or "").strip()
                    or item.get("working_shown"))
            if not has_content:
                continue
            raw_refs = [item.get("question_ref"), item.get("visible_question_ref")]
            if section == "tables":
                for field in ("row_question_refs", "row_visible_question_refs"):
                    if isinstance(item.get(field), list):
                        raw_refs.extend(item[field])
            refs = {key for raw in raw_refs if (key := _page_ref_key(raw))}
            for page in pages:
                bucket = evidence.setdefault((document, page), {"artifact_count": 0, "question_refs": set()})
                bucket["artifact_count"] += 1; bucket["question_refs"].update(refs)

    def compatible(left: str, right: str) -> bool:
        return left == right or left.startswith(right + "|") or right.startswith(left + "|")

    gaps: list[dict] = []
    for document, page in sorted(expected):
        rows = observed.get((document, page), [])
        if len(rows) != 1:
            gaps.append({"document_index": document, "page_number": page,
                         "reason": "missing" if not rows else "duplicate"}); continue
        row = rows[0]; status = str(row.get("status") or "").strip().lower()
        if status not in {"content", "blank", "unreadable"}:
            gaps.append({"document_index": document, "page_number": page, "reason": "invalid_status"}); continue
        if status == "unreadable":
            gaps.append({"document_index": document, "page_number": page, "reason": "unreadable"}); continue
        found = evidence.get((document, page), {"artifact_count": 0, "question_refs": set()})
        raw_manifest = row.get("question_refs") if isinstance(row.get("question_refs"), list) else []
        manifest_refs = {key for raw in raw_manifest if (key := _page_ref_key(raw))}
        present = row.get("answer_content_present")
        if status == "blank" and (found["artifact_count"] or present is True or manifest_refs):
            gaps.append({"document_index": document, "page_number": page, "reason": "blank_with_answer_evidence"}); continue
        if status != "content":
            continue
        if present is False and found["artifact_count"]:
            gaps.append({"document_index": document, "page_number": page, "reason": "answer_content_flag_mismatch"}); continue
        if (present is True or manifest_refs) and not found["artifact_count"]:
            gaps.append({"document_index": document, "page_number": page, "reason": "content_without_extraction"}); continue
        uncovered = sorted(ref for ref in manifest_refs if not any(compatible(ref, evidence_ref) for evidence_ref in found["question_refs"]))
        if uncovered:
            gaps.append({"document_index": document, "page_number": page,
                         "reason": "manifest_ref_without_extraction", "question_refs": uncovered}); continue
        unlisted = sorted(ref for ref in found["question_refs"] if (present is True or manifest_refs)
                          and not any(compatible(manifest_ref, ref) for manifest_ref in manifest_refs))
        if unlisted:
            gaps.append({"document_index": document, "page_number": page,
                         "reason": "extraction_ref_without_manifest", "question_refs": unlisted})
    return gaps


def merge_page_repairs(primary: dict, repair: dict, repaired: set[tuple[int, int]]) -> dict:
    merged = deepcopy(primary)
    for section in ("text_answers", "tables", "numerical_workings"):
        values = []
        for value in primary.get(section, []) or []:
            if not isinstance(value, dict):
                values.append(value); continue
            try:
                keys = {(int(value["source_document_index"]), int(page)) for page in value.get("source_pages", [])}
            except (KeyError, TypeError, ValueError):
                keys = set()
            if not keys or not keys.issubset(repaired):
                values.append(value)
        seen = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values if isinstance(value, dict)}
        for value in repair.get(section, []) or []:
            if not isinstance(value, dict):
                continue
            try:
                keys = {(int(value["source_document_index"]), int(page)) for page in value.get("source_pages", [])}
            except (KeyError, TypeError, ValueError):
                continue
            marker = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if keys and keys.issubset(repaired) and marker not in seen:
                values.append(value); seen.add(marker)
        merged[section] = values
    def key(row: dict) -> tuple[int, int] | None:
        try: return int(row["document_index"]), int(row["page_number"])
        except (KeyError, TypeError, ValueError): return None
    merged["page_manifest"] = [row for row in primary.get("page_manifest", []) if key(row) not in repaired]
    merged["page_manifest"] += [row for row in repair.get("page_manifest", []) if key(row) in repaired]
    merged["page_manifest"].sort(key=lambda row: key(row) or (0, 0))
    merged["targeted_page_repairs"] = [{"document_index": d, "page_number": p} for d, p in sorted(repaired)]
    primary_report = deepcopy(primary.get("legibility_report") or {})
    repair_report = repair.get("legibility_report") or {}
    for field in ("difficult_questions", "illegible_questions"):
        combined = []
        for source in (primary_report.get(field) or [], repair_report.get(field) or []):
            if not isinstance(source, (list, tuple, set)):
                continue
            for raw_ref in source:
                ref = str(raw_ref or "").strip()
                if ref and ref not in combined:
                    combined.append(ref[:100])
        primary_report[field] = combined
    merged["legibility_report"] = primary_report
    if primary.get("legibility_metadata_uncertain") is True or repair.get("legibility_metadata_uncertain") is True:
        merged["legibility_metadata_uncertain"] = True
    return merged


def flag_unverified_pages(data: dict, gaps: list[dict], *, repair_attempted: bool) -> dict:
    result = deepcopy(data)
    pages = [{"document_index": int(gap["document_index"]), "page_number": int(gap["page_number"]),
              "reason": str(gap.get("reason") or "unverified")[:80]} for gap in gaps]
    affected: list[str] = []
    unresolved = {(row["document_index"], row["page_number"]) for row in pages}
    for section in ("text_answers", "tables", "numerical_workings"):
        for item in result.get(section, []) or []:
            if not isinstance(item, dict): continue
            try: keys = {(int(item["source_document_index"]), int(page)) for page in item.get("source_pages", [])}
            except (KeyError, TypeError, ValueError): continue
            if keys & unresolved:
                item["page_verification_uncertain"] = True
                ref = str(item.get("question_ref") or "").strip()
                if ref and ref not in affected: affected.append(ref)
    verification = {"status": "partial", "repair_attempted": repair_attempted,
                    "requires_review": True, "unverified_pages": pages}
    if affected:
        verification["affected_question_refs"] = affected
    result["page_verification"] = verification
    return result


def build_page_mapping(data: dict) -> dict:
    mapping: dict[str, list[dict]] = {}
    for section in ("text_answers", "tables", "numerical_workings"):
        for item in data.get(section, []) or []:
            if not isinstance(item, dict): continue
            ref = str(item.get("question_ref") or "").strip()
            if not ref: continue
            try:
                document = int(item["source_document_index"])
                pages = [int(page) for page in item.get("source_pages", [])]
            except (KeyError, TypeError, ValueError): continue
            entries = mapping.setdefault(ref, [])
            for page in pages:
                value = {"document_index": document, "page_number": page}
                if value not in entries: entries.append(value)
    return mapping


def question_guide_from_paper(paper: dict) -> list[dict]:
    """Use a linked generated paper when it has a structured question breakdown."""
    payload = paper.get("paper_payload") or {}
    guide: list[dict] = []
    for section in payload.get("sections", []) if isinstance(payload, dict) else []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []) or []:
            if not isinstance(question, dict):
                continue
            ref = str(question.get("number") or question.get("question_ref") or "").strip()
            if not ref:
                continue
            guide.append({
                "question_ref": ref,
                "question_text": str(question.get("question_text") or question.get("text") or "")[:1000],
            })
    return guide


def _document_details(path: str, raw: bytes) -> tuple[str, list[dict], set[int]]:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if mime == "application/pdf" or raw.startswith(b"%PDF"):
        try:
            with fitz.open(stream=raw, filetype="pdf") as document:
                count = document.page_count
        except Exception as exc:
            raise Stage1PermanentError("The stored answer PDF cannot be opened.") from exc
        if count < 1:
            raise Stage1PermanentError("The stored answer PDF has no pages.")
        return "application/pdf", [{"document_index": 1, "page_count": count}], set()
    if mime in {"image/png", "image/jpeg", "image/webp"}:
        return mime, [], {1}
    raise Stage1PermanentError("The stored answer script has an unsupported file type.")


def _render_repair_pages(raw: bytes, pages: set[tuple[int, int]]) -> list[tuple[str, bytes]]:
    if any(document != 1 for document, _ in pages):
        raise Stage1PermanentError("Focused repair referenced an unavailable document.")
    rendered: list[tuple[str, bytes]] = []
    try:
        with fitz.open(stream=raw, filetype="pdf") as document:
            matrix = fitz.Matrix(300 / 72, 300 / 72)
            for _, page_number in sorted(pages):
                pixmap = document.load_page(page_number - 1).get_pixmap(matrix=matrix, alpha=False)
                rendered.append(("image/png", pixmap.tobytes("png")))
    except Exception as exc:
        raise Stage1RetryableError("Focused page rendering failed.") from exc
    return rendered


def _call_stage1(
    call: Callable[..., dict], files: list[tuple[str, bytes]], guide: list[dict],
    inventory: list[dict], *, tenant_id: str, job_id: str | None,
) -> dict:
    settings = get_settings()
    prompt = build_stage1_prompt(guide, inventory)
    try:
        with ai_call_context(
            "evaluation_stage1", tenant_id=tenant_id, evaluation_job_id=job_id,
        ):
            response = call(
                "Transcribe only. Do not evaluate or grade.", prompt, files,
                model=settings.gemini_stage1_model, temperature=0.0,
                schema=STAGE1_EXTRACTION_SCHEMA,
                max_output_tokens=settings.gemini_stage1_max_output_tokens,
                thinking_budget=settings.gemini_stage1_thinking_budget,
            )
    except Stage1RetryableError:
        raise
    except Exception as exc:
        raise Stage1RetryableError("Stage 1 provider call failed.") from exc
    return _validate_contract(response)


def run_stage1(
    service, submission: dict, paper: dict, *, job_id: str | None = None,
    explicit_re_evaluation: bool = False,
    gemini_call: Callable[..., dict] = gemini_json_multimodal,
) -> Stage1Outcome:
    """Run or safely reuse the pure-transcription Stage 1 result."""
    source = str(submission.get("answer_script_path") or "")
    if not source:
        raise Stage1PermanentError("Submission has no stored answer script.")
    cached = submission.get("stage1_extraction")
    if (not explicit_re_evaluation and submission.get("stage1_extraction_source") == source
            and isinstance(cached, dict) and all(key in cached for key in REQUIRED_KEYS)):
        return Stage1Outcome(cached, source, submission.get("page_mapping") or build_page_mapping(cached),
                             stage1_requires_review(cached))
    try:
        raw = download_bytes(source, bucket=EVALUATION_SUBMISSIONS_BUCKET)
    except Exception as exc:
        raise Stage1RetryableError("Could not download the stored answer script.") from exc
    mime, inventory, image_documents = _document_details(source, raw)
    guide = question_guide_from_paper(paper)
    valid_refs = [row["question_ref"] for row in guide]

    primary: dict | None = None
    provenance_errors: list[str] = []
    for _attempt in range(2):
        candidate = postprocess_stage1(
            _call_stage1(gemini_call, files, guide, inventory,
                         tenant_id=str(submission["tenant_id"]), job_id=job_id),
            valid_refs,
        )
        provenance_errors = inventory_errors(candidate, inventory, allowed_images=image_documents)
        if not provenance_errors:
            primary = candidate
            break
        logger.warning("Rejected Stage 1 invented provenance; retrying cleanly")
    if primary is None:
        raise Stage1RetryableError("Stage 1 repeatedly returned impossible provenance.")

    if stage1_blocks_grading(primary):
        return Stage1Outcome(primary, source, build_page_mapping(primary), True)

    gaps = page_gaps(primary, inventory)
    paid_gaps = [gap for gap in gaps if gap.get("reason") in PAID_GAP_REASONS]
    repair_attempted = False
    repair_reference: dict | None = None
    if paid_gaps and len(paid_gaps) <= MAX_REPAIR_PAGES and mime == "application/pdf":
        repair_attempted = True
        repaired_keys = {(int(gap["document_index"]), int(gap["page_number"])) for gap in paid_gaps}
        repair_inventory = [{"document_index": 1,
                             "page_numbers": [page for document, page in sorted(repaired_keys) if document == 1]}]
        try:
            repair_files = _render_repair_pages(raw, repaired_keys)
            repair_reference = postprocess_stage1(
                _call_stage1(gemini_call, repair_files, guide, repair_inventory,
                             tenant_id=str(submission["tenant_id"]), job_id=job_id),
                valid_refs,
            )
            if inventory_errors(repair_reference, repair_inventory):
                raise Stage1RetryableError("Focused repair invented provenance.")
            primary = merge_page_repairs(primary, repair_reference, repaired_keys)
            gaps = page_gaps(primary, inventory)
        except Exception as exc:
            logger.warning("Discarded focused Stage 1 repair (%s)", type(exc).__name__)
            gaps = page_gaps(primary, inventory)
    # ExamApp treats manifest/question mapping disagreements as audit telemetry,
    # not as proof that the page is missing or unreadable. Only unresolved
    # physical-page gaps are marked uncertain and routed to review after grading.
    unresolved_physical = [
        gap for gap in gaps if gap.get("reason") in PAID_GAP_REASONS
    ]
    mapping_only = len(gaps) - len(unresolved_physical)
    if mapping_only:
        logger.info(
            "Stage 1 kept %d page/question mapping disagreement(s) as audit telemetry",
            mapping_only,
        )
    if unresolved_physical:
        primary = flag_unverified_pages(
            primary,
            unresolved_physical,
            repair_attempted=repair_attempted,
        )
    requires_review = stage1_requires_review(primary)
    return Stage1Outcome(primary, source, build_page_mapping(primary), requires_review)
    files = [(mime, raw)]
