from app.services.extraction import ExtractedText, PageSpan
from app.services.source_material import (
    evidence_occurs_in_material,
    evidence_page_ranges,
    is_meaningful_evidence,
    render_extracted_material,
)


def test_pdf_material_preserves_page_markers_and_slicing() -> None:
    extracted = ExtractedText(
        text="alpha fact\n\nbeta fact",
        page_spans=(PageSpan(1, 0, 10), PageSpan(2, 12, 21)),
    )
    rendered = render_extracted_material(extracted)
    assert "=== SOURCE PAGE 1 ===\nalpha fact" in rendered
    assert "=== SOURCE PAGE 2 ===\nbeta fact" in rendered
    assert evidence_page_ranges(rendered, "beta fact") == [(2, 2)]


def test_docx_material_remains_plain_text_without_fake_pages() -> None:
    extracted = ExtractedText(text="A paragraph from a document.")
    assert render_extracted_material(extracted) == "A paragraph from a document."


def test_compact_symbolic_evidence_is_meaningful_and_matches_notation_variants() -> None:
    assert is_meaningful_evidence("V = IR")
    assert is_meaningful_evidence("H₂O")
    assert evidence_occurs_in_material("P = VI = I²R", "Formula: P = VI = I2R")


def test_incomplete_symbolic_prefix_does_not_verify_a_longer_formula() -> None:
    assert not evidence_occurs_in_material("KE = 1/2mv", "Formula: KE = 1/2mv²")
    assert not evidence_occurs_in_material("H₂O", "Compound: H₂O₂")
