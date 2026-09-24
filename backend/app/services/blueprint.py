"""
Blueprint-driven quiz generation (Slice 7).

The app (exam setter) turns the teacher's selected topics + High/Med/Low weights
into a concrete blueprint — how many questions per priority topic, plus a
"general" count for whole-document coverage. Gemini (question writer) then fills
that blueprint covering the whole document. Questions on a priority topic are
tagged with that topic's id; general questions are left untagged (topic_id NULL).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.blueprint_prompts import (
    GENERAL_TOPIC,
    build_blueprint_system_prompt,
    build_blueprint_user_prompt,
)
from app.services.commerce_context import commerce_context_for_prompt
from app.services.events import QUESTION_GENERATED, log_events, make_event
from app.services.extraction import extract_text_with_pages, require_readable_generation_pages
from app.services.llm.base import LLMError
from app.services.llm.structured import complete_json_with_fallback
from app.services.ai_call_logging import ai_call_context
from app.services.question_validation import (
    validate_question_answer_shape,
    validate_question_presentation,
)
from app.services.question_verification import verify_generated_questions
from app.services.question_repair import repair_candidates
from app.services.source_material import render_extracted_material
from app.services.teacher_access import teacher_has_subject

QuestionType = Literal[
    "mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"
]
Weight = Literal["high", "medium", "low"]

_WEIGHT_UNITS = {"high": 3, "medium": 2, "low": 1}
# Share of the quiz devoted to the selected priority topics; the remainder
# covers the rest of the document. Tunable without touching the flow.
_EMPHASIS_FRACTION = 0.7
logger = logging.getLogger(__name__)


class SelectedTopic(BaseModel):
    name: str
    weight: Weight = "medium"
    # New per-topic blueprint: the teacher sets exact per-format counts for this
    # topic (e.g. {"mcq_single": 2, "fill_blank": 1}). When present on any topic,
    # the weight math is bypassed entirely (see build_blueprint).
    counts: dict[str, int] | None = None


class BPQuestion(BaseModel):
    topic: str | None = None
    type: QuestionType
    question_text: str
    options: list[dict] | None = None
    correct_answer: Any
    explanation: str | None = None
    difficulty: str = "medium"
    marks: float = 1
    source_evidence_id: str | None = None
    source_excerpt: str = ""
    source_page_start: int | None = None
    source_page_end: int | None = None
    grounding_confidence: float = 0
    # Optional structured inputs for independent numeric verification (P6.3-A):
    # {"family": "simple_interest", "inputs": {...}}. Used at verification only;
    # not persisted. Populated only when the commerce pack asks for it.
    calc: dict | None = None

    def check_shape(self) -> None:
        validate_question_answer_shape(self.type, self.options, self.correct_answer)


class BPQuiz(BaseModel):
    questions: list[BPQuestion]


def _bind_verified_evidence(
    questions: list[BPQuestion], evidence_catalog: dict[str, dict]
) -> None:
    """Replace model-supplied evidence with canonical, pre-verified values."""
    for question in questions:
        evidence = evidence_catalog.get(question.source_evidence_id or "")
        if not evidence:
            raise LLMError("Model returned an invalid source evidence ID.")
        question.source_excerpt = str(evidence["text"])
        question.source_page_start = evidence.get("page_start")
        question.source_page_end = evidence.get("page_end")


def build_blueprint(
    selected: list[SelectedTopic], total: int, *, selected_only: bool = False
) -> dict:
    """
    Turn selected topics + weights into per-topic counts + a general count.

    Whole-document coverage: priority topics share ~EMPHASIS_FRACTION of the
    total (split 3:2:1 by weight, each >= 1); the remainder is general coverage.
    With no selected topics, the whole quiz is general coverage.
    """
    if not selected:
        total = max(total, 1)
        return {"topics": [], "general": total, "total": total}

    # Per-topic explicit blueprint: each selected topic carries its own per-format
    # counts (the teacher set them directly). The quiz is built ONLY from these
    # topics — no High/Med/Low weight math and no general coverage. The total is
    # simply the sum of every topic's counts.
    if any(t.counts is not None for t in selected):
        topics = []
        for t in selected:
            counts = {k: int(v) for k, v in (t.counts or {}).items() if v and v > 0}
            topics.append(
                {"name": t.name, "counts": counts, "num_questions": sum(counts.values())}
            )
        emphasis_total = sum(x["num_questions"] for x in topics)
        return {
            "topics": topics,
            "general": 0,
            "total": emphasis_total,
            "mode": "per_topic",
        }

    # Each selected topic must get at least one question. Never silently raise the
    # teacher's requested total: that would contradict the exact per-type mix.
    if len(selected) > total:
        raise ValueError(
            "The number of selected topics cannot exceed the requested question count."
        )
    emphasis_budget = (
        total
        if selected_only
        else min(total, max(len(selected), round(total * _EMPHASIS_FRACTION)))
    )

    units = [_WEIGHT_UNITS[t.weight] for t in selected]
    unit_sum = sum(units)
    counts = [max(1, round(emphasis_budget * u / unit_sum)) for u in units]

    # Trim rounding overflow so emphasis never exceeds the total (keep each >= 1).
    while sum(counts) > total:
        i = counts.index(max(counts))
        if counts[i] <= 1:
            break
        counts[i] -= 1

    emphasis_total = sum(counts)
    general = max(0, total - emphasis_total)
    topics = [
        {"name": t.name, "weight": t.weight, "num_questions": c}
        for t, c in zip(selected, counts)
    ]
    return {"topics": topics, "general": general, "total": emphasis_total + general}


def _validated_generated_quiz(
    data: object,
    expected_counts: dict[str, int],
    expected_topic_counts: dict[str, dict[str, int]] | None = None,
    requested_difficulty: str | None = None,
    allowed_evidence_ids: set[str] | None = None,
) -> BPQuiz:
    """Validate shape and the teacher's exact requested type distribution."""
    _check_source_capacity(data)
    try:
        quiz = BPQuiz.model_validate(data)
    except ValidationError as exc:
        raise LLMError("Model returned invalid quiz JSON.") from exc
    if not quiz.questions:
        raise LLMError("Model returned no questions.")
    for question in quiz.questions:
        try:
            if allowed_evidence_ids is not None and (
                not question.source_evidence_id
                or question.source_evidence_id not in allowed_evidence_ids
            ):
                raise ValueError(
                    "every question must use a valid source_evidence_id from the material"
                )
            question.check_shape()
            validate_question_presentation(
                question_type=question.type,
                question_text=question.question_text,
                explanation=question.explanation,
                source_excerpt=question.source_excerpt,
                requested_difficulty=requested_difficulty,
                declared_difficulty=question.difficulty,
            )
        except ValueError as exc:
            raise LLMError(f"Model produced an unsuitable question: {exc}") from exc

    actual = Counter(question.type for question in quiz.questions)
    expected = Counter(
        {kind: count for kind, count in expected_counts.items() if count > 0}
    )
    if actual != expected:
        expected_text = ", ".join(
            f"{kind}={count}" for kind, count in sorted(expected.items())
        )
        actual_text = (
            ", ".join(f"{kind}={count}" for kind, count in sorted(actual.items()))
            or "none"
        )
        raise LLMError(
            "AI question mix mismatch: "
            f"requested {sum(expected.values())} ({expected_text}); "
            f"received {sum(actual.values())} ({actual_text})."
        )

    if expected_topic_counts is not None:
        expected_by_topic = Counter(
            {
                (topic.strip().casefold(), kind): count
                for topic, counts in expected_topic_counts.items()
                for kind, count in counts.items()
                if count > 0
            }
        )
        actual_by_topic = Counter(
            ((question.topic or "").strip().casefold(), question.type)
            for question in quiz.questions
        )
        if actual_by_topic != expected_by_topic:
            raise LLMError(
                "AI per-topic question mix mismatch: generated questions did not "
                "match the exact topic and question-type allocation."
            )
    return quiz


