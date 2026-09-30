from app.services.paper_generation import fix_instructions_text, reletter_sections, sum_paper_marks


def test_reletters_sections_consecutively():
    rows = [
        {"type": "section_header", "number": "A", "question": "Section A: Objective"},
        {"type": "question", "number": "1"},
        {"type": "section_header", "number": "C", "question": "Section C: Long"},
    ]
    assert reletter_sections(rows) == ["A", "B"]
    assert rows[-1]["question"] == "Section B: Long"


def test_instruction_numbering_and_section_count_are_corrected():
    assert fix_instructions_text(["1. Read carefully", "The paper comprises six sections"], ["A", "B"]) == [
        "Read carefully",
        "The question paper comprises two sections - A and B. All questions are compulsory.",
    ]


def test_total_prefers_positive_parts_and_falls_back_from_zero_parts():
    assert sum_paper_marks([
        {"marks": 99, "parts": [{"marks": 4}, {"marks": 6}]},
        {"marks": 5, "parts": [{"marks": 0}]},
        {"marks": 2},
        "junk",
    ]) == 17
