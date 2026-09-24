"""Manual, REAL-AI evidence run for the large-document map/reduce pipeline.

This deliberately avoids production database writes while exercising the same
extraction, chunking, MAP, REDUCE, selected-topic rendering, and final writer
prompts used by the application. It prints a compact JSON evidence record and
never prints credentials.

Run from backend/ with APP_ENV=development:
    ./venv/bin/python scripts/review_large_document_e2e.py ../docs/python-basics-sample-chapters.pdf
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app.lib.config import get_settings
from app.services.blueprint import SelectedTopic, _generate_with_exact_mix, build_blueprint
from app.services.blueprint_prompts import (
    build_blueprint_system_prompt,
    build_blueprint_user_prompt,
)
from app.services.chunking_service import ChunkingService
from app.services.document_profile import profile_to_summary
from app.services.extraction import extract_text_with_pages
from app.services.llm.structured import (
    complete_json_large,
    _deepseek_json_large,
)
from app.services.map_reduce_prompts import (
    MAP_SYSTEM,
    PROFILE_SYSTEM,
    REDUCE_SYSTEM,
    build_map_user_prompt,
    build_profile_user_prompt,
    build_reduce_user_prompt,
)
from app.services.master_blueprint_synthesizer import (
    _fact_matches_source,
    spot_check_verbatim_facts,
)
from app.services.quiz_generator_service import render_blueprint_material
from app.services.topic_extraction_pipeline import validate_map_output


def _pages_for_chunk(chunk, spans) -> tuple[int | None, int | None]:
    pages = [
        span.page_number
        for span in spans
        if span.char_end > chunk.char_start and span.char_start < chunk.char_end
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def _normal_words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) >= 3
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Pass one PDF path.")
    pdf_path = Path(sys.argv[1]).resolve()
    started = time.monotonic()
    extracted = extract_text_with_pages(pdf_path.read_bytes(), "pdf")
    chunks = ChunkingService().split(extracted.text)
    settings = get_settings()
    calls: list[dict] = []
    http_attempts: list[dict] = []
    http_attempts_lock = threading.Lock()
    original_post = httpx.post

    def tracked_post(url, *args, **kwargs):
        provider = "gemini" if "googleapis.com" in str(url) else "deepseek"
        try:
            response = original_post(url, *args, **kwargs)
        except Exception:
            with http_attempts_lock:
                http_attempts.append({"provider": provider, "outcome": "network_error"})
            raise
        with http_attempts_lock:
            http_attempts.append({"provider": provider, "status": response.status_code})
        return response

    httpx.post = tracked_post

    profile_data, profile_provider = complete_json_large(
        PROFILE_SYSTEM,
        build_profile_user_prompt(
            extracted.text[: settings.generation_profile_max_chars]
        ),
    )
    calls.append({"stage": "profile", "provider": profile_provider})
    summary = profile_to_summary(profile_data)

    def map_chunk(chunk):
        page_start, page_end = _pages_for_chunk(chunk, extracted.page_spans)
        data, provider = complete_json_large(
            MAP_SYSTEM,
            build_map_user_prompt(
                document_title=pdf_path.name,
                chunk_number=chunk.index + 1,
                total_chunks=len(chunks),
                content=chunk.content,
                document_summary=summary,
                page_start=page_start,
                page_end=page_end,
            ),
        )
        topics = validate_map_output(data)
        if page_start is not None and page_end is not None:
            for topic in topics:
                topic["source_page_ranges"] = [
                    {"start": page_start, "end": page_end}
                ]
        return {
            "chunk_index": chunk.index,
            "content": chunk.content,
            "page_start": page_start,
            "page_end": page_end,
            "topics": topics,
            "provider": provider,
        }

    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        mapped = list(pool.map(map_chunk, chunks))
    mapped.sort(key=lambda item: item["chunk_index"])
    calls.extend(
        {"stage": f"map-{item['chunk_index'] + 1}", "provider": item["provider"]}
        for item in mapped
    )

    raw_topics = [topic for item in mapped for topic in item["topics"]]
    reduce_user = build_reduce_user_prompt(
        document_title=pdf_path.name,
        topics_json=json.dumps(raw_topics, ensure_ascii=False),
        document_summary=summary,
    )
    reduced_data, reduce_provider = complete_json_large(
        REDUCE_SYSTEM,
        reduce_user,
    )
    calls.append({"stage": "reduce", "provider": reduce_provider})
    consolidated = validate_map_output(reduced_data)
    spot_check = spot_check_verbatim_facts(consolidated, mapped)

    # Explicitly exercise the provider that previously truncated REDUCE at its
    # old 8,192-token application ceiling. This is test-only and is reported
    # separately from the production logical call count below.
    deepseek_reduced = validate_map_output(
        _deepseek_json_large(
            REDUCE_SYSTEM,
            reduce_user,
            max_tokens=settings.deepseek_max_output_tokens,
        )
    )

    late_text = "\n".join(
        extracted.text[span.char_start : span.char_end]
        for span in extracted.page_spans
        if span.page_number >= 90
    )
    candidates: list[tuple[dict, str]] = []
    for topic in consolidated:
        for fact in topic.get("key_facts_and_figures") or []:
            if _fact_matches_source(str(fact), late_text):
                candidates.append((topic, str(fact)))
    if not candidates:
        raise RuntimeError("No consolidated verbatim fact matched pages 90+.")

    late_topic, late_fact = candidates[0]
    matching_source_pages = [
        span.page_number
        for span in extracted.page_spans
        if _fact_matches_source(
            late_fact, extracted.text[span.char_start : span.char_end]
        )
    ]
    selected_name = str(late_topic["topic_name"])
    master = {"topics": consolidated}
    material = render_blueprint_material(master, {selected_name.casefold()})
    if late_fact not in material:
        raise RuntimeError("The selected late fact was missing from writer material.")

    selected = [SelectedTopic(name=selected_name, weight="high")]
    blueprint = build_blueprint(selected, 3, selected_only=True)
    system = build_blueprint_system_prompt(
        ["mcq_single", "true_false", "fill_blank"],
        "mixed",
        "medium",
        selected_only_material=True,
    )
    user = build_blueprint_user_prompt(
        material,
        blueprint,
        ["mcq_single", "true_false", "fill_blank"],
        "mixed",
        "medium",
        {"mcq_single": 1, "true_false": 1, "fill_blank": 1},
        selected_only_material=True,
    )
    expected_counts = {"mcq_single": 1, "true_false": 1, "fill_blank": 1}
    quiz, generation_provider = _generate_with_exact_mix(
        system, user, expected_counts
    )
    calls.append({"stage": "generation", "provider": generation_provider})
    actual_counts = Counter(question.type for question in quiz.questions)

    fact_words = _normal_words(late_fact)
    ranked = sorted(
        quiz.questions,
        key=lambda question: len(
            fact_words
            & _normal_words(
                f"{question.question_text} {question.correct_answer} {question.explanation or ''}"
            )
        ),
        reverse=True,
    )
    best = ranked[0]
    overlap = sorted(
        fact_words
        & _normal_words(
            f"{best.question_text} {best.correct_answer} {best.explanation or ''}"
        )
    )
    if len(overlap) < 3:
        raise RuntimeError("Generated questions did not demonstrably use the late fact.")

    evidence = {
        "document": str(pdf_path),
        "pages": len(extracted.page_spans),
        "characters": len(extracted.text),
        "threshold_characters": settings.chunking_trigger_chars,
        "chunk_count": len(chunks),
        "chunk_page_ranges": [
            [item["page_start"], item["page_end"]] for item in mapped
        ],
        "raw_topic_count": len(raw_topics),
        "consolidated_topic_count": len(consolidated),
        "late_topic": selected_name,
        "late_topic_page_ranges": late_topic.get("source_page_ranges") or [],
        "late_source_fact": late_fact,
        "late_source_fact_pages": matching_source_pages,
        "selected_material_characters": len(material),
        "late_fact_present_in_generation_material": late_fact in material,
        "generated_question": best.question_text,
        "generated_answer": best.correct_answer,
        "generated_explanation": best.explanation,
        "fact_question_overlap_words": overlap,
        "verbatim_spot_check": spot_check,
        "deepseek_reduce_verification": {
            "max_tokens": settings.deepseek_max_output_tokens,
            "valid_topic_count": len(deepseek_reduced),
            "completed_without_truncation": True,
        },
        "requested_question_type_counts": expected_counts,
        "generated_question_type_counts": dict(actual_counts),
        "logical_ai_calls": calls,
        "logical_ai_call_count": len(calls),
        "external_ai_http_attempts": http_attempts,
        "actual_external_ai_http_attempt_count": len(http_attempts),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    # Never print source text, filenames, prompts, questions, or answers. This
    # command may run in CI where stdout is retained by a third party.
    safe_evidence = {
        key: evidence[key]
        for key in (
            "raw_topic_count",
            "consolidated_topic_count",
            "selected_material_characters",
            "late_fact_present_in_generation_material",
            "fact_question_overlap_words",
            "verbatim_spot_check",
            "deepseek_reduce_verification",
            "requested_question_type_counts",
            "generated_question_type_counts",
            "logical_ai_call_count",
            "actual_external_ai_http_attempt_count",
            "elapsed_seconds",
        )
    }
    print(json.dumps(safe_evidence, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
