"""Pure direct-score-v2 evidence, validation, compilation, and choice rules."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
import re

from app.services.evaluation_references import normalize_question_ref, ref_is_descendant


class Stage2PermanentError(RuntimeError):
    pass


class Stage2RetryableError(RuntimeError):
    pass


class Stage2ContractError(Stage2PermanentError):
    """A response violates cross-question evidence ownership and is unusable."""


@dataclass(frozen=True)
class CompiledStage2:
    questions: list[dict]
    artifacts: list[dict]
    total_obtained: float
    total_possible: float
    requires_review: bool


def _decimal(value: object, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise Stage2PermanentError(f"Invalid {field}.")
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation
        return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise Stage2PermanentError(f"Invalid {field}.") from exc


def validate_fixed_rubric(rows: object) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise Stage2PermanentError("The fixed paper rubric is empty. No grading request was sent.")
    output, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise Stage2PermanentError("The fixed paper rubric contains a non-object question.")
        ref = str(raw.get("question_ref") or "").strip()
        norm = normalize_question_ref(ref)
        if not norm or norm in seen:
            raise Stage2PermanentError("The fixed paper rubric contains a missing or duplicate question reference. No grading request was sent.")
        seen.add(norm)
        criteria_raw = raw.get("evaluation_criteria")
        if not isinstance(criteria_raw, list) or not criteria_raw:
            raise Stage2PermanentError(f"Question {ref} has no fixed criteria. No grading request was sent.")
        criteria, criterion_ids = [], set()
        for index, criterion in enumerate(criteria_raw, start=1):
            if not isinstance(criterion, dict):
                raise Stage2PermanentError(f"Question {ref} has an invalid fixed criterion.")
            criterion_id = str(criterion.get("criterion_id") or f"c{index}").strip()
            if not criterion_id or criterion_id in criterion_ids:
                raise Stage2PermanentError(f"Question {ref} has duplicate fixed criterion IDs. No grading request was sent.")
            criterion_ids.add(criterion_id)
            marks = _decimal(criterion.get("marks"), f"criterion {criterion_id} marks for {ref}")
            if marks < 0:
                raise Stage2PermanentError(f"Question {ref} has negative fixed marks. No grading request was sent.")
            criteria.append({**deepcopy(criterion), "criterion_id": criterion_id, "marks": marks})
        total = _decimal(raw.get("marks", raw.get("total_marks", 0)), f"total marks for {ref}")
        if total < 0:
            raise Stage2PermanentError(f"Question {ref} has negative fixed marks. No grading request was sent.")
        criterion_total = float(sum((Decimal(str(row["marks"])) for row in criteria), Decimal("0.00")))
        if total == 0:
            total = criterion_total
        elif Decimal(str(total)) != Decimal(str(criterion_total)):
            raise Stage2PermanentError(
                f"Question {ref} has a fixed rubric worth {criterion_total:g} marks but the question is worth {total:g}. No grading request was sent."
            )
        output.append({**deepcopy(raw), "question_ref": ref, "total_marks": total,
                       "evaluation_criteria": criteria})
    return output


def _unsafe(item: dict) -> bool:
    text = str(item.get("raw_text") or item.get("text") or "")
    return bool(item.get("selection_ambiguous") or item.get("mapping_conflict")
                or item.get("continuation_merge_unresolved")
                or re.search(r"\b(?:ILLEGIBLE|UNREADABLE)\b", text, flags=re.I))


def _chunks(text: str) -> list[str]:
    """Split only at preserved lines, list boundaries, or strong sentence stops."""
    output: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])|(?=\s*(?:[-*•]|\d+[.)])\s+)", line)
        output.extend(part.strip() for part in parts if part.strip())
    return output


def _eid(kind: str, document: int, pages: list[int], item: int, part: int, text: str) -> str:
    source = f"{kind}|{document}|{','.join(map(str, pages))}|{item}|{part}|{text}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]


def _evidence(kind: str, item: dict, item_index: int, part_index: int, text: str,
              *, difficult_cells: list | None = None) -> dict:
    document = int(item.get("source_document_index") or 1)
    pages = sorted({int(page) for page in (item.get("source_pages") or [])})
    return {
        "evidence_id": _eid(kind, document, pages, item_index, part_index, text),
        "type": kind, "text": text, "document_index": document,
        "source_pages": pages,
        "extraction_uncertain": bool(
            _unsafe(item) or item.get("page_verification_uncertain") or difficult_cells
        ),
        "difficult_cells": list(difficult_cells or []),
    }


def build_evidence_groups(extraction: dict) -> tuple[list[dict], list[dict]]:
    """Return reference groups and signals that had no safe semantic evidence."""
    groups: dict[str, dict] = {}
    unsafe_signals: list[dict] = []
    last_ref = ""

    def target(item: dict) -> str:
        nonlocal last_ref
        raw = str(item.get("question_ref") or "").strip()
        norm = normalize_question_ref(raw)
        if norm:
            last_ref = raw
            return raw
        if (item.get("mapping_unresolved") or item.get("question_ref_unresolved")
                or item.get("continuation_merge_unresolved")):
            return ""
        return last_ref

    def add(ref: str, row: dict) -> None:
        if not ref:
            unsafe_signals.append(row); return
        group = groups.setdefault(ref, {"ref_group": ref, "evidence": [], "attempt_signal": False})
        group["evidence"].append(row)

    for index, item in enumerate(extraction.get("text_answers") or []):
        if not isinstance(item, dict): continue
        ref = target(item)
        selected = [str(value).strip() for value in item.get("selected_options") or [] if str(value).strip()]
        if selected:
            text = "Selected option: " + ", ".join(selected)
            row = _evidence("mcq_selection", item, index, 0, text)
            if item.get("selection_ambiguous"): unsafe_signals.append({**row, "ref_group": ref})
            else: add(ref, row)
        raw = str(item.get("raw_text") or "")
        if _unsafe(item):
            unsafe_signals.append({"ref_group": ref, "attempt_signal": bool(raw or item.get("has_diagrams")), "reason": "unsafe_text"})
            continue
        for part, text in enumerate(_chunks(raw)):
            add(ref, _evidence("text", item, index, part, text))
        if not raw and item.get("has_diagrams"):
            unsafe_signals.append({"ref_group": ref, "attempt_signal": True, "reason": "diagram_only"})

    for index, item in enumerate(extraction.get("tables") or []):
        if not isinstance(item, dict): continue
        ref = target(item); headers = [str(value or "").strip() for value in item.get("headers") or []]
        for part, cells in enumerate(item.get("rows") or []):
            cells = cells if isinstance(cells, list) else [cells]
            pairs = [f"{headers[i]}: {cell}" if i < len(headers) and headers[i] else str(cell)
                     for i, cell in enumerate(cells)]
            text = " | ".join(pairs).strip()
            if text:
                add(ref, _evidence("table_row", item, index, part, text,
                                   difficult_cells=item.get("difficult_cells") or []))

    for index, item in enumerate(extraction.get("numerical_workings") or []):
        if not isinstance(item, dict): continue
        ref = target(item)
        parts = [str(item.get("formula_used") or "").strip(),
                 *[str(v).strip() for v in item.get("figures_substituted") or []],
                 str(item.get("final_answer") or "").strip()]
        text = " | ".join(value for value in parts if value)
        if text and not _unsafe(item): add(ref, _evidence("numerical", item, index, 0, text))
        elif text: unsafe_signals.append({"ref_group": ref, "attempt_signal": True, "reason": "unsafe_numerical"})
    return list(groups.values()), unsafe_signals


def map_evidence_to_rubric(rubric: list[dict], extraction: dict) -> tuple[dict[str, dict], list[dict]]:
    groups, unsafe = build_evidence_groups(extraction)
    by_norm = {normalize_question_ref(row["question_ref"]): row for row in rubric}
    answers = {key: {"evidence": [], "attempt_signal": False} for key in by_norm}
    unmatched: list[dict] = []
    for group in groups:
        norm = normalize_question_ref(group["ref_group"])
        targets: list[str] = []
        if norm in by_norm:
            targets = [norm]
        else:
            descendants = [key for key in by_norm if ref_is_descendant(key, norm)]
            if descendants:
                targets = descendants
            else:
                ancestors = [key for key in by_norm if ref_is_descendant(norm, key)]
                if ancestors: targets = [max(ancestors, key=len)]
        if not targets:
            unmatched.append(group); continue
        for key in targets:
            answers[key]["evidence"].extend(deepcopy(group["evidence"]))
    for signal in unsafe:
        norm = normalize_question_ref(signal.get("ref_group"))
        targets = ([norm] if norm in by_norm else [key for key in by_norm if ref_is_descendant(key, norm)])
        if targets:
            for key in targets: answers[key]["attempt_signal"] = True
        else: unmatched.append(signal)
    return answers, unmatched


def answer_presence(answer: dict) -> str:
    # Evidence that survived Stage 1's safety filters remains scoreable even
    # when its page verification or legibility carries uncertainty. ExamApp
    # grades that preserved evidence, lowers confidence, and routes the report
    # to review; unsafe semantic fragments never enter this evidence list.
    if any(str(row.get("text") or "").strip()
           for row in answer.get("evidence") or []): return "substantive"
    if answer.get("attempt_signal") or answer.get("evidence"): return "attempted_ungradable"
    return "none"


def fixed_payload(rubric: list[dict], extraction: dict, *, rubric_source: str,
                  paper_context: dict) -> dict:
    validated = validate_fixed_rubric(rubric)
    answers, unmatched = map_evidence_to_rubric(validated, extraction)
    questions = []
    for row in validated:
        answer = answers[normalize_question_ref(row["question_ref"])]
        questions.append({
            "question_ref": row["question_ref"], "question_text": row.get("question_text", ""),
            "suggested_answer": row.get("suggested_answer", ""), "total_marks": row["total_marks"],
            "evaluation_criteria": row["evaluation_criteria"],
            "answer_presence": answer_presence(answer),
            "extraction_uncertain": any(e.get("extraction_uncertain") for e in answer["evidence"]),
            "student_evidence": answer["evidence"],
        })
    unmatched_rows = []
    for group in unmatched:
        for row in group.get("evidence") or []:
            unmatched_rows.append({**row, "extracted_ref_group": group.get("ref_group", "")})
    return {"grading_contract_version": "direct-score-v2", "rubric_source": rubric_source,
            "paper_context": {**paper_context, "contract_version": "direct-score-v2"}, "questions": questions,
            "other_unmatched_evidence": unmatched_rows}


def snap_half_away(value: float) -> float:
    return math.floor(abs(value) * 2 + 0.5) / 2 * (-1 if value < 0 else 1)


def direct_score_mark(value: object, maximum: float) -> float:
    if value is None or isinstance(value, bool):
        raise Stage2PermanentError("Invalid marks_awarded.")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise Stage2PermanentError("Invalid marks_awarded.") from exc
    if not math.isfinite(number):
        raise Stage2PermanentError("Invalid marks_awarded.")
    clamped = min(max(number, 0.0), maximum)
    if maximum <= 0: return 0.0
    if not math.isclose(maximum * 2, round(maximum * 2), abs_tol=1e-9):
        return round(maximum, 2) if math.isclose(clamped, maximum, abs_tol=1e-9) else 0.0
    if math.isclose(clamped, maximum, abs_tol=1e-9): return round(maximum, 2)
    return round(min(max(snap_half_away(clamped), 0.0), maximum), 2)


def deterministic_mcq(question: dict) -> dict | None:
    if question.get("question_type") != "mcq_single": return None
    options = question.get("options") or []; criteria = question.get("evaluation_criteria") or []
    labels = [re.sub(r"[^a-z0-9]+", "", str(row.get("label") or "").lower())
              for row in options if isinstance(row, dict)]
    correct = re.sub(r"[^a-z0-9]+", "", str(question.get("correct_option") or "").lower())
    total = float(question.get("total_marks", question.get("marks", 0)) or 0)
    if len(labels) < 2 or len(set(labels)) != len(labels) or correct not in labels \
            or len(criteria) != 1 or float(criteria[0].get("marks", 0) or 0) != total:
        return None
    evidence = question.get("student_evidence") or []
    selections = [re.sub(r"[^a-z0-9]+", "", str(row.get("text") or "").split(":", 1)[-1].lower())
                  for row in evidence if row.get("type") == "mcq_selection"]
    ambiguous = question.get("answer_presence") == "attempted_ungradable" or len(set(selections)) > 1
    blank = not selections and not ambiguous
    awarded = total if selections and selections[0] == correct and not ambiguous else 0.0
    return _base_result(question, awarded, "unsafe" if ambiguous else ("blank" if blank else "matched"),
                        not_attempted=blank, not_evaluated=ambiguous,
                        criteria=[{"criterion_id": criteria[0].get("criterion_id", "c1"),
                                   "criterion": criteria[0].get("criterion", "Correct selected option"),
                                   "marks_awarded": awarded, "marks_available": total,
                                   "category": criteria[0].get("category", "conceptual")}])


def _base_result(question: dict, obtained: float, status: str, *, not_attempted: bool,
                 not_evaluated: bool, criteria: list, feedback: str = "") -> dict:
    evidence = question.get("student_evidence") or []
    return {"question_ref": question["question_ref"], "question_text": question.get("question_text", ""),
            "marks_obtained": 0.0 if not_attempted or not_evaluated else round(obtained, 2),
            "marks_possible": question["total_marks"], "not_attempted": not_attempted,
            "not_evaluated": not_evaluated, "not_counted": False, "mapping_status": status,
            "feedback": feedback, "student_guidance": {},
            "student_answer_excerpt": "\n\n".join(str(row.get("text") or "") for row in evidence),
            "handwriting_legibility": "difficult" if question.get("extraction_uncertain") else "clear",
            "grading_confidence": 0.0 if not_evaluated else (0.7 if question.get("extraction_uncertain") else 1.0),
            "criteria_breakdown": criteria}


def compile_question(question: dict, parsed: dict, unmatched: list[dict]) -> dict:
    presence = question.get("answer_presence"); own = presence == "substantive"
    attempted = presence == "attempted_ungradable"
    unmatched_by_id = {row["evidence_id"]: row for row in unmatched}
    claimed = parsed.get("recovered_evidence_ids") or []
    if not isinstance(claimed, list):
        if own: claimed = []
        else: raise Stage2PermanentError(f"Question {question['question_ref']} returned invalid recovered evidence.")
    claimed = {str(value).strip() for value in claimed if str(value).strip()}
    unknown = claimed - unmatched_by_id.keys()
    if unknown and not own and not attempted:
        raise Stage2ContractError(f"Question {question['question_ref']} cited unknown unmatched evidence.")
    claimed -= unknown
    status = re.sub(r"[^a-z_]+", "", str(parsed.get("mapping_status") or "").lower())
    if own: status, not_attempted, not_evaluated, claimed = "matched", False, False, set()
    elif attempted: status, not_attempted, not_evaluated, claimed = "unsafe", False, True, set()
    elif claimed:
        if status not in {"recovered", "unsafe"}: raise Stage2PermanentError("Recovered evidence lacks a safe mapping decision.")
        not_attempted, not_evaluated = False, status == "unsafe"
    else: status, not_attempted, not_evaluated = "blank", True, False
    fixed = question["evaluation_criteria"]
    rows = parsed.get("criteria_breakdown")
    by_id: dict[str, dict] = {}
    if not not_attempted and not not_evaluated:
        if not isinstance(rows, list): raise Stage2PermanentError("Invalid criteria array.")
        expected = {row["criterion_id"] for row in fixed}
        for row in rows:
            if not isinstance(row, dict): continue
            cid = str(row.get("criterion_id") or "")
            if cid not in expected: continue
            if cid in by_id and by_id[cid] != row: raise Stage2PermanentError(f"Conflicting duplicate criterion {cid}.")
            by_id[cid] = row
        missing = expected - by_id.keys()
        if missing: raise Stage2PermanentError("Missing fixed criterion IDs: " + ", ".join(sorted(missing)))
    compiled, obtained = [], 0.0
    for row in fixed:
        provider = by_id.get(row["criterion_id"], {})
        award = direct_score_mark(provider.get("marks_awarded"), row["marks"]) if provider else 0.0
        obtained += award
        compiled.append({"criterion_id": row["criterion_id"], "criterion": row.get("criterion", ""),
                         "marks_awarded": award, "marks_available": row["marks"],
                         "category": row.get("category", "conceptual"),
                         "student_evidence": str(provider.get("student_evidence") or "").strip(),
                         "comment": str(provider.get("comment") or "").strip(),
                         "correct_treatment": str(provider.get("correct_treatment") or "").strip(),
                         "evidence_ids": sorted(claimed)})
    result = _base_result(question, obtained, status, not_attempted=not_attempted,
                          not_evaluated=not_evaluated, criteria=compiled,
                          feedback=str(parsed.get("feedback") or "").strip())
    improve = parsed.get("improve_next")
    result["student_guidance"] = {
        "what_you_did_well": str(parsed.get("what_you_did_well") or "").strip(),
        "improve_next": [str(value).strip() for value in improve if str(value).strip()]
        if isinstance(improve, list) else [],
    }
    if claimed:
        extra = [unmatched_by_id[eid]["text"] for eid in sorted(claimed)]
        result["student_answer_excerpt"] = "\n\n".join(filter(None, [result["student_answer_excerpt"], *extra]))
    return result


def parse_response(raw: str) -> dict:
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip())
    try: parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc: raise Stage2PermanentError("The grader returned invalid direct-score JSON.") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        raise Stage2PermanentError("The grader omitted the direct-score results array.")
    return parsed


def compile_response(payload: dict, raw: str) -> tuple[list[dict], bool]:
    parsed = parse_response(raw); expected = {normalize_question_ref(q["question_ref"]): q for q in payload["questions"]}
    rows: dict[str, dict] = {}; invalid: set[str] = set()
    for row in parsed["results"]:
        if not isinstance(row, dict): continue
        norm = normalize_question_ref(row.get("question_ref"))
        if norm not in expected or norm in invalid: continue
        if norm in rows:
            if rows[norm] != row: rows.pop(norm); invalid.add(norm)
            continue
        rows[norm] = row
    results, claimed_owner = [], {}
    for norm, question in expected.items():
        mcq = deterministic_mcq(question)
        if mcq is not None: result = mcq
        elif norm in rows:
            try: result = compile_question(question, rows[norm], payload.get("other_unmatched_evidence") or [])
            except Stage2PermanentError:
                # Match ExamApp's paid-response handling: a malformed result for
                # one question must not discard valid sibling results. Fail the
                # affected question closed and route the completed evaluation to
                # review. Cross-question duplicate evidence is still rejected
                # below because ownership cannot be resolved safely.
                result = _base_result(question, 0, "unsafe", not_attempted=False,
                                      not_evaluated=True, criteria=[], feedback="AI grading result requires review.")
        else:
            result = _base_result(question, 0, "unsafe", not_attempted=False,
                                  not_evaluated=True, criteria=[], feedback="AI grading result was missing.")
        for criterion in result.get("criteria_breakdown") or []:
            for eid in criterion.get("evidence_ids") or []:
                if eid in claimed_owner and claimed_owner[eid] != norm:
                    raise Stage2ContractError("The same unmatched evidence was claimed by multiple questions.")
                claimed_owner[eid] = norm
        results.append(result)
    if not any(not row["not_evaluated"] for row in results):
        raise Stage2PermanentError("The grader returned no usable question result.")
    return results, any(row["not_evaluated"] or row["handwriting_legibility"] == "difficult" for row in results)


def apply_choices(results: list[dict], question_structure: dict | None) -> list[dict]:
    """Apply fused-uppercase alternatives and printed pick groups deterministically."""
    output = deepcopy(results); by_norm = {normalize_question_ref(r["question_ref"]): r for r in output}
    alternatives: dict[str, dict[str, list[dict]]] = {}
    for result in output:
        match = re.match(r"^q(\d+)(?:!([a-z]))?", normalize_question_ref(result["question_ref"]))
        if match:
            alternatives.setdefault(match.group(1), {}).setdefault(match.group(2) or "", []).append(result)
    for branches in alternatives.values():
        if len(branches) < 2 or not any(marker for marker in branches):
            continue
        attempted = [(marker, rows) for marker, rows in branches.items()
                     if any(not row["not_attempted"] for row in rows)]
        if attempted:
            winner = min(attempted, key=lambda item: (
                -sum(float(row["marks_obtained"]) for row in item[1]),
                (" " if item[0] == "" else item[0]),
            ))[0]
            for marker, rows in branches.items():
                for row in rows:
                    row["not_counted"] = marker != winner
    structure = question_structure or {}
    for group in structure.get("optional_groups") or []:
        pick = int(group.get("pick") or 0)
        branches: list[list[dict]] = []
        for ref in group.get("questions") or []:
            norm = normalize_question_ref(ref)
            branch = [row for key, row in by_norm.items()
                      if key == norm or ref_is_descendant(key, norm)]
            if branch:
                branches.append(branch)
        attempted = [branch for branch in branches
                     if any(not row["not_attempted"] for row in branch)]
        slots = attempted[:pick]
        if len(slots) < pick:
            slots += [branch for branch in branches if branch not in attempted][:pick-len(slots)]
        for branch in branches:
            for row in branch:
                row["not_counted"] = branch not in slots
    return output
