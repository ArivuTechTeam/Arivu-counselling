"""
Prompt construction for quiz generation.

This is business-critical: the prompt is what makes the AI produce well-formed,
auto-gradeable questions strictly from the teacher's material. We describe the
EXACT JSON shape per question type so the output is machine-parseable, and we
constrain the model to the provided text only.
"""

from __future__ import annotations

import json

from app.services.prompt_security import UNTRUSTED_SOURCE_RULE

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
    "assertion_reason": (
        'assertion_reason: state an Assertion and a Reason INSIDE question_text as '
        'two lines: "Assertion (A): <statement>" then "Reason (R): <statement>". '
        'Use EXACTLY these 4 options verbatim: '
        '"options": ['
        '{"id":"a","text":"Both A and R are true and R is the correct explanation of A"},'
        '{"id":"b","text":"Both A and R are true but R is NOT the correct explanation of A"},'
        '{"id":"c","text":"A is true but R is false"},'
        '{"id":"d","text":"A is false but R is true"}]. '
        '"correct_answer": the id of the one correct option, e.g. "a".'
    ),
    "mrm": (
        'mrm (multiple-response, partial credit): 4 to 6 options, MORE THAN ONE '
        'correct. "options": [{"id":"a","text":"..."}, ... ]. '
        '"correct_answer": array of ALL correct ids, e.g. ["a","c","d"]. Grading '
        "awards marks per correct selection minus wrong ones, so every correct "
        "option must be genuinely correct and every distractor genuinely wrong."
    ),
    "matching": (
        'matching: two columns to pair up. "options" holds BOTH columns, each item '
        'tagged with its side: [{"id":"l1","side":"left","text":"..."}, ... , '
        '{"id":"r1","side":"right","text":"..."}, ... ]. Provide 3-5 left items and '
        'at least as many right items (extra right items are allowed as distractors). '
        'All ids unique. "correct_answer": {"pairs": {"l1":"r1","l2":"r2", ...}}. '
        "map EVERY left id to exactly one right id. Each side item must be short and "
        "unambiguous so exactly one pairing is correct."
    ),
}

LEVEL_GUIDANCE: dict[str, str] = {
    "theory": "Theory / recall: definitions, concepts, and direct understanding.",
    "practical": "Practical: application and multi-step problem solving.",
    "mixed": "A balanced blend of recall, application, and problem solving.",
}

DIFFICULTY_GUIDANCE: dict[str, str] = {
    "easy": (
        "Use direct understanding or one clear step, but do not reveal the rule or "
        "answer in the question stem."
    ),
    "medium": (
        "Require interpretation or application rather than copying a source sentence. "
        "The student must identify the relevant concept or method."
    ),
    "hard": (
        "Require method selection plus deeper reasoning, such as a multi-step "
        "application, combining two supported relationships, diagnosing a "
        "misconception, comparing plausible alternatives, or applying a concept in "
        "an unfamiliar scenario. Do not use direct definition recall, direct formula "
        "recall, or a one-step substitution labelled as hard. For hard True/False, "
        "test a consequence, constraint, or misconception—not a copied source fact."
    ),
}

STUDENT_FACING_RULES = (
    "STUDENT-FACING WORDING:\n"
    "- Every question must stand alone. Never say 'according to the handbook', "
    "'from the document', 'based on the provided material', 'as stated in the "
    "text', or refer to any PDF, notes, passage, chapter, page, source, or teacher "
    "upload. The student may never have seen that file.\n"
    "- Never put the answer-bearing formula, equation, rule, definition, or source "
    "sentence in the question stem. A numerical/application question must give the "
    "scenario and all input values in ordinary language, then require the student "
    "to recall and select the method. Do not write 'using the formula X=...'.\n"
    "- If the task is to identify an equation, place candidate equations only in "
    "the answer options; do not state the correct equation in the stem.\n"
    "- The explanation shown after answering may demonstrate the formula or rule, "
    "but it must explain the concept directly and must not mention the source file.\n"
)