def _check_source_capacity(data: object) -> None:
    if isinstance(data, dict) and data.get("source_insufficient") is True:
        raise ValueError("The selected source cannot support the requested number of distinct questions. Reduce the question count or include more source material.")


def _generate_with_exact_mix(
    system: str,
    user: str,
    expected_counts: dict[str, int],
    expected_topic_counts: dict[str, dict[str, int]] | None = None,
    requested_difficulty: str | None = None,
    tenant_id: str | None = None,
    document_id: str | None = None,
    allowed_evidence_ids: set[str] | None = None,
) -> tuple[BPQuiz, str]:
    """Generate once, then make one explicit correction attempt for a bad mix."""
    with ai_call_context(
        "blueprint_generation", tenant_id=tenant_id, document_id=document_id
    ):
        data, provider = complete_json_with_fallback(
            system,
            user,
            preferred_provider=getattr(
                get_settings(), "quiz_generation_provider", "deepseek"
            ),
        )
    try:
        return (
            _validated_generated_quiz(
                data,
                expected_counts,
                expected_topic_counts,
                requested_difficulty,
                allowed_evidence_ids,
            ),
            provider,
        )
    except LLMError as first_error:
        if not any(
            reason in str(first_error)
            for reason in ("question mix mismatch", "unsuitable question")
        ):
            raise

        expected_text = ", ".join(
            f"{kind}={count}"
            for kind, count in sorted(expected_counts.items())
            if count > 0
        )
        corrective_system = (
            system
            + "\n\nCORRECTION REQUIRED: Rebuild the complete JSON response. Return "
            f"exactly this type distribution: {expected_text}. No question stem may "
            "reveal its answer-bearing formula/rule, and no question or explanation "
            "may refer to a handbook, document, PDF, source material, notes, passage, "
            "page, or uploaded file. Every question must use one valid evidence ID "
            "copied exactly from the supplied material. Obey every original grounding "
            "and difficulty rule."
        )
        with ai_call_context(
            "blueprint_generation", tenant_id=tenant_id, document_id=document_id
        ):
            corrected, corrected_provider = complete_json_with_fallback(
                corrective_system,
                user,
                preferred_provider=getattr(
                    get_settings(), "quiz_generation_provider", "deepseek"
                ),
            )
        return (
            _validated_generated_quiz(
                corrected,
                expected_counts,
                expected_topic_counts,
                requested_difficulty,
                allowed_evidence_ids,
            ),
            corrected_provider,
        )


