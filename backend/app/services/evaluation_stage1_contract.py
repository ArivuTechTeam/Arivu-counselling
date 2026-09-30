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

SELECTED-RESPONSE TRANSCRIPTION IS NOT GRADING: you are not given the answer
key. Capture only the option label(s) visibly chosen by the student. A crossed-
out choice is not selected. If the student clearly cancels one choice and
selects another, return only the live choice. Never convert a written
explanation into an option label.

UNLABELLED CONTINUATIONS BELONG TO THE HEADING ABOVE THEM: a table, working
or paragraph carrying no question number of its own belongs to the nearest
UNCANCELLED question heading above it, including across page breaks. Students
routinely write one heading and then continue for several pages -- every one
of those pages is still that question, and each one takes that heading's
NUMBER as its question_ref (not its own title). Do not invent a new ref for
them and do not carry over a ref from a cancelled block. A content heading
such as "Solution", "Provision", "High Court", "Working Notes", or an account
name is not a visible question reference. Keep the previous live numbered
heading across the page break; if it cannot be recovered safely, use "" rather
than putting that caption into visible_question_ref.

NESTED NUMBERING -- GIVE THE FULL PATH: when a question has a heading and then
its own internal list (the student writes "1.", then "(a) True or False", then
numbered items "1." "2." "3."), each item's ref is the FULL path from the top:
"1(a)(1)", "1(a)(2)", "1(a)(3)". Never emit the bare item number on its own --
a lone "3." looks like Question 3 and sends a True/False answer to a
ten-mark question.

STUDENTS ANSWER OUT OF ORDER: the order answers appear on the page is NOT the
question order. A student may answer Q6 before Q5, or begin Q6, cancel it, and
write Q5 underneath it on the same page. Use the nearest uncancelled heading
ABOVE the content as the authoritative reference when it exists in the
canonical guide. Use content to map only when that heading cannot be read or
is not a real guide reference. Never infer a reference from page sequence,
and never assume a later page means a later question number. Mis-assigning a
continuation hands one question's work to another question, so the student
loses the marks twice: once where the work is missing, once where it does not
belong.

QUESTION-BOUNDARY SWEEP (MANDATORY): a single ruled/physical table can cross
several separately-numbered questions. Detect each new visible question or
sub-question heading even when it appears halfway down the same table or page.
A new top-level heading such as "2." ends the preceding Q1 block and starts Q2;
do not let the continued ruling make Q1 rows inherit Q2. Assign every row its
own row_question_refs value, then return a separate table object for every
exact canonical atomic question. Repeat the headers for each split object.

SHORTHAND PARENT BOUNDARIES ARE STILL BOUNDARIES: students commonly write only
a sibling marker such as "(c)" after completing "1(b)", while the canonical
guide lists the finer children "1(c)(i)", "1(c)(ii)", and "1(c)(iii)". The
visible "(c)" immediately ENDS the 1(b) block and opens structural parent
"1(c)". Never include any writing below that marker in 1(b) raw_text, tables,
or workings, and never transcribe the marker as a word such as "other". Use a
structural-parent guide ref when supplied; then map separately identifiable
child work to its atomic child. If the child cannot be separated safely, keep
the combined work on the structural parent so Stage 2 can test it independently
against each child rubric. Apply the same rule universally to any nested
numbering style, not only this example.

CARET-INSERTED CORRECTIONS: a word or phrase written above the line with a
^ or other insertion mark shows exactly where the student wants it inserted.
Include it at that position in your transcription as part of the final
sentence -- this is the student's intended final wording. Omitting an
inserted word (e.g. "not") can silently reverse the meaning of the whole
answer, which is worse than leaving it out of a table cell.

JOURNAL ENTRIES ARE ALWAYS TABLES: any journal entry -- even a single Dr/Cr
line -- MUST be extracted as a table (table_type: journal_entry) with columns
[Particulars, Dr, Cr], one row per line including narration lines like
"(Being ...)" (blank Dr/Cr for those rows). Never fold a journal entry into a
text_answers raw_text paragraph -- that loses the Dr/Cr column structure the
student actually wrote in. Keep multiple entries together ONLY when they all
answer the same exact canonical atomic question. If the canonical guide has
separate refs such as 1(i), 1(ii), 1(iii), or 2(i), each ref MUST be a separate
table object even when the student drew one continuous table around all of
them. A table object's question_ref and every non-empty row_question_refs value
inside it must therefore identify that same exact canonical question.

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
