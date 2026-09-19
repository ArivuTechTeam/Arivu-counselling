from app.services.extraction import ExtractedText, PageSpan
from app.services.local_document_outline import build_local_pdf_outline


def _extracted(pages: list[str]) -> ExtractedText:
    text_parts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    for page_number, page in enumerate(pages, start=1):
        if text_parts:
            cursor += 2
        start = cursor
        cursor += len(page)
        spans.append(PageSpan(page_number, start, cursor))
        text_parts.append(page)
    return ExtractedText("\n\n".join(text_parts), tuple(spans))


def test_builds_page_grounded_outline_from_typed_pdf_index() -> None:
    pages = [
        "Course title\nUNIT - I: Networks and models",
        "INDEX\nUNIT NO TOPIC PAGE NO\nNetworks 1\nModels 2\nPhysical Layer 3\nData Link 4\nRouting 5\nTransport 6",
        "UNIT - I\nNETWORKS\nA network connects devices so that they can exchange information.",
        "REFERENCE MODELS\nA reference model organises communication responsibilities into layers.",
        "PHYSICAL LAYER\nThe physical layer transmits bits over a communication medium.",
        "DATA LINK\nThe data-link layer provides framing and link-level error control.",
        "ROUTING\nRouting selects a path through an interconnected packet network.",
        "TRANSPORT\nThe transport layer provides process-to-process communication.",
    ]

    outline = build_local_pdf_outline(_extracted(pages))

    assert outline is not None
    assert outline["analysis_mode"] == "local_typed_pdf_outline"
    assert outline["local_outline"]["provider_calls"] == 0
    assert outline["local_outline"]["printed_to_physical_page_offset"] == 2
    assert [topic["topic_name"] for topic in outline["topics"]] == [
        "Networks", "Models", "Physical Layer", "Data Link", "Routing", "Transport"
    ]
    assert outline["topics"][0]["source_page_ranges"] == [{"start": 3, "end": 3}]
    assert outline["topics"][0]["source_excerpts"][0]["page_start"] == 3


def test_rejects_pdf_without_reliable_index() -> None:
    pages = [f"Ordinary body page {index}. No structured contents here." for index in range(10)]
    assert build_local_pdf_outline(_extracted(pages)) is None


def test_rejects_short_or_pageless_documents() -> None:
    assert build_local_pdf_outline(ExtractedText("plain document")) is None

