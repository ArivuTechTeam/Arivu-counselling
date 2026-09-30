"""Extract, generate, validate, and freeze one evaluation-paper rubric."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import mimetypes
import re
from typing import Callable

from app.lib.config import get_settings
from app.lib.storage import EVALUATION_PAPERS_BUCKET, download_bytes
from app.services.ai_call_logging import ai_call_context
from app.services.commerce_context import format_commerce_context, resolve_paper_profile
from app.services.evaluation_rubric_contract import (
    CRITERION_CATEGORIES,
    STRUCTURED_QA_SCHEMA,
    build_rubric_prompt,
)
from app.services.extraction import MIN_READABLE_PDF_TEXT_CHARS, extract_text_with_pages
from app.services.llm.structured import complete_json_large, gemini_json_multimodal


class RubricPermanentError(RuntimeError):
    """Stored input or twice-invalid output that a queue retry cannot repair."""


@dataclass(frozen=True)
class RubricOutcome:
    questions: list[dict]
    question_structure: dict
    source: str
    question_text: str
    answer_text: str


@dataclass(frozen=True)
class RubricValidation:
    questions: list[dict]
    question_structure: dict
    errors: list[str]


def _ref_key(value: object) -> str:
    raw = re.sub(r"^(?:question|q)\.?\s*[-:]?\s*", "", str(value or "").strip(), flags=re.I)
    return "|".join(re.findall(r"[0-9]+|[A-Za-z]+", raw.lower()))


def _printed_ref(value: object) -> bool:
    raw = str(value or "").strip()
    return bool(re.fullmatch(
        r"(?:Q(?:uestion)?\s*)?(?:[A-Za-z]+-)?\d+"
        r"(?:(?:\.\d+)|(?:\([A-Za-z0-9]+\))|[A-Za-z]|(?:-\d+))*",
        raw,
        flags=re.I,
    ))


def _half(value: float) -> bool:
    return value > 0 and abs(value * 2 - round(value * 2)) <= 1e-6


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _normalize_misapplied_paper_total(
    questions: object, raw_structure: object, total_marks: float
) -> set[str]:
    """Repair only the proven all-compulsory copied-paper-total shape."""
    if (
        not isinstance(questions, list)
        or len(questions) < 2
        or not isinstance(raw_structure, dict)
        or total_marks <= 0
        or raw_structure.get("optional_groups")
    ):
        return set()
    compulsory = {_ref_key(ref) for ref in raw_structure.get("compulsory", [])}
    compulsory.discard("")
    question_keys = {
        _ref_key(row.get("question_ref")) for row in questions if isinstance(row, dict)
    }
    question_keys.discard("")
    if not question_keys or question_keys != compulsory:
        return set()
    for row in questions:
        if not isinstance(row, dict):
            return set()
        question_key = _ref_key(row.get("question_ref"))
        if (
            row.get("marks_source") != "derived_from_parent"
            or not question_key
            or _ref_key(row.get("parent_question_ref")) != question_key
            or abs(_number(row.get("parent_total_marks")) - total_marks) > 1e-6
        ):
            return set()
    share = total_marks / len(questions)
    if not _half(share):
        return set()
    for row in questions:
        row["parent_question_ref"] = "PAPER_TOTAL"
        row["parent_total_marks"] = total_marks
    return question_keys


def _rescale_recovered_criteria(criteria: list[dict], marks: float) -> None:
    """Rescale copied-total criteria onto the authoritative half-mark grid."""
    units = int(round(marks * 2))
    if not criteria or len(criteria) > units:
        return
    weights = [max(_number(row.get("marks")), 0.0) for row in criteria]
    if sum(weights) <= 0:
        return
    assigned = [1] * len(criteria)
    remaining = units - len(criteria)
    raw = [remaining * weight / sum(weights) for weight in weights]
    floors = [int(value) for value in raw]
    assigned = [base + extra for base, extra in zip(assigned, floors)]
    for index in sorted(
        range(len(criteria)), key=lambda item: raw[item] - floors[item], reverse=True
    )[: remaining - sum(floors)]:
        assigned[index] += 1
    for row, value in zip(criteria, assigned):
        row["marks"] = value / 2


def _reconcile_parent_marks(questions: list[dict]) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for question in questions:
        key = _ref_key(question.get("parent_question_ref"))
        if key:
            groups.setdefault(key, []).append(question)
    errors: list[str] = []
    for key, siblings in groups.items():
        derived = [q for q in siblings if q["marks_source"] == "derived_from_parent"]
        if not derived:
            continue
        totals = [q["parent_total_marks"] for q in siblings]
        if (any(total <= 0 for total in totals)
                or max(totals) - min(totals) > 1e-6
                or any(q["marks_source"] not in {"printed", "derived_from_parent"}
                       for q in siblings)):
            errors.append(f"invalid parent metadata for {key}")
            continue
        parent_total = totals[0]
        printed = sum(q["marks"] for q in siblings if q["marks_source"] == "printed")
        remainder = parent_total - printed
        share = remainder / len(derived)
        if _half(share):
            for question in derived:
                question["marks"] = round(share * 2) / 2
        elif not (all(_half(q["marks"]) for q in derived)
                  and abs(sum(q["marks"] for q in derived) - remainder) <= 1e-6):
            errors.append(f"unverified child allocation for {key}")
            continue
        if abs(sum(q["marks"] for q in siblings) - parent_total) > 1e-6:
            errors.append(f"children do not sum to parent {key}")
    return errors


def _top_ref(ref: str, candidates: dict[str, str]) -> str:
    key = _ref_key(ref)
    if key in candidates:
        return candidates[key]
    matches = [(candidate.count("|") + 1, value) for candidate, value in candidates.items()
               if key.startswith(candidate + "|")]
    return max(matches, default=(0, ""))[1]


def _validate_structure(raw: object, questions: list[dict], total_marks: float) -> dict:
    """Preserve uncertain structure, correcting pick only in the unique safe case."""
    if not isinstance(raw, dict):
        raw = {}
    result = deepcopy(raw)
    compulsory = result.get("compulsory") if isinstance(result.get("compulsory"), list) else []
    raw_groups = result.get("optional_groups") if isinstance(result.get("optional_groups"), list) else []
    top_values = [str(value).strip() for value in compulsory]
    for group in raw_groups:
        if isinstance(group, dict) and isinstance(group.get("questions"), list):
            top_values.extend(str(value).strip() for value in group["questions"])
    tops = {_ref_key(value): value for value in top_values if _ref_key(value)}
    by_top = {value: 0.0 for value in tops.values()}
    for question in questions:
        top = _top_ref(question["question_ref"], tops) or _top_ref(
            question["parent_question_ref"], tops
        )
        if top:
            by_top[top] = by_top.get(top, 0.0) + question["marks"]

    review_reasons: list[str] = []
    groups: list[dict] = []
    used: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            review_reasons.append("an optional group is not an object")
            continue
        refs = [str(value).strip() for value in raw_group.get("questions", []) if str(value).strip()]
        printed = _number(raw_group.get("printed_pick"))
        pick = _number(raw_group.get("pick"))
        valid_whole = all(abs(value - round(value)) <= 1e-6 for value in (printed, pick))
        overlap = bool(used.intersection(refs)); used.update(refs)
        if not refs or not valid_whole or printed < 1 or printed > len(refs):
            review_reasons.append(f"optional group {index + 1} has unresolved pick metadata")
        if overlap:
            review_reasons.append(f"optional group {index + 1} overlaps another group")
        groups.append({
            "label": str(raw_group.get("label") or f"Optional group {index + 1}"),
            "printed_pick": int(round(printed)) if printed else raw_group.get("printed_pick"),
            "pick": int(round(pick)) if pick else raw_group.get("pick"),
            "questions": refs,
        })

    clean_compulsory = [str(value).strip() for value in compulsory if str(value).strip()]
    compulsory_total = sum(by_top.get(ref, 0.0) for ref in clean_compulsory)
    adjusted = False
    reason = str(result.get("adjustment_reason") or "").strip()
    if len(groups) == 1 and not review_reasons and total_marks > 0:
        group = groups[0]
        unit_marks = [by_top.get(ref, 0.0) for ref in group["questions"]]
        if unit_marks and min(unit_marks) > 0 and max(unit_marks) - min(unit_marks) <= 1e-6:
            exact = (total_marks - compulsory_total) / unit_marks[0]
            unique = int(round(exact))
            if abs(exact - unique) <= 1e-6 and 1 <= unique <= len(unit_marks):
                printed = group["printed_pick"]
                if isinstance(printed, int) and printed != unique:
                    group["pick"] = unique
                    adjusted = True
                    reason = (
                        f"Verified correction: {compulsory_total:g} + "
                        f"({unique} x {unit_marks[0]:g}) = {total_marks:g}"
                    )
            elif group.get("pick") != group.get("printed_pick"):
                group["pick"] = group.get("printed_pick")
                review_reasons.append("printed pick cannot be uniquely reconciled")
        elif group.get("pick") != group.get("printed_pick"):
            group["pick"] = group.get("printed_pick")
            review_reasons.append("optional choices do not have equal verified marks")
    elif any(group.get("pick") != group.get("printed_pick") for group in groups):
        for group in groups:
            group["pick"] = group.get("printed_pick")
        review_reasons.append("pick adjustment is not a single uniquely provable correction")

    if review_reasons:
        reason = "; ".join(dict.fromkeys(filter(None, [reason, *review_reasons])))[:1000]
    return {
        "compulsory": clean_compulsory,
        "optional_groups": groups,
        "printed_required_marks": _number(result.get("printed_required_marks")),
        "configured_total_marks": total_marks,
        "structure_adjusted": adjusted,
        "requires_admin_review": bool(result.get("requires_admin_review")) or bool(review_reasons),
        "adjustment_reason": reason,
        "unresolved_original": deepcopy(raw) if review_reasons else None,
        "source": "rubric_extraction",
        "backend_validated": True,
    }


def validate_rubric(candidate: object, question_paper_text: str, total_marks: float) -> RubricValidation:
    """Strict deterministic gate. No invalid per-question rubric crosses it."""
    if not isinstance(candidate, dict) or not isinstance(candidate.get("questions"), list):
        return RubricValidation([], _validate_structure({}, [], total_marks),
                                ["response must contain a questions array"])
    candidate = deepcopy(candidate)
    recovered_paper_total = _normalize_misapplied_paper_total(
        candidate["questions"], candidate.get("paper_structure"), total_marks
    )
    errors: list[str] = []
    questions: list[dict] = []
    required = set(STRUCTURED_QA_SCHEMA["properties"]["questions"]["items"]["required"])
    paper_haystack = _normalized_text(question_paper_text)
    for index, raw in enumerate(candidate["questions"]):
        if not isinstance(raw, dict):
            errors.append(f"questions[{index}] is not an object")
            continue
        missing = sorted(required - raw.keys())
        if missing:
            errors.append(f"questions[{index}] omitted: {', '.join(missing)}")
            continue
        ref = str(raw.get("question_ref") or "").strip()
        text = str(raw.get("question_text") or "").strip()
        marks = _number(raw.get("marks"))
        source = str(raw.get("marks_source") or "").strip()
        parent = str(raw.get("parent_question_ref") or "").strip()
        parent_total = _number(raw.get("parent_total_marks"))
        qtype = str(raw.get("question_type") or "").strip()
        if not ref or not _ref_key(ref) or not _printed_ref(ref):
            errors.append(f"questions[{index}] has no usable printed ref")
        if not text or _normalized_text(text) not in paper_haystack:
            errors.append(f"{ref or index}: question_text is not verbatim paper text")
        if source not in {"printed", "derived_from_parent"}:
            errors.append(f"{ref or index}: marks_source is unverified")
        if not parent or parent_total <= 0:
            errors.append(f"{ref or index}: parent mark metadata is missing")
        if not _half(marks): errors.append(f"{ref or index}: marks must be positive 0.5 increments")
        if qtype not in {"descriptive", "mcq_single"}:
            errors.append(f"{ref or index}: unsupported question_type")
        criteria = raw.get("evaluation_criteria")
        if not isinstance(criteria, list) or not criteria:
            errors.append(f"{ref or index}: evaluation_criteria is empty")
            criteria = []
        if _ref_key(ref) in recovered_paper_total and isinstance(criteria, list):
            _rescale_recovered_criteria(criteria, total_marks / len(candidate["questions"]))
        cleaned_criteria: list[dict] = []
        for cidx, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                errors.append(f"{ref or index}: criterion {cidx + 1} is not an object")
                continue
            wording = " ".join(str(criterion.get("criterion") or "").split())
            cmarks = _number(criterion.get("marks"))
            category = str(criterion.get("category") or "").strip()
            if (len(wording) < 4 or wording.casefold() in {
                    "correct answer", "overall correctness", "accuracy", "correctness",
                    "overall correctness per the suggested answer"}):
                errors.append(f"{ref or index}: criterion {cidx + 1} is vague or empty")
            if not _half(cmarks):
                errors.append(f"{ref or index}: criterion {cidx + 1} is not on the half-mark grid")
            if category not in CRITERION_CATEGORIES:
                errors.append(f"{ref or index}: criterion {cidx + 1} category is invalid")
            cleaned_criteria.append({"criterion": wording, "marks": cmarks, "category": category})
        criteria_target = (
            total_marks / len(candidate["questions"])
            if _ref_key(ref) in recovered_paper_total
            else marks
        )
        if abs(sum(item["marks"] for item in cleaned_criteria) - criteria_target) > 1e-6:
            errors.append(f"{ref or index}: criteria do not sum exactly to question marks")
        if marks > 0 and len(cleaned_criteria) > round(marks * 2):
            errors.append(f"{ref or index}: criterion count exceeds marks x 2")
        options = raw.get("options") if isinstance(raw.get("options"), list) else []
        correct = str(raw.get("correct_option") or "").strip()
        if qtype == "mcq_single":
            labels = [str(option.get("label") or "").strip() for option in options
                      if isinstance(option, dict)]
            normalized = [_ref_key(label) for label in labels]
            if len(labels) < 2 or len(set(normalized)) != len(labels) or _ref_key(correct) not in normalized:
                errors.append(f"{ref or index}: MCQ options/correct option are not deterministic")
            if len(cleaned_criteria) != 1 or not cleaned_criteria or abs(cleaned_criteria[0]["marks"] - marks) > 1e-6:
                errors.append(f"{ref or index}: MCQ must have exactly one full-mark criterion")
        elif options or correct:
            errors.append(f"{ref or index}: descriptive question must not carry MCQ fields")
        printed_match = re.search(r"[\[(]\s*(\d+(?:\.5)?)\s*marks?\s*[\])]", text, flags=re.I)
        if source == "printed" and printed_match and abs(float(printed_match.group(1)) - marks) > 1e-6:
            errors.append(f"{ref or index}: printed child marks were overwritten")
        questions.append({
            "question_ref": ref, "question_text": text,
            "topic": str(raw.get("topic") or "").strip(),
            "suggested_answer": str(raw.get("suggested_answer") or "").strip(),
            "question_type": qtype, "options": deepcopy(options),
            "correct_option": correct,
            "expected_answer_points": [str(point).strip() for point in raw.get("expected_answer_points", [])
                                       if str(point).strip()],
            "marks": marks, "marks_source": source,
            "parent_question_ref": parent, "parent_total_marks": parent_total,
            "evaluation_criteria": cleaned_criteria,
        })
    keys = [_ref_key(question["question_ref"]) for question in questions]
    duplicate = sorted({key for key in keys if key and keys.count(key) > 1})
    if duplicate: errors.append("duplicate question_ref values after normalization: " + ", ".join(duplicate))
    errors.extend(_reconcile_parent_marks(questions))
    # Parent reconciliation may change marks; criteria are intentionally rechecked.
    for question in questions:
        if abs(sum(item["marks"] for item in question["evaluation_criteria"]) - question["marks"]) > 1e-6:
            message = f"{question['question_ref']}: criteria do not match reconciled child marks"
            if message not in errors: errors.append(message)
    structure = _validate_structure(candidate.get("paper_structure"), questions, total_marks)
    return RubricValidation(questions, structure, errors)


def _mime(path: str) -> str:
    guessed = mimetypes.guess_type(path)[0]
    return guessed if guessed in {"application/pdf", "image/png", "image/jpeg"} else "application/pdf"


def extract_paper_text(
    path: str, *, vision_call: Callable[..., dict] = gemini_json_multimodal,
) -> str:
    """Reuse pdfplumber for typed PDFs and use Gemini only for images/scans."""
    try:
        raw = download_bytes(path, bucket=EVALUATION_PAPERS_BUCKET)
    except Exception as exc:
        raise RuntimeError("Could not download an evaluation-paper document.") from exc
    mime = _mime(path)
    if mime == "application/pdf":
        try:
            extracted = extract_text_with_pages(raw, "pdf").text
            if len(extracted.strip()) >= MIN_READABLE_PDF_TEXT_CHARS:
                return extracted.strip()
        except Exception:
            pass
    schema = {
        "type": "OBJECT", "properties": {"text": {"type": "STRING"}},
        "required": ["text"],
    }
    response = vision_call(
        "Transcribe this exam document verbatim. Do not solve, summarize, or grade it.",
        "Return every visible question, instruction, mark, answer, table, and option in reading order.",
        [(mime, raw)], temperature=0.0, schema=schema,
        thinking_budget=0, max_output_tokens=get_settings().gemini_extraction_max_output_tokens,
    )
    text = str((response or {}).get("text") or "").strip()
    if not text:
        raise RubricPermanentError("The evaluation-paper document contained no readable text.")
    return text


def _context(service, paper: dict) -> tuple[str, str, str, str]:
    tenant = str(paper["tenant_id"])
    subject_id = str(paper["subject_id"])
    subject_row = (service.table("subjects").select("name,course_id,course_level_id")
                   .eq("id", subject_id).eq("tenant_id", tenant).maybe_single().execute().data or {})
    level_row = (service.table("course_levels").select("name,course_id")
                 .eq("id", str(paper["course_level_id"])).eq("tenant_id", tenant)
                 .maybe_single().execute().data or {})
    course_id = subject_row.get("course_id") or level_row.get("course_id")
    course_row = (service.table("courses").select("name").eq("id", course_id)
                  .eq("tenant_id", tenant).maybe_single().execute().data or {}) if course_id else {}
    commerce = format_commerce_context(resolve_paper_profile(service, tenant, subject_id)) or ""
    return (str(subject_row.get("name") or ""), str(course_row.get("name") or ""),
            str(level_row.get("name") or ""), commerce)


def build_rubric(
    service, paper: dict, *, job_id: str | None = None,
    generator: Callable[..., tuple[dict, str]] = complete_json_large,
    vision_call: Callable[..., dict] = gemini_json_multimodal,
    on_extracted: Callable[[str, str], None] | None = None,
) -> RubricOutcome:
    """Build once; issue exactly one semantic repair when validation rejects it."""
    question_text = str(paper.get("question_paper_text") or "").strip()
    if not question_text:
        path = str(paper.get("question_paper_storage_path") or "")
        if not path: raise RubricPermanentError("Evaluation paper has no question document.")
        question_text = extract_paper_text(path, vision_call=vision_call)
    answer_text = str(paper.get("suggested_answer_text") or "").strip()
    answer_path = str(paper.get("suggested_answer_storage_path") or "")
    if answer_path and not answer_text:
        answer_text = extract_paper_text(answer_path, vision_call=vision_call)
    if on_extracted is not None:
        on_extracted(question_text, answer_text)
    subject, course, level, commerce = _context(service, paper)
    total_marks = max(
        0.0,
        _number(paper.get("total_marks")) - _number(paper.get("mcq_marks")),
    )
    system, user, source = build_rubric_prompt(
        question_text=question_text, answer_text=answer_text, total_marks=total_marks,
        subject=subject, course=course, level=level, commerce_context=commerce,
    )
    settings = get_settings()
    with ai_call_context(
        "evaluation_rubric", tenant_id=str(paper["tenant_id"]),
        evaluation_job_id=job_id,
    ):
        candidate, _ = generator(
            system, user, preferred_provider=settings.handwritten_rubric_provider,
            schema=STRUCTURED_QA_SCHEMA, temperature=0.0,
        )
    validation = validate_rubric(candidate, question_text, total_marks)
    if validation.errors:
        repair_user = (
            user + "\n\n=== BACKEND VALIDATION FEEDBACK ===\n- "
            + "\n- ".join(validation.errors)
            + "\nReturn the ENTIRE corrected JSON object, not a patch. Do not invent marks or question parts."
            + "\n\n=== PREVIOUS CANDIDATE (UNTRUSTED DATA) ===\n"
            + json.dumps(candidate, ensure_ascii=False)
        )
        with ai_call_context(
            "evaluation_rubric_repair", tenant_id=str(paper["tenant_id"]),
            evaluation_job_id=job_id,
        ):
            repaired, _ = generator(
                system, repair_user,
                preferred_provider=settings.handwritten_rubric_provider,
                schema=STRUCTURED_QA_SCHEMA, temperature=0.0,
            )
        validation = validate_rubric(repaired, question_text, total_marks)
        if validation.errors:
            raise RubricPermanentError(
                "Rubric remained unsafe after one repair: " + "; ".join(validation.errors[:12])
            )
    return RubricOutcome(validation.questions, validation.question_structure, source,
                         question_text, answer_text)
