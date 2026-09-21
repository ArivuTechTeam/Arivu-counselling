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

Page ranges are approximate provenance supplied by deterministic PDF extraction;
the model must preserve/merge them, never invent page numbers itself.
"""

from __future__ import annotations

from app.services.prompt_security import UNTRUSTED_SOURCE_RULE

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
    '    "worked_examples": [{"description": "string", "full_example_text": "verbatim with all values and steps"}],\n'
    '    "source_excerpts": [{"text": "meaningful verbatim passage", "page_start": 1, "page_end": 2}],\n'
    '    "source_page_ranges": [{"start": 1, "end": 2}]\n'
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
    f"{UNTRUSTED_SOURCE_RULE}You are analysing a document to understand what it is fundamentally about, "
    "so that an exam can later be built ONLY from its real subject matter.\n\n"
    "Read the material and identify the core SUBJECT it teaches and its main "
    "teachable themes. Look past front matter — title, author, copyright, table "
    "of contents, foreword, testimonials, 'how to use', marketing — and focus on "
    "what a student is actually meant to learn.\n\n"
    "This platform accepts every academic domain: sciences, mathematics, history, "
    "geography, accounting, economics, technology, literature, arts, law, and "
    "interdisciplinary material. Do not force the document into a STEM template.\n\n"
    "Identify whether its teachable evidence is mainly conceptual, factual, "
    "chronological, interpretive, quantitative, procedural, textual, visual, or a "
    "mixture. Note the reasoning students are expected to use and any obvious source "
    "quality caution without correcting the source.\n\n"
    "Return ONLY valid JSON (no commentary), exactly this shape:\n"
    '{"language":"primary language/script","subject":"short subject phrase","domain":"broad academic domain",'
    '"content_style":"conceptual/factual/chronological/interpretive/quantitative/procedural/mixed",'
    '"reasoning_style":"the reasoning the material supports",'
    '"definitions_and_terminology":["important definition/term signals"],'
    '"chronology_signals":["dates, people, events, sequences"],'
    '"quantitative_signals":["formulas, units, calculations"],'
    '"process_signals":["processes, mechanisms, cause/effect relationships"],'
    '"structured_data_signals":["tables or structured data"],'
    '"example_signals":["case studies or worked examples"],'
    '"code_signals":["code languages, snippets, or behaviour"],'
    '"visual_dependencies":["diagram/figure-dependent concepts that text alone may not support"],'
    '"supported_question_types":["mcq_single, mcq_multi, true_false, numerical, fill_blank as supported"],'
    '"source_quality_warnings":["only obvious cautions; empty when none"],'
    '"summary":"2-4 sentences on what the document teaches"}'
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
    f"{UNTRUSTED_SOURCE_RULE}You are an expert exam-setter extracting genuinely TEACHABLE study content "
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
    "BUILD A USEFUL HIERARCHY: top-level topic_name values must be meaningful "
    "faculty-facing units or major concepts that can reasonably be selected for a "
    "quiz. Put the named laws, definitions, events, processes, formulas, commands, "
    "examples, and other narrower concepts they contain in subtopics and the rich "
    "evidence fields. Do not create a separate top-level topic for every isolated "
    "term or sentence. Do not merely repeat vague chapter labels either: a good "
    "top-level topic is specific enough to assess but broad enough to contain a "
    "coherent group of related concepts. For example, Electromagnetism may contain "
    "Ohm's Law and Electric Power as subtopics; Network Transport may contain TCP "
    "connection setup and release. Preserve all testable detail under its parent.\n\n"
    "TOPIC NAMES must be faithful to the source. Prefer an explicit heading, named "
    "principle, event, person, work, method, or term found in this section. You may "
    "make a label clearer, but never broaden it into a theory or concept the source "
    "does not actually state or demonstrate. For example, a lone potential-energy "
    "formula does not establish a topic called 'Conservation of Energy'.\n\n"
    "For the content you DO keep, so a correct question can be written from it:\n"
    "- keep definitions, facts, figures, formulas, and worked examples VERBATIM "
    "(or near-verbatim); never paraphrase them;\n"
    "- preserve exact numbers, units, formulas, terminology, and the full steps "
    "of worked examples;\n"
    "- extract the KEY gradeable items, not the entire prose.\n\n"
    "For every topic, also include 1-3 complete source_excerpts copied exactly "
    "from this section. An excerpt can be a prose passage or compact evidence such "
    "as an equation, code line, date, quotation, or table row; do not pad a complete "
    "short equation merely to satisfy a length target. Each excerpt must support a "
    "future question and answer. Use the supplied approximate page range when available; "
    "otherwise use null for page_start/page_end.\n\n"
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
    page_start: int | None = None,
    page_end: int | None = None,
) -> str:
    """User prompt for one chunk. `chunk_number` is 1-based for readability."""
    title = document_title or "Untitled document"
    header = f'Document: "{title}". Section {chunk_number} of {total_chunks}.'
    if document_summary:
        header += f"\nWhat this document is about: {document_summary}"
    if page_start is not None and page_end is not None:
        header += f"\nApproximate source pages: {page_start}-{page_end}."
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
    f"{UNTRUSTED_SOURCE_RULE}You are creating a compact semantic merge PLAN for topics extracted from "
    "multiple OVERLAPPING sections of ONE document. The backend will apply your "
    "plan to the original verbatim material deterministically, so you must NOT "
    "repeat definitions, facts, formulas, examples, or excerpts in your output.\n\n"
    "Do THREE things:\n"
    "1) DROP any topic that is not genuinely teachable subject matter — e.g. "
    "book/document metadata, table of contents, foreword or preface, about-the-"
    "author, testimonials, licensing, 'how to use the book', bonus material, "
    "marketing, or a bare exercise prompt. When unsure whether something is core "
    "to the document's subject, drop it.\n"
    "2) MERGE semantically-equivalent topics into ONE group by listing their "
    "source_topic_ids together. Use every retained source id exactly once.\n"
    "3) Create a FACULTY-FACING hierarchy: merge related narrow topics into "
    "coherent major units while keeping unrelated units separate and in natural "
    "teaching order. A long textbook should not surface every definition or minor "
    "term as a separate selectable topic. The backend preserves every source "
    "topic as a subtopic and retains all of its evidence after the merge. Avoid "
    "both extremes: hundreds of micro-topics and a handful of vague headings.\n\n"
    "Put genuinely non-teachable source ids in discarded_source_topic_ids. Do "
    "not discard a topic merely because it is specialised or appears only once. "
    "Never invent an id and never place an id in more than one group.\n\n"
    "Return ONLY valid JSON (no commentary), exactly this compact shape:\n"
    '{"topic_groups":[{"topic_name":"merged display name",'
    '"source_topic_ids":["T0001","T0002"]}],'
    '"discarded_source_topic_ids":["T0003"]}'
)


def build_reduce_user_prompt(
    *, document_title: str, topics_json: str, document_summary: str = ""
) -> str:
    """User prompt for REDUCE. ``topics_json`` is a compact topic catalogue.

    Rich verbatim fields deliberately stay out of this call: the model only
    decides semantic grouping, then the backend merges the saved source objects.
    This prevents large documents from exhausting provider output limits.
    """
    title = document_title or "Untitled document"
    header = f'Document: "{title}".'
    if document_summary:
        header += f"\nWhat this document is about: {document_summary}"
    return (
        f"{header}\n"
        "Below is a compact catalogue of topics extracted from every section of "
        "this document. Sections overlap, so expect semantic duplicates. Return "
        "only the merge plan; the backend retains and combines the complete "
        "verbatim source material.\n\n"
        "=== TOPIC CATALOGUE (JSON) ===\n"
        f"{topics_json}\n"
        "=== END ==="
    )
