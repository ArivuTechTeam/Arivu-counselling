"""Generate validated exam-paper snapshots from the tenant paper bank."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.lib.config import get_settings
from app.lib.supabase_queries import select_all
from app.services.ai_call_logging import ai_call_context, ai_provider_attempt
from app.services.commerce_context import format_commerce_context, resolve_paper_profile
from app.services.llm import LLMError, get_providers
from app.services.llm.json_repair import parse_repaired_json
from app.services.paper_selection import bias_order, pick_exact_marks


_SECTION_HEADER_RE = re.compile(r"^(Section\s+)([A-Za-z]+)(\s*:\s*)(.*)$", re.IGNORECASE)
_SECTION_COUNT_RE = re.compile(r"\bcomprises?\b.{0,20}\bsections?\b", re.IGNORECASE)
_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+[.)]\s*")
_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


class AISection(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    question_ids: list[str] = Field(min_length=1)


class AIPaperPlan(BaseModel):
    instructions: list[str] = Field(default_factory=list, max_length=20)
    sections: list[AISection] = Field(min_length=1, max_length=26)
    total_marks: float = Field(gt=0)


def sum_paper_marks(questions: list[dict] | None) -> float:
    """Sum rendered marks, preferring a positive part breakdown when present."""
    total = 0.0
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        parts = [part for part in question.get("parts") or [] if isinstance(part, dict)]
        parts_total = 0.0
        for part in parts:
            try:
                parts_total += float(part.get("marks") or 0)
            except (TypeError, ValueError):
                pass
        try:
            total += parts_total if parts and parts_total > 0 else float(question.get("marks") or 0)
        except (TypeError, ValueError):
            pass
    return total


def reletter_sections(questions: list | None) -> list[str]:
    """Repair flat section-header entries to consecutive A, B, C… labels."""
    letters: list[str] = []
    for question in questions or []:
        if not isinstance(question, dict) or question.get("type") != "section_header":
            continue
        letter = chr(ord("A") + len(letters))
        letters.append(letter)
        question["number"] = letter
        text = question.get("question")
        if isinstance(text, str):
            match = _SECTION_HEADER_RE.match(text)
            if match:
                question["question"] = f"{match.group(1)}{letter}{match.group(3)}{match.group(4)}"
    return letters


def fix_instructions_text(instructions: list | None, section_letters: list[str]) -> list[str]:
    """Remove duplicate numbering and make any section-count claim truthful."""
    cleaned: list[str] = []
    for instruction in instructions or []:
        if not isinstance(instruction, str) or not instruction.strip():
            continue
        line = _NUMBER_PREFIX_RE.sub("", instruction.strip())
        if section_letters and _SECTION_COUNT_RE.search(line):
            count = len(section_letters)
            word = _NUMBER_WORDS.get(count, str(count))
            if count == 1:
                letters = section_letters[0]
            elif count == 2:
                letters = f"{section_letters[0]} and {section_letters[1]}"
            else:
                letters = ", ".join(section_letters[:-1]) + f" and {section_letters[-1]}"
            line = (
                f"The question paper comprises {word} section{'s' if count != 1 else ''} "
                f"- {letters}. All questions are compulsory."
            )
        cleaned.append(line)
    return cleaned


def _complete_plan(system: str, user: str, *, preferred_provider: str) -> tuple[AIPaperPlan, str]:
    failures: list[str] = []
    for index, provider in enumerate(get_providers(preferred_provider)):
        try:
            with ai_provider_attempt(was_fallback=index > 0):
                raw = provider.complete(system, user)
            parsed = parse_repaired_json(raw, expect="dict")
            if not isinstance(parsed, dict):
                raise LLMError("returned no usable JSON object")
            return AIPaperPlan.model_validate(parsed), provider.name
        except (LLMError, ValidationError) as exc:
            failures.append(f"{provider.name}: {exc}")
    raise LLMError("All LLM providers failed → " + " | ".join(failures))


def _question_count(format_config: dict, request: dict) -> int:
    configured = sum(
        int(section.get("count") or 0)
        for section in format_config.get("sections") or []
        if isinstance(section, dict)
    )
    return configured or int(request.get("question_count") or 0)


def _query_candidates(service, tenant_id: str, request: dict) -> list[dict]:
    def configure(query):
        query = query.eq("tenant_id", tenant_id).eq("subject_id", request["subject_id"])
        chapter_ids = request.get("chapter_ids") or []
        question_types = request.get("question_types") or []
        if chapter_ids:
            query = query.in_("chapter_id", chapter_ids)
        if question_types:
            query = query.in_("type", question_types)
        return query

    return select_all(
        service,
        "paper_questions",
        "id,paper_type,subject_id,chapter_id,exam,year,type,question_text,options,"
        "correct_answer,explanation,marks,model_answer,answer_summary",
        configure=configure,
    )


def _prompt(profile: dict, format_config: dict, candidates: list[dict], mode: str) -> tuple[str, str]:
    context = format_commerce_context(profile) or "No exam-body context configured"
    system = (
        "Arrange an exam paper using only the supplied question IDs. Return one JSON object with "
        "instructions, sections [{name, question_ids}], and total_marks. Never rewrite questions, "
        "invent IDs, duplicate IDs, or change marks. Follow the supplied tenant format; do not assume "
        "any exam body, institution, currency, or locale that is not supplied."
    )
    user = json.dumps(
        {
            "mode": mode,
            "paper_context": context,
            "format_config": format_config,
            "candidates": [
                {"id": row["id"], "type": row["type"], "marks": row["marks"], "text": row["question_text"]}
                for row in candidates
            ],
        },
        ensure_ascii=False,
        default=str,
    )
    return system, user


def _configured_sections(selected: list[dict], format_config: dict) -> list[AISection]:
    remaining = list(selected)
    sections: list[AISection] = []
    for configured in format_config.get("sections") or []:
        if not isinstance(configured, dict):
            continue
        kind = configured.get("question_type")
        count = int(configured.get("count") or 0)
        matches = [row for row in remaining if not kind or row.get("type") == kind]
        chosen = matches[:count] if count else matches
        if chosen:
            chosen_ids = [str(row["id"]) for row in chosen]
            chosen_set = set(chosen_ids)
            remaining = [row for row in remaining if str(row["id"]) not in chosen_set]
            sections.append(AISection(name=str(configured.get("name") or "Section"), question_ids=chosen_ids))
    if remaining:
        sections.append(AISection(name="Questions", question_ids=[str(row["id"]) for row in remaining]))
    return sections


def _matches_format(plan: AIPaperPlan, by_id: dict[str, dict], format_config: dict) -> bool:
    configured = [section for section in format_config.get("sections") or [] if isinstance(section, dict)]
    if not configured:
        return True
    if len(plan.sections) != len(configured):
        return False
    for planned, section in zip(plan.sections, configured, strict=True):
        if len(planned.question_ids) != int(section.get("count") or 0):
            return False
        for question_id in planned.question_ids:
            row = by_id.get(question_id)
            if row is None:
                return False
            marks = float(row.get("marks") or 0)
            if section.get("question_type") and row.get("type") != section["question_type"]:
                return False
            if section.get("min_marks") is not None and marks < float(section["min_marks"]):
                return False
            if section.get("max_marks") is not None and marks > float(section["max_marks"]):
                return False
    return True


def _validate_selection(
    plan: AIPaperPlan,
    candidates: list[dict],
    requested_total: float,
    format_config: dict,
) -> list[dict] | None:
    by_id = {str(row["id"]): row for row in candidates}
    ids = [question_id for section in plan.sections for question_id in section.question_ids]
    if not ids or len(ids) != len(set(ids)) or any(question_id not in by_id for question_id in ids):
        return None
    selected = [by_id[question_id] for question_id in ids]
    actual = sum_paper_marks(selected)
    if abs(actual - requested_total) > 1e-6 or abs(plan.total_marks - actual) > 1e-6:
        return None
    if not _matches_format(plan, by_id, format_config):
        return None
    return selected


def _number(index: int, style: str) -> str:
    if style == "q_numeric":
        return f"Q{index}"
    if style == "roman":
        values = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
        value, output = index, ""
        for amount, numeral in values:
            while value >= amount:
                output += numeral
                value -= amount
        return output
    return str(index)


def _payload(plan: AIPaperPlan, candidates: list[dict], profile: dict, format_config: dict) -> dict:
    by_id = {str(row["id"]): row for row in candidates}
    counter = 0
    sections: list[dict] = []
    for section_index, section in enumerate(plan.sections):
        letter = chr(ord("A") + section_index)
        title = _SECTION_HEADER_RE.sub(rf"\1{letter}\3\4", section.name)
        if not title.lower().startswith("section "):
            title = f"Section {letter}: {title}"
        rendered: list[dict] = []
        for question_id in section.question_ids:
            counter += 1
            rendered.append({**by_id[question_id], "number": _number(counter, format_config.get("numbering_style", "numeric"))})
        sections.append({"name": title, "questions": rendered})
    letters = [chr(ord("A") + index) for index in range(len(sections))]
    instructions = fix_instructions_text(
        plan.instructions or format_config.get("instructions") or [], letters
    )
    questions = [question for section in sections for question in section["questions"]]
    return {
        "exam_body": profile.get("exam_body"),
        "level": profile.get("level"),
        "paper": profile.get("paper"),
        "assessment_year": profile.get("assessment_year"),
        "framework": profile.get("framework"),
        "duration_minutes": format_config.get("duration_minutes"),
        "numbering_style": format_config.get("numbering_style", "numeric"),
        "currency_symbol": format_config.get("currency_symbol"),
        "locale": format_config.get("locale"),
        "instructions": instructions,
        "sections": sections,
        "total_marks": sum_paper_marks(questions),
    }


def generate_paper(service, job: dict) -> dict:
    """Process one leased ``generate_paper`` faculty job."""
    request = job["request"]
    tenant_id = job["tenant_id"]
    paper_id = request["generated_paper_id"]
    service.table("generated_papers").update({"status": "processing", "error_message": None}) \
        .eq("id", paper_id).eq("tenant_id", tenant_id).execute()

    profile = resolve_paper_profile(service, tenant_id, request["subject_id"])
    if not profile or str(profile.get("course_level_id")) != str(request["course_level_id"]):
        raise ValueError("A paper profile is required for this course level.")
    format_config = profile.get("format_config") or {}
    count = _question_count(format_config, request)
    if count < 1:
        raise ValueError("Configure section counts or request a question count.")
    candidates = _query_candidates(service, tenant_id, request)
    configured_sections = [
        section for section in format_config.get("sections") or [] if isinstance(section, dict)
    ]
    if configured_sections:
        def eligible(row: dict) -> bool:
            marks = float(row.get("marks") or 0)
            return any(
                (not section.get("question_type") or section.get("question_type") == row.get("type"))
                and (section.get("min_marks") is None or marks >= float(section["min_marks"]))
                and (section.get("max_marks") is None or marks <= float(section["max_marks"]))
                for section in configured_sections
            )
        candidates = [row for row in candidates if eligible(row)]
    if not candidates:
        raise ValueError("No paper-bank questions match these filters.")

    total = float(request["requested_total_marks"])
    mode: Literal["exact_mark", "candidate_ai"] = request["mode"]
    if mode == "exact_mark":
        ordered = sorted(candidates, key=lambda row: str(row["id"]))
        selected = pick_exact_marks(ordered, total, count)
        if not selected:
            raise ValueError("No exact-mark combination exists for these filters.")
        prompt_candidates = selected
    else:
        prompt_candidates = bias_order(candidates, lambda row: row.get("type"))[:50]
        selected = []

    system, user = _prompt(profile, format_config, prompt_candidates, mode)
    last_error: Exception | None = None
    plan: AIPaperPlan | None = None
    provider = ""
    for attempt in range(2):
        try:
            corrective = "\nYour prior response failed local validation. Return corrected JSON only." if attempt else ""
            with ai_call_context(
                "paper_generation", tenant_id=tenant_id, job_id=job["id"]
            ):
                plan, provider = _complete_plan(
                    system + corrective,
                    user,
                    preferred_provider=getattr(get_settings(), "quiz_generation_provider", "deepseek"),
                )
            validated = _validate_selection(plan, prompt_candidates, total, format_config)
            if mode == "exact_mark" and validated and {str(row["id"]) for row in validated} == {str(row["id"]) for row in selected}:
                selected = validated
                break
            if mode == "candidate_ai" and validated:
                selected = validated
                break
            raise ValueError("The AI selection did not have the requested verified total.")
        except (LLMError, ValidationError, ValueError) as exc:
            last_error = exc
            plan = None
    if plan is None or not selected:
        if mode == "candidate_ai":
            corrected = pick_exact_marks(prompt_candidates, total, count)
            if corrected:
                selected = corrected
                plan = AIPaperPlan(
                    instructions=format_config.get("instructions") or [],
                    sections=_configured_sections(selected, format_config),
                    total_marks=total,
                )
                if _validate_selection(plan, prompt_candidates, total, format_config):
                    provider = "local_exact_correction"
                else:
                    selected = []
        if plan is None or not selected:
            raise LLMError("Paper formatting failed local validation.") from last_error

    payload = _payload(plan, selected, profile, format_config)
    if abs(float(payload["total_marks"]) - total) > 1e-6:
        raise ValueError("The generated paper did not match the requested mark total.")
    selected_ids = [str(question["id"]) for section in payload["sections"] for question in section["questions"]]
    from datetime import datetime, timezone
    service.table("generated_papers").update({
        "selected_question_ids": selected_ids,
        "paper_payload": payload,
        "instructions_text": "\n".join(payload["instructions"]),
        "status": "ready",
        "error_message": None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", paper_id).eq("tenant_id", tenant_id).execute()
    return {"generated_paper_id": paper_id, "total": len(selected_ids), "provider": provider}
