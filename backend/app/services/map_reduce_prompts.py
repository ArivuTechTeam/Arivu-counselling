"""
Prompts for the large-document Map-Reduce pipeline.

PROFILE — read the document and say what it is fundamentally about.
MAP     — per-chunk extraction of genuinely TEACHABLE content (guided by the profile).
REDUCE  — consolidate into one clean, de-duplicated Master Blueprint.

Design goals (why these prompts are strict):
  * We pay for the model to THINK, not to mirror the table of contents. So MAP is
    told to break material into the distinct concepts a student must learn — not
    to echo chapter/section headings.
  * A quiz must test the SUBJECT, never the book. So both MAP and REDUCE are told
    to ignore front matter / metadata (title, copyright, ISBN, TOC, foreword,
    testimonials, licensing, "how to use", marketing) and to treat incidental
    numbers (ISBNs, years, prices, reading times) as NOT gradeable.
  * The document PROFILE (subject + summary) is injected into MAP and REDUCE so
    each step can judge what is core vs. peripheral to THIS document, even inside
    a chapter — a single chunk in isolation often can't tell.

No page numbers anywhere: we chunk by character offset on extracted text, so page
metadata doesn't exist and asking for it would only invite hallucination.
"""

from __future__ import annotations

# The one topic shape every step speaks. Kept in a single place so MAP and REDUCE
# never drift apart.
_TOPIC_SCHEMA = (
    '{"topics": [\n'
    '  {\n'
    '    "topic_name": "string",\n'
    '    "subtopics": ["string", ...],\n'
    '    "key_definitions": [{"term": "string", "definition": "verbatim"}],\n'
    '    "key_facts_and_figures": ["verbatim fact / statistic / figure"],\n'
    '    "formulas": [{"name": "string", "formula": "exact", "variables_explained": "string"}],\n'
    '    "worked_examples": [{"description": "string", "full_example_text": "verbatim with all values and steps"}]\n'
    '  }\n'
    "]}"
)

# What both MAP and REDUCE must refuse to treat as subject matter.
_IGNORE_BLOCK = (
    "IGNORE everything that is not the subject being taught, even when it appears "
    "in the material. This includes, but is not limited to:\n"
    "- book/document metadata: title pages, author names, edition, copyright, "
    "ISBN, publisher, dedication;\n"
    "- table of contents, index, lists of chapters/sections, page numbers;\n"
    "- forewords, prefaces, 'about the author', acknowledgements, testimonials, "
    "reviews, or praise quotes;\n"
    "- 'how to use this book', 'how long will it take', learning tips, bonus "
    "material, licensing terms, formatting conventions;\n"
    "- marketing, pricing, 'buy the full version', URLs, contact / feedback info;\n"
    "- bare exercise or challenge prompts that contain no teachable explanation.\n"
    "Incidental numbers such as ISBNs, years, prices, page counts, or reading "
    "times are NOT gradeable facts — never extract them. Every fact you keep must "
    "be about the SUBJECT, not about the book, its authors, or how to read it."
)


# --- PROFILE ---------------------------------------------------------------
PROFILE_SYSTEM = (
    "You are analysing a document to understand what it is fundamentally about, "
    "so that an exam can later be built ONLY from its real subject matter.\n\n"
    "Read the material and identify the core SUBJECT it teaches and its main "
    "teachable themes. Look past front matter — title, author, copyright, table "
    "of contents, foreword, testimonials, 'how to use', marketing — and focus on "
    "what a student is actually meant to learn.\n\n"
    "Return ONLY valid JSON (no commentary), exactly this shape:\n"
    '{"subject": "a short phrase naming the subject", '
    '"summary": "2-4 sentences on what this document teaches and the main topics '
    'a student should learn from it"}'
)


def build_profile_user_prompt(text: str) -> str:
    return (
        "Analyse the document below and identify its core subject and main "
        "teachable topics.\n\n"
        "=== DOCUMENT START ===\n"
        f"{text}\n"
        "=== DOCUMENT END ==="
    )


