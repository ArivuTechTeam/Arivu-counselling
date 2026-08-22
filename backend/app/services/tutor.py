"""
AI Tutor — cached per-question explanations (SRS §14).

A student who gets a question wrong wants to understand WHY. We generate a
deeper step-by-step explanation, a plain-language "simplified" version, and a
couple of progressive hints — ONCE per question, cached in `ai_explanations`.
Every later student who sees that question reuses the cache, so the LLM is paid
at most once per question (a few paise), never per student.
"""

from __future__ import annotations

from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.llm.structured import gemini_json

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "explanation": {"type": "STRING"},
        "simplified": {"type": "STRING"},
        "hints": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["explanation", "simplified", "hints"],
}

_SYSTEM = (
    "You are a patient tutor for exam-prep students. Given ONE quiz question, its "
    "options, and the correct answer, produce a JSON object with:\n"
    "- 'explanation': a clear, step-by-step reason WHY the correct answer is "
    "correct and (briefly) why the tempting wrong options are wrong. Ground it "
    "only in the question; never invent facts.\n"
    "- 'simplified': the same idea in plain, everyday language a beginner "
    "understands, 2-3 sentences.\n"
    "- 'hints': 2-3 short progressive hints that nudge a student toward the "
    "answer WITHOUT stating it outright.\n"
    "Encouraging, concrete, no fluff. Output JSON only."
)


def _build_prompt(q: dict) -> str:
    opts = q.get("options") or []
    opt_lines = "\n".join(
        f"  {o.get('id')}. {o.get('text')}" for o in opts if isinstance(o, dict)
    )
    parts = [f"QUESTION ({q.get('type')}): {q.get('question_text')}"]
    if opt_lines:
        parts.append("OPTIONS:\n" + opt_lines)
    parts.append(f"CORRECT ANSWER: {q.get('correct_answer')}")
    if q.get("explanation"):
        parts.append(f"EXISTING SHORT NOTE: {q.get('explanation')}")
    return "\n".join(parts)


def explain_question(question_id: str, tenant_id: str) -> dict:
    """
    Return {explanation, simplified, hints, cached}. Serves the cached row if it
    exists; otherwise generates once (Flash-Lite), stores it, and returns it.
    """
    service = get_service_client()

    # 1) Cache hit? (ai_explanations has a UNIQUE(question_id))
    cached = (
        service.table("ai_explanations")
        .select("explanation_text, simplified_text, hints")
        .eq("question_id", question_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if cached:
        row = cached[0]
        return {
            "explanation": row.get("explanation_text") or "",
            "simplified": row.get("simplified_text") or "",
            "hints": row.get("hints") or [],
            "cached": True,
        }

    # 2) Fetch the question (tenant-scoped).
    qrow = (
        service.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not qrow:
        raise ValueError("Question not found.")
    q = qrow[0]

    # 3) Generate once (cheap model).
    model = get_settings().gemini_blueprint_model
    data = gemini_json(_SYSTEM, _build_prompt(q), _SCHEMA, model=model, temperature=0.3)
    explanation = (data.get("explanation") or "").strip()
    simplified = (data.get("simplified") or "").strip()
    hints = [h.strip() for h in (data.get("hints") or []) if isinstance(h, str) and h.strip()]

    # 4) Cache it (best-effort; a race just means two writes, one wins the unique).
    try:
        service.table("ai_explanations").insert(
            {
                "tenant_id": tenant_id,
                "question_id": question_id,
                "explanation_text": explanation,
                "simplified_text": simplified,
                "hints": hints,
                "model_used": model,
            }
        ).execute()
    except Exception:  # noqa: BLE001 — cache write is non-critical
        pass

    return {
        "explanation": explanation,
        "simplified": simplified,
        "hints": hints,
        "cached": False,
    }
