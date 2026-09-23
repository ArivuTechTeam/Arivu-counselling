"""Official exam-scoring presets (Phase 6.2-5).

The negative-marking / partial-credit rule of each exam body is universal (a CA
Foundation objective paper is −0.25 everywhere), so we ship them as named presets
an admin picks per course — instead of anyone typing raw JSON. Each preset maps to
the scoring-engine `rules` (see app/services/scoring.py). `preset_key` is stored
inside the created policy's rules so the admin UI can show the current selection.
"""

from __future__ import annotations

# key -> {name, description, rules}. Rules use the scoring engine's fields;
# an empty rules object means the default full-marks / zero (no negative marking).
SCORING_PRESETS: dict[str, dict] = {
    "standard": {
        "name": "Standard — full marks / zero (no negative)",
        "description": "Right = full marks, wrong = 0. The default for practice quizzes.",
        "rules": {},
    },
    "ca_foundation": {
        "name": "CA Foundation — 0.25 negative marking",
        "description": "ICAI CA Foundation objective papers: −0.25 per wrong answer; blank = 0.",
        "rules": {"wrong_penalty": 0.25, "clamp_negative_total": True},
    },
    "cma_india": {
        "name": "CMA India — no negative marking",
        "description": "ICMAI CMA: no deduction for wrong answers.",
        "rules": {},
    },
    "cs_india": {
        "name": "CS (ICSI) — no negative marking",
        "description": "ICSI CS objective questions: no deduction.",
        "rules": {},
    },
    "acca": {
        "name": "ACCA — partial credit, no negative",
        "description": "ACCA: no negative marking; multiple-response questions award partial marks.",
        "rules": {"multi_mode": "mrm_partial"},
    },
    "cma_us": {
        "name": "CMA US (IMA) — no negative marking",
        "description": "IMA CMA-US MCQ section: no deduction (0–500 scaling is separate).",
        "rules": {},
    },
}


def preset_rules(key: str) -> dict | None:
    """The engine rules for a preset, tagged with preset_key for round-tripping."""
    preset = SCORING_PRESETS.get(key)
    if preset is None:
        return None
    return {**preset["rules"], "preset_key": key}