def build_system_prompt(
    question_types: list[str], cognitive_level: str, difficulty: str
) -> str:
    specs = "\n".join(f"- {TYPE_SPECS[t]}" for t in question_types)
    level = LEVEL_GUIDANCE.get(cognitive_level, LEVEL_GUIDANCE["mixed"])
    difficulty_guidance = DIFFICULTY_GUIDANCE.get(
        difficulty, DIFFICULTY_GUIDANCE["medium"]
    )
    return (
        f"{UNTRUSTED_SOURCE_RULE}You are an expert exam-question author. You are given source material "
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
        "For an application question, you MAY introduce neutral exercise inputs "
        "(for example a mass, date interval, transaction amount, or variable value) "
        "only when every input is stated in the question and the answer follows "
        "directly from a source formula/rule. Never present an invented exercise "
        "input as a fact from the document.\n"
        "2. OUTPUT FORMAT: Respond with ONLY a valid JSON object of the form "
        '{"questions": [ ... ]}. No markdown fences, no preamble, no text '
        "outside the JSON. Field names, types, and casing must match exactly.\n"
        "3. QUESTION TYPES: Use ONLY the types listed below, matched to what the "
        "material supports. Each type has EXACTLY this JSON shape:\n"
        f"{specs}\n"
        "4. NO AMBIGUITY: Every question must be auto-gradeable with a single "
        "unambiguous correct answer. For MCQs, distractors must be plausible but "
        "clearly wrong according to the material.\n"
        "5. NO DUPLICATES: Do not test the same evidence with the same skill twice, "
        "even using different wording or question types. Formula recognition, "
        "rearrangement, and numerical application are different skills; repeated "
        "formula-recognition questions are duplicates.\n"
        f"6. COGNITIVE LEVEL for ALL questions: {level}\n"
        f"7. DIFFICULTY for ALL questions: {difficulty} - judge by conceptual "
        "depth, not sentence length.\n"
        "8. EXPLANATION: Give a short, correct 'explanation' that reinforces the "
        "concept for the student.\n\n"
        f"{STUDENT_FACING_RULES}\n"
        f"DIFFICULTY STANDARD: {difficulty_guidance}\n\n"
        "9. SOURCE EVIDENCE: Copy the smallest complete supporting evidence EXACTLY "
        "from the supplied material into 'source_excerpt'. Evidence may be prose, "
        "a short equation, chemical formula, code line, date, quotation, or table "
        "value. A complete equation such as 'V = IR' is valid even though it is "
        "short. Do not paraphrase it. For derived application questions, cite the "
        "source formula/rule rather than the exercise values you introduced. Set "
        "'source_page_start' and 'source_page_end' from the nearest explicit source "
        "page/range label; use null for both when the material has no page labels. "
        "Preserve mathematical, scientific, linguistic, and code notation exactly: "
        "never replace θ with q, lose a negative sign, change units, or silently "
        "remove superscripts/subscripts. Set 'grounding_confidence' to a number from 0 to 1 representing how directly "
        "the excerpt supports the question and answer.\n\n"
        'Each question object has: "type", "question_text", "options" (or null), '
        '"correct_answer", "explanation", "difficulty", "marks" (number, default '
        '1), "source_excerpt", "source_page_start", "source_page_end", and '
        '"grounding_confidence". Return the JSON object now - JSON only.'
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

def build_regen_system_prompt(
    question_type: str, difficulty: str = "medium"
) -> str:
    spec = TYPE_SPECS[question_type]
    difficulty_guidance = DIFFICULTY_GUIDANCE.get(
        difficulty, DIFFICULTY_GUIDANCE["medium"]
    )
    return (
        f"{UNTRUSTED_SOURCE_RULE}You are an expert exam-question author. You are given ONE existing quiz "
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
        f"{STUDENT_FACING_RULES}\n"
        f"- The rewritten question must be {difficulty}: {difficulty_guidance}\n\n"
        "- Include a meaningful verbatim 'source_excerpt', its supplied page range "
        "(or null/null), and 'grounding_confidence' from 0 to 1.\n\n"
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
