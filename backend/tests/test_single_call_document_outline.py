from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.extraction import ExtractedText, PageSpan
from app.services.single_call_document_outline import build_single_call_ai_outline


def _document(page_texts: list[str]) -> ExtractedText:
    parts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    for number, page in enumerate(page_texts, start=1):
        if parts:
            cursor += 2
        start = cursor
        cursor += len(page)
        parts.append(page)
        spans.append(PageSpan(number, start, cursor))
    return ExtractedText("\n\n".join(parts), tuple(spans))


def test_builds_exact_local_evidence_from_one_compact_model_response() -> None:
    extracted = _document([
        "LANs connect devices in a limited geographic area. " * 20,
        "Ethernet frames carry source and destination MAC addresses. " * 20,
        "Routers forward IP packets between different networks. " * 20,
    ])
    calls = []

    def analyzer(document: str, page_count: int, title: str, marker: str) -> dict:
        calls.append((document, page_count, title, marker))
        return {
            "document_title": "Networking",
            "groups": [{
                "group_name": "Network foundations",
                "topics": [
                    {
                        "topic_name": "Local Area Networks",
                        "covered_concepts": ["LAN basics", "Ethernet"],
                        "source_ranges": [{"start": 1, "end": 2}],
                        "evidence_locations": [1, 2],
                    },
                    {
                        "topic_name": "Packet Forwarding",
                        "covered_concepts": ["Routers"],
                        "source_ranges": [{"start": 3, "end": 3}],
                        "evidence_locations": [3],
                    },
                    {
                        "topic_name": "Addressing",
                        "covered_concepts": ["MAC addresses"],
                        "source_ranges": [{"start": 2, "end": 2}],
                        "evidence_locations": [2],
                    },
                ],
            }],
        }

    with patch(
        "app.services.single_call_document_outline.get_settings",
        return_value=SimpleNamespace(gemini_blueprint_model="gemini-lite"),
    ):
        result = build_single_call_ai_outline(
            extracted, document_title="network.pdf", analyzer=analyzer
        )

    assert len(calls) == 1
    assert "=== PDF PAGE 1 ===" in calls[0][0]
    assert calls[0][3] == "PDF PAGE"
    assert result["analysis_mode"] == "single_call_ai_outline"
    assert result["single_call_outline"]["provider_calls"] == 1
    first = result["topics"][0]
    assert first["parent_group"] == "Network foundations"
    assert first["source_page_ranges"] == [{"start": 1, "end": 2}]
    assert first["source_excerpts"][0]["text"] in extracted.text
    assert {item["page_start"] for item in first["source_excerpts"]} == {1, 2}


def test_rejects_oversized_document_before_calling_model() -> None:
    extracted = _document(["x" * 2_000 for _ in range(2_000)])
    called = False

    def analyzer(*_args):
        nonlocal called
        called = True
        return {}

    with pytest.raises(ValueError, match="too many source locations"):
        build_single_call_ai_outline(extracted, analyzer=analyzer)
    assert called is False


def test_small_document_can_return_one_topic_without_artificial_minimum() -> None:
    extracted = _document(["Photosynthesis converts light into chemical energy."])

    def analyzer(_document: str, _count: int, _title: str, _marker: str) -> dict:
        return {
            "document_title": "Biology note",
            "groups": [{
                "group_name": "Plant biology",
                "topics": [{
                    "topic_name": "Photosynthesis",
                    "covered_concepts": ["Light energy"],
                    "source_ranges": [{"start": 1, "end": 1}],
                    "evidence_locations": [1],
                }],
            }],
        }

    with patch(
        "app.services.single_call_document_outline.get_settings",
        return_value=SimpleNamespace(gemini_blueprint_model="gemini-lite"),
    ):
        result = build_single_call_ai_outline(extracted, analyzer=analyzer)

    assert result["source_topic_count"] == 1
    assert result["topics"][0]["topic_name"] == "Photosynthesis"


def test_non_paginated_document_uses_source_sections_and_local_evidence() -> None:
    extracted = ExtractedText(
        ("SMTP transfers email between servers. " * 100)
        + "\n\n"
        + ("TCP provides reliable ordered transport. " * 100)
    )
    calls = []

    def analyzer(document: str, count: int, title: str, marker: str) -> dict:
        calls.append((document, count, title, marker))
        return {
            "document_title": "Protocol notes",
            "groups": [{
                "group_name": "Transport protocols",
                "topics": [{
                    "topic_name": "Transmission Control Protocol",
                    "covered_concepts": ["Reliable transport"],
                    "source_ranges": [{"start": 2, "end": 2}],
                    "evidence_locations": [2],
                }],
            }],
        }

    with patch(
        "app.services.single_call_document_outline.get_settings",
        return_value=SimpleNamespace(gemini_blueprint_model="gemini-lite"),
    ):
        result = build_single_call_ai_outline(
            extracted, document_title="protocols.docx", analyzer=analyzer
        )

    assert calls[0][3] == "SOURCE SECTION"
    assert "=== SOURCE SECTION 2 ===" in calls[0][0]
    topic = result["topics"][0]
    assert topic["source_page_ranges"] == []
    assert topic["source_section_ranges"] == [{"start": 2, "end": 2}]
    assert topic["source_excerpts"][0]["source_section_start"] == 2


def test_non_paginated_long_line_is_split_into_bounded_source_sections() -> None:
    extracted = ExtractedText("networking " * 2_000)
    captured = {}

    def analyzer(document: str, count: int, _title: str, marker: str) -> dict:
        captured.update(document=document, count=count, marker=marker)
        return {
            "document_title": "Notes",
            "groups": [{
                "group_name": "Networking",
                "topics": [{
                    "topic_name": "Networking basics",
                    "covered_concepts": [],
                    "source_ranges": [{"start": 1, "end": count}],
                    "evidence_locations": [1],
                }],
            }],
        }

    with patch(
        "app.services.single_call_document_outline.get_settings",
        return_value=SimpleNamespace(gemini_blueprint_model="gemini-lite"),
    ):
        build_single_call_ai_outline(extracted, analyzer=analyzer)

    assert captured["marker"] == "SOURCE SECTION"
    assert captured["count"] > 1
    assert f"=== SOURCE SECTION {captured['count']} ===" in captured["document"]