def _attach_source_figures(service, tenant_id: str, source_document_id, result) -> None:
    """Best-effort, flag-gated: link generated questions to their source-document
    figures AFTER persistence, using the returned rows' own ids.

    Fully decoupled from the commit path — it only issues follow-up UPDATEs and
    never raises, so figure linking can never affect quiz generation. Imported
    locally to keep this module's import graph (and pymupdf) out of the hot path.
    """
    if not source_document_id or not isinstance(result, dict):
        return
    try:
        from app.services.document_figures import attach_figures_to_questions

        attach_figures_to_questions(
            service,
            tenant_id=tenant_id,
            document_id=source_document_id,
            questions=result.get("questions") or [],
        )
    except Exception:  # noqa: BLE001 - figure linking is a non-critical enhancement
        logger.warning("Figure attachment step skipped")


def _get_or_create(service, table: str, tenant_id: str, match: dict, insert: dict) -> str:
    """Return the id of a row matching `match`, creating it from `insert` if none."""
    q = service.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in match.items():
        q = q.eq(k, v)
    rows = q.limit(1).execute().data or []
    if rows:
        return rows[0]["id"]
    created = service.table(table).insert({"tenant_id": tenant_id, **insert}).execute()
    return created.data[0]["id"]


def generate_blueprint_quiz(
    *,
    document_id: str,
    subject_id: str,
    chapter_name: str,
    selected_topics: list[dict],
    total_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    profile: CurrentProfile,
    type_counts: dict[str, int] | None = None,
    persist_result: Callable[[dict], dict] | None = None,
) -> dict:
    service = get_service_client()
    tid = profile.tenant_id
    chapter_name = chapter_name.strip()

    # 0) Explicit assignments are authoritative. Course enrolment is maintained
    # as derived compatibility data and must never grant additional access.
    if not teacher_has_subject(service, profile, subject_id):
        raise ValueError("Subject not found.")

    # 1) Fetch the document + extract text.
    doc = (
        service.table("documents").select("storage_path,file_type")
        .eq("id", document_id)
        .eq("tenant_id", tid)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    extracted = extract_text_with_pages(
        download_bytes(doc.data["storage_path"]), doc.data["file_type"]
    )
    if not extracted.text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    require_readable_generation_pages(extracted)
    if len(extracted.text) > get_settings().generation_max_text_chars:
        raise ValueError("This document exceeds the direct generation limit. Complete the large-document analysis first so all source content is considered.")
    material = render_extracted_material(
        extracted, max_chars=get_settings().generation_max_text_chars
    )

    # 2) Generate + persist from the document's own text. (For LARGE documents the
    #    caller uses generate_and_persist_from_material directly with a Master
    #    Blueprint as the material instead — same writer + persistence.)
    return generate_and_persist_from_material(
        service=service,
        tenant_id=tid,
        material=material,
        subject_id=subject_id,
        chapter_name=chapter_name,
        selected_topics=selected_topics,
        total_questions=total_questions,
        question_types=question_types,
        cognitive_level=cognitive_level,
        difficulty=difficulty,
        profile=profile,
        type_counts=type_counts,
        source_document_id=document_id,
        commerce_context=commerce_context_for_prompt(service, tid, subject_id),
        persist_result=persist_result,
    )


def generate_and_persist_from_material(
    *,
    service,
    tenant_id: str,
    material: str,
    subject_id: str,
    chapter_name: str,
    selected_topics: list[dict],
    total_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    profile: CurrentProfile,
    type_counts: dict[str, int] | None = None,
    selected_only_material: bool = False,
    source_document_id: str | None = None,
    evidence_catalog: dict[str, dict] | None = None,
    commerce_context: str | None = None,
    persist_result: Callable[[dict], dict] | None = None,
) -> dict:
    """Write + persist a blueprint-driven quiz from a block of `material`.

    `material` is either a small document's raw text (single-pass path) or a
    consolidated Master Blueprint rendered to text (large-document path). For
    the latter, `selected_only_material=True` tells allocation and prompting
    that no whole-document/general coverage is available or desired.
    """
    tid = tenant_id
    chapter_name = chapter_name.strip()

    # Build the blueprint (exam setter).
    selected = [SelectedTopic(**t) for t in selected_topics]
    # A per-topic blueprint (each topic carries its own counts) is inherently
    # selected-topics-only: there is no general/whole-document coverage.
    per_topic = any(t.counts is not None for t in selected)
    selected_only = selected_only_material or per_topic
    blueprint = build_blueprint(selected, total_questions, selected_only=selected_only)

    # Generate with the configured stage provider and controlled fallback. This
    # function stays a pure payload builder — it performs no DB reads/writes before
    # the atomic commit — so the commerce context (AY / jurisdiction / framework) is
    # resolved by the caller and passed in; it is None when the pack is off.
    system = build_blueprint_system_prompt(
        question_types,
        cognitive_level,
        difficulty,
        selected_only_material=selected_only,
        evidence_ids_required=bool(evidence_catalog),
        commerce_calc_enabled=bool(commerce_context),
        commerce_context=commerce_context,
    )
    user = build_blueprint_user_prompt(
        material,
        blueprint,
        question_types,
        cognitive_level,
        difficulty,
        type_counts,
        selected_only_material=selected_only,
    )
    expected_counts = (
        {kind: count for kind, count in type_counts.items() if count > 0}
        if type_counts
        else {kind: 0 for kind in question_types}
    )
    if not type_counts:
        # The legacy caller specifies only a total and allowed types. Preserve that
        # path by validating total count, while exact per-type enforcement is used
        # by the teacher blueprint UI.
        with ai_call_context(
            "blueprint_generation", tenant_id=tid, document_id=source_document_id
        ):
            data, provider = complete_json_with_fallback(
                system,
                user,
                preferred_provider=getattr(
                    get_settings(), "quiz_generation_provider", "deepseek"
                ),
            )
        _check_source_capacity(data)
        try:
            quiz = BPQuiz.model_validate(data)
        except ValidationError as exc:
            raise LLMError("Model returned invalid quiz JSON.") from exc
        questions = quiz.questions
        if len(questions) != total_questions:
            raise LLMError(
                f"AI generated {len(questions)} questions instead of the requested "
                f"{total_questions}."
            )
        allowed_evidence_ids = set(evidence_catalog or {}) or None
        for q in questions:
            try:
                if allowed_evidence_ids is not None and (
                    not q.source_evidence_id
                    or q.source_evidence_id not in allowed_evidence_ids
                ):
                    raise ValueError(
                        "every question must use a valid source_evidence_id from the material"
                    )
                q.check_shape()
                validate_question_presentation(
                    question_type=q.type,
                    question_text=q.question_text,
                    explanation=q.explanation,
                    source_excerpt=q.source_excerpt,
                    requested_difficulty=difficulty,
                    declared_difficulty=q.difficulty,
                )
            except ValueError as exc:
                corrective_system = (
                    system
                    + "\n\nCORRECTION REQUIRED: Rewrite the complete quiz. No question "
                    "stem may reveal its answer-bearing formula/rule, and no question "
                    "or explanation may refer to a handbook, document, PDF, source "
                    "material, notes, passage, page, or uploaded file. Preserve the "
                    "requested difficulty and all JSON/type rules. Every question must "
                    "use one valid evidence ID copied exactly from the supplied material."
                )
                with ai_call_context(
                    "blueprint_generation", tenant_id=tid, document_id=source_document_id
                ):
                    corrected, corrected_provider = complete_json_with_fallback(
                        corrective_system,
                        user,
                        preferred_provider=getattr(
                            get_settings(), "quiz_generation_provider", "deepseek"
                        ),
                    )
                try:
                    corrected_quiz = BPQuiz.model_validate(corrected)
                    if len(corrected_quiz.questions) != total_questions:
                        raise LLMError(
                            "AI generated the wrong number of questions after correction."
                        )
                    for corrected_question in corrected_quiz.questions:
                        if allowed_evidence_ids is not None and (
                            not corrected_question.source_evidence_id
                            or corrected_question.source_evidence_id
                            not in allowed_evidence_ids
                        ):
                            raise ValueError(
                                "every question must use a valid source_evidence_id "
                                "from the material"
                            )
                        corrected_question.check_shape()
                        validate_question_presentation(
                            question_type=corrected_question.type,
                            question_text=corrected_question.question_text,
                            explanation=corrected_question.explanation,
                            source_excerpt=corrected_question.source_excerpt,
                            requested_difficulty=difficulty,
                            declared_difficulty=corrected_question.difficulty,
                        )
                except (ValidationError, ValueError) as corrected_error:
                    raise LLMError(
                        f"Model produced an unsuitable question: {corrected_error}"
                    ) from corrected_error
                questions = corrected_quiz.questions
                provider = corrected_provider
                break
    else:
        expected_topic_counts = (
            {topic["name"]: topic["counts"] for topic in blueprint["topics"]}
            if per_topic
            else None
        )
        quiz, provider = _generate_with_exact_mix(
            system,
            user,
            expected_counts,
            expected_topic_counts,
            difficulty,
            tenant_id=tid,
            document_id=source_document_id,
            allowed_evidence_ids=set(evidence_catalog or {}) or None,
        )
        questions = quiz.questions

    # For large-document generation, never trust model-copied evidence text or
    # pages. Resolve the selected ID to the already verified canonical excerpt.
    if evidence_catalog:
        _bind_verified_evidence(questions, evidence_catalog)

    with ai_call_context(
        "question_verification", tenant_id=tid, document_id=source_document_id
    ):
        verification = verify_generated_questions(questions, material)

    def repair_complete(repair_system: str, repair_user: str):
        with ai_call_context(
            "question_repair", tenant_id=tid, document_id=source_document_id
        ):
            return complete_json_with_fallback(
                repair_system,
                repair_user,
                preferred_provider=getattr(
                    get_settings(), "quiz_generation_provider", "deepseek"
                ),
            )

    def repair_verify(repaired_questions, repaired_material):
        with ai_call_context(
            "question_verification", tenant_id=tid, document_id=source_document_id
        ):
            return verify_generated_questions(repaired_questions, repaired_material)

    questions, verification, quality = repair_candidates(
        questions,
        verification,
        material,
        difficulty,
        complete=repair_complete,
        verify=repair_verify,
        allowed_evidence_ids=set(evidence_catalog or {}) or None,
    )
    if evidence_catalog:
        _bind_verified_evidence(questions, evidence_catalog)
    blueprint["quality"] = quality

    if persist_result is not None:
        # The durable worker commits all result rows and job completion in one
        # fenced database transaction. No partial quiz/chapter writes precede it.
        result = persist_result({
            "title": f"{chapter_name} — {cognitive_level}",
            "chapter_name": chapter_name,
            "variant_type": cognitive_level,
            "selected_topics": [topic.name.strip() for topic in selected],
            "provider": provider,
            "blueprint": blueprint,
            "source": "ai_generated",
            "questions": [
                {**question.model_dump(), "verification_status": check.status,
                 "verification_warnings": check.warnings}
                for question, check in zip(questions, verification, strict=True)
            ],
        })
        _attach_source_figures(service, tid, source_document_id, result)
        return result

    # 4) Persist chapter + selected topics (exam-setter data; powers analytics).
    chapter_id = _get_or_create(
        service, "chapters", tid,
        {"subject_id": subject_id, "name": chapter_name},
        {"subject_id": subject_id, "name": chapter_name},
    )
    topic_id_by_name: dict[str, str] = {}
    for t in selected:
        name = t.name.strip()
        topic_id_by_name[name.casefold()] = _get_or_create(
            service, "topics", tid,
            {"chapter_id": chapter_id, "name": name},
            {"chapter_id": chapter_id, "name": name},
        )

    # 5) quiz_set -> variant -> questions (all pending review).
    quiz_set_values = {
        "tenant_id": tid, "chapter_id": chapter_id, "subject_id": subject_id,
        "title": f"{chapter_name} — {cognitive_level}",
        "status": "draft", "created_by": profile.user_id,
    }
    if source_document_id:
        quiz_set_values["document_id"] = source_document_id
    quiz_set = service.table("quiz_sets").insert(quiz_set_values).execute()
    quiz_set_id = quiz_set.data[0]["id"]

    stored: list[dict] = []
    created_question_ids: list[str] = []
    try:
        total_marks = sum(q.marks for q in questions)
        variant = service.table("quiz_variants").insert({
            "tenant_id": tid, "quiz_set_id": quiz_set_id,
            "variant_type": cognitive_level, "total_marks": total_marks,
        }).execute()
        variant_id = variant.data[0]["id"]

        for index, q in enumerate(questions):
            verified = verification[index]
            tag = (q.topic or "").strip().casefold()
            topic_id = (
                None
                if tag in ("", GENERAL_TOPIC.casefold())
                else topic_id_by_name.get(tag)
            )
            qrow = service.table("questions").insert({
                "tenant_id": tid, "chapter_id": chapter_id, "topic_id": topic_id,
                "type": q.type, "question_text": q.question_text, "options": q.options,
                "correct_answer": q.correct_answer, "explanation": q.explanation,
                "difficulty": q.difficulty, "marks": q.marks,
                "source_excerpt": q.source_excerpt,
                "source_page_start": q.source_page_start,
                "source_page_end": q.source_page_end,
                "grounding_confidence": q.grounding_confidence,
                "verification_status": verified.status,
                "verification_warnings": verified.warnings,
                "source": "ai_generated", "review_status": "pending_review",
                "created_by": profile.user_id,
            }).execute()
            question_id = qrow.data[0]["id"]
            created_question_ids.append(question_id)
            service.table("quiz_variant_questions").insert({
                "tenant_id": tid, "variant_id": variant_id,
                "question_id": question_id, "order_index": index,
            }).execute()
            stored.append({
                "id": question_id,
                **q.model_dump(),
                "verification_status": verified.status,
                "verification_warnings": verified.warnings,
            })
    except Exception:
        service.table("quiz_sets").delete().eq("id", quiz_set_id).eq(
            "tenant_id", tid
        ).eq("created_by", profile.user_id).execute()
        if created_question_ids:
            service.table("questions").delete().in_("id", created_question_ids).eq(
                "tenant_id", tid
            ).eq("created_by", profile.user_id).execute()
        raise

    if source_document_id:
        try:
            service.table("documents").update({"chapter_id": chapter_id}).eq(
                "id", source_document_id
            ).eq("tenant_id", tid).eq("uploaded_by", profile.user_id).execute()
        except Exception as exc:  # noqa: BLE001 - quiz generation already succeeded
            logger.warning(
                "Could not file source document under generated chapter (%s)",
                type(exc).__name__,
            )

    # Instrument: one 'question.generated' event per question (best-effort).
    log_events(
        [
            make_event(
                tenant_id=tid,
                event_type=QUESTION_GENERATED,
                actor_id=profile.user_id,
                actor_role=profile.role,
                subject_type="question",
                subject_id=s["id"],
                metadata={
                    "type": s.get("type"),
                    "difficulty": s.get("difficulty"),
                    "cognitive_level": cognitive_level,
                    "subject_id": subject_id,
                    "provider": provider,
                },
            )
            for s in stored
        ]
    )

    result = {
        "quiz_set_id": quiz_set_id,
        "variant_id": variant_id,
        "provider": provider,
        "blueprint": blueprint,
        "questions": stored,
    }
    _attach_source_figures(service, tid, source_document_id, result)
    return result
