"""Gemini Stage 1 transcription contract (no grading instructions)."""
from __future__ import annotations

STAGE1_EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "text_answers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "question_ref": {"type": "STRING"}, "visible_question_ref": {"type": "STRING"},
            "raw_text": {"type": "STRING"}, "leading_continuation_ref": {"type": "STRING"},
            "leading_continuation_text": {"type": "STRING"},
            "selected_options": {"type": "ARRAY", "items": {"type": "STRING"}},
            "selection_ambiguous": {"type": "BOOLEAN"}, "word_count": {"type": "INTEGER"},
            "has_headings": {"type": "BOOLEAN"}, "has_diagrams": {"type": "BOOLEAN"},
            "has_tables": {"type": "BOOLEAN"}, "source_document_index": {"type": "INTEGER"},
            "source_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["question_ref", "visible_question_ref", "raw_text",
            "leading_continuation_ref", "leading_continuation_text", "selected_options",
            "selection_ambiguous", "word_count", "has_headings", "has_diagrams",
            "has_tables", "source_document_index", "source_pages"]}},
        "tables": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "question_ref": {"type": "STRING"}, "visible_question_ref": {"type": "STRING"},
            "table_type": {"type": "STRING", "enum": ["journal_entry", "ledger",
                "balance_sheet", "profit_and_loss", "cash_flow", "cost_sheet",
                "trial_balance", "ratio_workings", "other"]},
            "headers": {"type": "ARRAY", "items": {"type": "STRING"}},
            "rows": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "row_question_refs": {"type": "ARRAY", "items": {"type": "STRING"}},
            "row_visible_question_refs": {"type": "ARRAY", "items": {"type": "STRING"}},
            "dr_total_by_student": {"type": "STRING"}, "cr_total_by_student": {"type": "STRING"},
            "computed_dr_total": {"type": "NUMBER"}, "computed_cr_total": {"type": "NUMBER"},
            "totals_match_student": {"type": "BOOLEAN"}, "totals_balance": {"type": "BOOLEAN"},
            "balance_difference": {"type": "NUMBER"},
            "difficult_cells": {"type": "ARRAY", "items": {"type": "STRING"}},
            "source_document_index": {"type": "INTEGER"},
            "source_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["question_ref", "visible_question_ref", "table_type", "headers", "rows",
            "row_question_refs", "row_visible_question_refs", "totals_balance",
            "computed_dr_total", "computed_cr_total", "difficult_cells",
            "source_document_index", "source_pages"]}},
        "numerical_workings": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "question_ref": {"type": "STRING"}, "visible_question_ref": {"type": "STRING"},
            "working_type": {"type": "STRING"}, "formula_used": {"type": "STRING"},
            "figures_substituted": {"type": "ARRAY", "items": {"type": "STRING"}},
            "final_answer": {"type": "STRING"}, "working_shown": {"type": "BOOLEAN"},
            "source_document_index": {"type": "INTEGER"},
            "source_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["question_ref", "visible_question_ref", "working_type", "formula_used",
            "final_answer", "working_shown", "source_document_index", "source_pages"]}},
        "page_manifest": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "document_index": {"type": "INTEGER"}, "page_number": {"type": "INTEGER"},
            "status": {"type": "STRING", "enum": ["content", "blank", "unreadable"]},
            "answer_content_present": {"type": "BOOLEAN"},
            "question_refs": {"type": "ARRAY", "items": {"type": "STRING"}},
            "notes": {"type": "STRING"},
        }, "required": ["document_index", "page_number", "status",
            "answer_content_present", "question_refs", "notes"]}},
        "legibility_report": {"type": "OBJECT", "properties": {
            "overall_legibility": {"type": "STRING", "enum": ["clear", "mostly_clear", "difficult", "illegible"]},
            "difficult_questions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "illegible_questions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "language_detected": {"type": "STRING"},
        }, "required": ["overall_legibility", "difficult_questions", "illegible_questions", "language_detected"]},
    },
    "required": ["text_answers", "tables", "numerical_workings", "page_manifest", "legibility_report"],
}

STAGE1_EXTRACTION_PROMPT = """You are a specialist document transcription engine.
Your ONLY job is to READ and EXTRACT what the student wrote. Do NOT evaluate,
judge, award marks, comment on correctness, or add grading information.

Return the exact supplied JSON contract. Transcribe text verbatim. For every text
answer, table, and numerical working include visible_question_ref, question_ref,
source_document_index and every physical source_pages value. A valid, live,
uncancelled visible heading is authoritative even when the content resembles a
different question; semantic mapping is only a fallback when that heading is
missing, unreadable, cancelled, or absent from the canonical guide. Never use a
caption or account name (for example Debtors A/c) as a question reference.

For text answers preserve paragraph and working-line breaks, selected option
labels, and any page-leading continuation in both raw_text and the explicit
leading_continuation fields. Exclude crossed-out work. For tables preserve every
header/cell and align row_question_refs and row_visible_question_refs 1:1 with
rows. Narration and blank continuation rows inherit the preceding entry; detect
each new question boundary even inside one ruled table. Compute Dr/Cr totals from
the rows without grading them. Capture formulas and substitutions verbatim.

PAGE-BY-PAGE COMPLETENESS SWEEP (MANDATORY): make a second independent
page-by-page sweep. Return exactly one page_manifest
row for every supplied PDF page, including blank/unreadable pages. Every content
page must be cited by extracted evidence and every manifest question reference
must have evidence on that page. The legibility lists contain canonical question
references only. If the whole script cannot be read, use overall_legibility
"illegible". Do not invent document indexes, pages, question references, text,
or provenance. Before finalizing, verify that every visible uncancelled question
heading has a corresponding text answer, table, or numerical working."""


def build_stage1_prompt(question_guide: list[dict], inventory: list[dict]) -> str:
    import json
    guide = question_guide or []
    return (
        STAGE1_EXTRACTION_PROMPT
        + "\n\nCANONICAL QUESTION GUIDE (may be empty):\n"
        + json.dumps(guide, ensure_ascii=False)
        + "\n\nSTUDENT PDF INVENTORY:\n"
        + json.dumps(inventory, ensure_ascii=False)
    )
