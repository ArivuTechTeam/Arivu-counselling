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

    def analyzer(document: str, page_count: int, title: str) -> dict:
        calls.append((document, page_count, title))
        return {
            "document_title": "Networking",
            "topics": [
                {
                    "topic_name": "Local Area Networks",
                    "subtopics": ["LAN basics", "Ethernet"],
                    "page_ranges": [{"start": 1, "end": 2}],
                    "evidence_pages": [1, 2],
                },
                {
                    "topic_name": "Packet Forwarding",
                    "subtopics": ["Routers"],
                    "page_ranges": [{"start": 3, "end": 3}],
                    "evidence_pages": [3],
                },
                {
                    "topic_name": "Addressing",
                    "subtopics": ["MAC addresses"],
                    "page_ranges": [{"start": 2, "end": 2}],
                    "evidence_pages": [2],
                },
            ],
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
    assert result["analysis_mode"] == "single_call_ai_outline"
    assert result["single_call_outline"]["provider_calls"] == 1
    first = result["topics"][0]
    assert first["source_page_ranges"] == [{"start": 1, "end": 2}]
    assert first["source_excerpts"][0]["text"] in extracted.text
    assert {item["page_start"] for item in first["source_excerpts"]} == {1, 2}


def test_rejects_oversized_document_before_calling_model() -> None:
    extracted = _document(["x" * 2_000 for _ in range(400)])
    called = False

    def analyzer(*_args):
        nonlocal called
        called = True
        return {}

    with pytest.raises(ValueError, match="exceeds the one-call cost limit"):
        build_single_call_ai_outline(extracted, analyzer=analyzer)
    assert called is False
