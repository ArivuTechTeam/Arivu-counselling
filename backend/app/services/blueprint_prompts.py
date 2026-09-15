"""
Prompt construction for blueprint-driven quiz generation (Slice 7).

Coverage model: the quiz covers the WHOLE document, but the teacher's selected
priority topics get MORE questions. Each question is tagged with the topic it
belongs to (an exact priority-topic name, or "General" for broad-coverage
questions). Reuses the exact per-type JSON shapes from quiz_prompts so questions
stay auto-gradeable.
"""

from __future__ import annotations

from app.services.quiz_prompts import LEVEL_GUIDANCE, TYPE_SPECS

GENERAL_TOPIC = "General"


def build_blueprint_system_prompt(
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    *,
    selected_only_material: bool = False,
) -> str:
    specs = "\n".join(f"- {TYPE_SPECS[t]}" for t in question_types)
    level = LEVEL_GUIDANCE.get(cognitive_level, LEVEL_GUIDANCE["mixed"])
    coverage_rule = (
        "- The supplied material contains ONLY the teacher-selected topics. Cover "
        "those topics according to the blueprint; do not introduce any topic or "
        "fact that is absent from the supplied material.\n\n"
        if selected_only_material
        else "- Cover the WHOLE document. The priority topics get MORE questions (as "
        "specified), but the 'general' questions must cover the REST of the "
        "material broadly. Do NOT restrict the quiz to only the priority topics.\n\n"
    )
    return (
        "You are an expert exam-question author for an exam-prep platform. You "
        "are given study material from a teacher's document plus a BLUEPRINT "
        "stating how many questions to write and which topics to emphasise.\n\n"
        "COVERAGE RULE (important):\n"
        f"{coverage_rule}"
        "TAGGING RULE:\n"
        '- Every question MUST include a "topic" field. If it is about a '
        'priority topic, set "topic" to that EXACT topic name. Otherwise set '
        f'"topic" to "{GENERAL_TOPIC}".\n\n'
        "WHAT TO TEST: core concepts, key terms/definitions, mechanisms, and how "
        "to APPLY them — questions that build real recall and understanding.\n"
        "WHAT TO IGNORE: document metadata (title, author, edition, ISBN, "
        "copyright, index, preface, page/chapter numbers, table of contents).\n\n"
        "STRICT RULES:\n"
        "1. GROUNDING: use ONLY concepts present in the material; never invent "
        "facts. If the material is thin for a topic, write fewer questions there "
        "rather than padding.\n"
        '2. OUTPUT: respond with ONLY a JSON object {"questions": [ ... ]}. No '
        "markdown fences, no prose outside the JSON.\n"
        '3. Each question object has: "topic", "type", "question_text", '
        '"options" (or null), "correct_answer", "explanation", "difficulty", '
        '"marks" (number, default 1).\n'
        "4. QUESTION TYPES — use ONLY these, each in EXACTLY this JSON shape:\n"
        f"{specs}\n"
        "5. Every question must be auto-gradeable with a single unambiguous "
        "answer; MCQ distractors plausible but clearly wrong per the material.\n"
        "6. No duplicate questions.\n"
        f"7. COGNITIVE LEVEL for all questions: {level}\n"
        f"8. DIFFICULTY for all questions: {difficulty} (judge by conceptual "
        "depth, not sentence length).\n"
        "9. Give a short, correct 'explanation' for each question.\n"
        "Return the JSON object now — JSON only."
    )


def build_blueprint_user_prompt(
    material: str,
    blueprint: dict,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    type_counts: dict[str, int] | None = None,
    *,
    selected_only_material: bool = False,
) -> str:
    types = ", ".join(question_types)
    per_topic = blueprint.get("mode") == "per_topic"

    # EXACT per-type mix: the teacher set how many of each type they want. This is
    # a HARD count (enforced after generation). For a per-topic blueprint it is the
    # aggregate across all topics.
    if type_counts:
        mix_lines = "\n".join(
            f"- {t}: exactly {n}" for t, n in type_counts.items() if n > 0
        )
        type_mix_block = (
            "EXACT TYPE MIX — the quiz MUST contain exactly this many of each "
            f"type (total {blueprint['total']}):\n{mix_lines}\n\n"
        )
    else:
        type_mix_block = ""

    if per_topic:
        # Explicit per-topic, per-format plan set by the teacher.
        blocks = []
        for t in blueprint["topics"]:
            fmt_lines = "\n".join(
                f"    - {fmt}: exactly {n}" for fmt, n in t["counts"].items()
            )
            blocks.append(
                f'  Topic "{t["name"]}" — exactly {t["num_questions"]} question(s):\n'
                f"{fmt_lines}"
            )
        topic_block = (
            "PER-TOPIC PLAN — produce EXACTLY the questions listed under each topic, "
            'and set each question\'s "topic" field to that EXACT topic name. Do NOT '
            "add any other topic or any extra questions:\n" + "\n".join(blocks) + "\n\n"
        )
        general_block = ""
    else:
        lines = [
            f'- "{t["name"]}" ({t["weight"]}): about {t["num_questions"]} questions'
            for t in blueprint["topics"]
        ]
        priority_block = (
            "\n".join(lines) if lines else "(none — general coverage only)"
        )
        topic_block = (
            "PRIORITY TOPICS — give these MORE questions, roughly as noted:\n"
            f"{priority_block}\n\n"
        )
        general_block = (
            ""
            if selected_only_material
            else f"GENERAL COVERAGE — about {blueprint['general']} more questions covering "
            "the REST of the document (anything not in the priority list); tag these "
            f'as "{GENERAL_TOPIC}".\n\n'
        )

    return (
        f"Write exactly {blueprint['total']} questions in total from the "
        "material below.\n"
        f"Allowed types (mix them): {types}.\n"
        f"Cognitive level: {cognitive_level}. Difficulty: {difficulty}.\n\n"
        f"{type_mix_block}"
        f"{topic_block}"
        f"{general_block}"
        "=== MATERIAL START ===\n"
        f"{material}\n"
        "=== MATERIAL END ==="
    )
