"""
Prompt construction for quiz generation.

This is business-critical: the prompt is what makes the AI produce well-formed,
auto-gradeable questions strictly from the teacher's material. We describe the
EXACT JSON shape per question type so the output is machine-parseable, and we
constrain the model to the provided text only.
"""

from __future__ import annotations

import json

# The exact JSON contract for each supported (core-5) question type. Keeping the
# shapes explicit here is what lets us auto-grade reliably later.
TYPE_SPECS: dict[str, str] = {
    "mcq_single": (
        'mcq_single: exactly 4 options. '
        '"options": [{"id":"a","text":"..."},{"id":"b",...},{"id":"c",...},{"id":"d",...}]. '
        '"correct_answer": the id of the one correct option, e.g. "b".'
    ),
    "mcq_multi": (
        'mcq_multi: exactly 4 options, MORE THAN ONE correct. '
        '"options": [{"id":"a","text":"..."}, ... 4 total]. '
        '"correct_answer": array of the correct ids, e.g. ["a","c"].'
    ),
    "true_false": (
        'true_false: '
        '"options": [{"id":"true","text":"True"},{"id":"false","text":"False"}]. '
        '"correct_answer": "true" or "false".'
    ),
    "numerical": (
        'numerical: no options ("options": null). '
        '"correct_answer": {"value": <number>, "tolerance": <number>} — tolerance '
        'is the allowed +/- range for grading (0 if exact).'
    ),
    "fill_blank": (
        'fill_blank: put a blank as "____" inside question_text. "options": null. '
        '"correct_answer": {"answers": ["accepted answer", "acceptable synonym"]} — '
        "ALWAYS list the primary answer PLUS every reasonable synonym, abbreviation, "
        "or alternate spelling/phrasing a correct student might write, so grading "
        "accepts equivalent answers (e.g. [\"depreciation\", \"depn\"])."
    ),
}

LEVEL_GUIDANCE: dict[str, str] = {
    "theory": "Theory / recall: definitions, concepts, and direct understanding.",
    "practical": "Practical: application and multi-step problem solving.",
    "mixed": "A balanced blend of recall, application, and problem solving.",
}


def build_system_prompt(
    question_types: list[str], cognitive_level: str, difficulty: str
) -> str:
    specs = "\n".join(f"- {TYPE_SPECS[t]}" for t in question_types)
    level = LEVEL_GUIDANCE.get(cognitive_level, LEVEL_GUIDANCE["mixed"])
    return (
        "You are an expert exam-question author. You are given source material "
        "extracted from a teacher-uploaded textbook, PDF, or notes on ANY "
        "subject (e.g. programming, science, mathematics, accounting, commerce, "
        "law). You generate quiz questions that help students genuinely learn "
        "and remember the subject.\n\n"
        "WHAT TO TEST (this is the point of the quiz):\n"
        "- The CORE CONCEPTS, key terminology and definitions, mechanisms, and "
        "how to APPLY them. Aim for questions where a student who practises them "
        "repeatedly builds real recall and understanding of the subject.\n"
        "- Reinforce the important terms and ideas a student must retain, and "
        "reward genuine understanding over rote trivia.\n\n"
        "WHAT TO IGNORE (never generate questions about these):\n"
        "- Document metadata: title, edition, author, publisher, ISBN, copyright, "
        "dates, page/chapter numbers, table of contents, preface, "
        "acknowledgements, dedication, index, bibliography, or references.\n"
        "- Anything that is not the actual subject matter being taught.\n\n"
        "STRICT RULES:\n"
        "1. GROUNDING: Use ONLY concepts present in the source material. Never "
        "invent facts not present or directly implied. If the material is too "
        "thin for a good question, produce FEWER questions rather than padding "
        "with metadata or invented content.\n"
        "2. OUTPUT FORMAT: Respond with ONLY a valid JSON object of the form "
        '{"questions": [ ... ]}. No markdown fences, no preamble, no text '
        "outside the JSON. Field names, types, and casing must match exactly.\n"
        "3. QUESTION TYPES: Use ONLY the types listed below, matched to what the "
        "material supports. Each type has EXACTLY this JSON shape:\n"
        f"{specs}\n"
        "4. NO AMBIGUITY: Every question must be auto-gradeable with a single "
        "unambiguous correct answer. For MCQs, distractors must be plausible but "
        "clearly wrong according to the material.\n"
        "5. NO DUPLICATES: Do not test the identical fact or concept twice in "
        "different wording within this batch.\n"
        f"6. COGNITIVE LEVEL for ALL questions: {level}\n"
        f"7. DIFFICULTY for ALL questions: {difficulty} - judge by conceptual "
        "depth, not sentence length.\n"
        "8. EXPLANATION: Give a short, correct 'explanation' that reinforces the "
        "concept for the student.\n\n"
        'Each question object has: "type", "question_text", "options" (or null), '
        '"correct_answer", "explanation", "difficulty", "marks" (number, default '
        "1). Return the JSON object now - JSON only."
    )


def build_user_prompt(
    material: str,
    num_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
) -> str:
    types = ", ".join(question_types)
    return (
        f"Generate exactly {num_questions} questions from the material below.\n"
        f"Allowed types (mix them): {types}.\n"
        f"Cognitive level: {cognitive_level}. Difficulty: {difficulty}.\n\n"
        "=== MATERIAL START ===\n"
        f"{material}\n"
        "=== MATERIAL END ==="
    )


# ---------------------------------------------------------------------------
# Single-question regeneration (Slice 4): rewrite one question, same concept.
# ---------------------------------------------------------------------------

def build_regen_system_prompt(question_type: str) -> str:
    spec = TYPE_SPECS[question_type]
    return (
        "You are an expert exam-question author. You are given ONE existing quiz "
        "question. Write a DIFFERENT question of the SAME type that tests the same "
        "underlying concept - reworded, with fresh options/values where "
        "applicable - useful for a student practising that concept.\n\n"
        "RULES:\n"
        f"- The type MUST stay '{question_type}', in EXACTLY this JSON shape:\n"
        f"  {spec}\n"
        "- Auto-gradeable with a single unambiguous answer. For MCQs, distractors "
        "must be plausible but clearly wrong.\n"
        "- Do NOT copy the original wording - make it a genuine alternative.\n"
        "- Use ONLY facts, definitions, formulas, and examples supported by the "
        "provided ORIGINAL SOURCE MATERIAL. Never introduce outside facts.\n"
        "- Include a short, correct 'explanation'.\n\n"
        'OUTPUT: a JSON object {"questions": [ <one question> ]} - JSON only, no '
        "prose, no markdown fences."
    )


def build_regen_user_prompt(question: dict, source_material: str) -> str:
    slim = {
        k: question.get(k)
        for k in (
            "type",
            "question_text",
            "options",
            "correct_answer",
            "explanation",
            "difficulty",
            "marks",
        )
    }
    return (
        "ORIGINAL SOURCE MATERIAL:\n"
        "=== SOURCE START ===\n"
        + source_material
        + "\n=== SOURCE END ===\n\n"
        "EXISTING QUESTION:\n"
        + json.dumps(slim, ensure_ascii=False)
        + "\n\nWrite one fresh alternative question now."
    )