# --- MAP -------------------------------------------------------------------
MAP_SYSTEM = (
    "You are an expert exam-setter extracting genuinely TEACHABLE study content "
    "from ONE section of a larger document, so exam-quality questions can be "
    "written from it later.\n\n"
    "You are told what the overall document is about — use that to judge what is "
    "core subject matter in THIS section and what is peripheral or irrelevant.\n\n"
    "Sections overlap slightly at the edges on purpose; duplication with "
    "neighbouring sections is fine and is reconciled later.\n\n"
    "EXTRACT ONLY the concepts, definitions, facts, formulas, and worked examples "
    "a student must actually LEARN and could fairly be tested on.\n\n"
    f"{_IGNORE_BLOCK}\n\n"
    "If THIS section contains no teachable subject content, return "
    '{"topics": []}.\n\n'
    "BE GRANULAR: break the material into the DISTINCT concepts a student must "
    "understand — do NOT merely echo chapter or section headings. One heading "
    "usually contains several teachable concepts; capture each as its own topic "
    "or as clearly-named subtopics.\n\n"
    "For the content you DO keep, so a correct question can be written from it:\n"
    "- keep definitions, facts, figures, formulas, and worked examples VERBATIM "
    "(or near-verbatim); never paraphrase them;\n"
    "- preserve exact numbers, units, formulas, terminology, and the full steps "
    "of worked examples;\n"
    "- extract the KEY gradeable items, not the entire prose.\n\n"
    "Return ONLY valid JSON (no commentary), exactly this shape:\n"
    f"{_TOPIC_SCHEMA}"
)


def build_map_user_prompt(
    *,
    document_title: str,
    chunk_number: int,
    total_chunks: int,
    content: str,
    document_summary: str = "",
) -> str:
    """User prompt for one chunk. `chunk_number` is 1-based for readability."""
    title = document_title or "Untitled document"
    header = f'Document: "{title}". Section {chunk_number} of {total_chunks}.'
    if document_summary:
        header += f"\nWhat this document is about: {document_summary}"
    return (
        f"{header}\n"
        "Extract the teachable study content from THIS section below "
        "(ignore anything that is not core to the subject above).\n\n"
        "=== SECTION START ===\n"
        f"{content}\n"
        "=== SECTION END ==="
    )


# --- REDUCE ----------------------------------------------------------------
REDUCE_SYSTEM = (
    "You are consolidating extracted study content from multiple OVERLAPPING "
    "sections of ONE document into a single clean Master Blueprint for an exam. "
    "You are told what the document is about.\n\n"
    "Do THREE things:\n"
    "1) DROP any topic that is not genuinely teachable subject matter — e.g. "
    "book/document metadata, table of contents, foreword or preface, about-the-"
    "author, testimonials, licensing, 'how to use the book', bonus material, "
    "marketing, or a bare exercise prompt. When unsure whether something is core "
    "to the document's subject, drop it.\n"
    "2) MERGE semantically-equivalent topics into ONE (combine their subtopics, "
    "definitions, facts, formulas, and examples) and REMOVE duplicate or "
    "near-duplicate items, keeping the most complete version.\n"
    "3) Keep the result GRANULAR and well-organised: preserve the distinct "
    "teachable concepts — do NOT over-merge everything into a few broad "
    "headings — and keep them in natural teaching order.\n\n"
    "Incidental numbers (ISBNs, years, prices, page counts, reading times) are "
    "NOT gradeable facts; remove them. Keep definitions, facts, figures, "
    "formulas, and worked examples VERBATIM — do NOT paraphrase them. Do NOT "
    "invent, infer, or add anything not present in the input.\n\n"
    "Return ONLY valid JSON (no commentary), exactly this shape:\n"
    f"{_TOPIC_SCHEMA}"
)


def build_reduce_user_prompt(
    *, document_title: str, topics_json: str, document_summary: str = ""
) -> str:
    """User prompt for REDUCE. `topics_json` is the concatenated per-chunk topics
    (a JSON array) that the model must consolidate."""
    title = document_title or "Untitled document"
    header = f'Document: "{title}".'
    if document_summary:
        header += f"\nWhat this document is about: {document_summary}"
    return (
        f"{header}\n"
        "Below is the study content extracted from every section of this "
        "document (sections overlap, so expect duplicates, and some items may not "
        "be core to the subject). Consolidate it into a single de-duplicated "
        "Master Blueprint following the rules above.\n\n"
        "=== EXTRACTED TOPICS (JSON) ===\n"
        f"{topics_json}\n"
        "=== END ==="
    )
