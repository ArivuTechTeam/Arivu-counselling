# Exam-simulator & mock-test scoring standards — research (for approval)

**Purpose:** the quiz generator's generic scoring (P6.2 policy engine) is right for practice quizzes, but **mock tests / the exam simulator must reproduce each body's *official* marking scheme**. This is the researched standard for ICAI (CA), ICMAI (CMA-India), ICSI (CS), ACCA, and IMA (CMA-US), plus what the engine needs beyond per-question scoring.

**Caveat:** these are researched from exam-body and coaching sources current in 2026; the exact per-paper rules must be **faculty-confirmed before an official-pattern mock is enabled** (rules change by syllabus/session). Sources are linked per section.

## 1. Official standards by body

### ICAI — Chartered Accountancy (CA)
| Level | Structure | Objective portion | Negative marking | Pass criteria |
| --- | --- | --- | --- | --- |
| **Foundation** | 4 papers × 100 = 400; P1 Accounting & P2 Business Laws subjective (3h); **P3 Quant Apt & P4 Business Economics objective MCQ (2h)** | 100% MCQ in P3/P4 | **−0.25 per wrong (P3/P4 only)** | **40% each paper + 50% aggregate** |
| **Intermediate** | 6 papers, 2 groups × 3; each 100 marks, 3h | **30 marks MCQ + 70 marks descriptive** per paper | **None** | 40% each paper + 50% aggregate **per group** |
| **Final** | 6 papers, 2 groups × 3; 100 marks, 3h | 30 MCQ + 70 descriptive | **None** | 40% each paper + 50% aggregate per group |

Sources: [ICAI CA pattern](https://www.arivupro.com/blogs/ca/icai-ca-exam-pattern), [CA Foundation](https://www.pw.live/ca/exams/ca-foundation-exam-pattern), [CA Inter/Final](https://www.pw.live/ca/exams/ca-exam-pattern).

### ICMAI — Cost & Management Accountancy (CMA India)
| Level | Structure | Objective | Negative | Pass |
| --- | --- | --- | --- | --- |
| **Foundation** | 4 papers × 100 = 400; **50 MCQ × 2 marks per paper** | 100% MCQ | **None** | 40% each + 50% aggregate |
| **Intermediate** | 2 groups; 100 marks/paper | **30% MCQ + 70% descriptive** | **None** | 40% each + 50% aggregate per group |
| **Final** | 8 papers × 100 = 800; objective + descriptive | mixed | **None** | 40% each + 50% aggregate per group |

Sources: [CMA Foundation](https://zeroinfy.in/blogs/cablogs/cma-foundation-exam-pattern), [CMA pattern & passing](https://rohansharma4787.graphy.com/blog/cma-exam-pattern-passing-marks-explained).

### ICSI — Company Secretary (CS)
- Executive/Professional: **~20% case-based objective + 80% descriptive** (one paper 100% descriptive); 100 marks, 3h.
- **Pass: 40% each paper + 50% aggregate per module.** Objective portion is case-based MCQ; **no negative marking** in current pattern.
Source: [ICSI CS pattern](https://www.pw.live/cs/exams/icsi-cs-exam-pattern), [CS Executive pattern](https://www.careers360.com/commerce/articles/cs-executive-exam-pattern).

### ACCA
- 13 exams, 3 levels. **Pass mark = 50% for every paper. No negative marking at any level.**
- **Applied Knowledge** (BT, MA, FA): 100% Objective Test (OT), computer-marked, **2 marks each, no partial**; 2h CBE.
- **Applied Skills**: sectioned — e.g. Corporate & Business Law: *Section A* 25 OTQ×2 + 5 MTQ×6, *Section B* 20 OTQ×1; other Skills papers add **Constructed Response** (long-form, human-marked). **MTQ / multiple-response can award partial marks; single OTQ is all-or-nothing.** **Number-entry** questions specify unit + rounding.
- **Strategic Professional**: constructed-response, includes **professional marks**; human-marked.
Sources: [ACCA structure](https://www.accaglobal.com/gb/en/student/getting-started/acca-qualification-structure.html), [ACCA marking facts](https://www.zelleducation.com/blog/is-there-negative-marking-in-acca-exams/), [OT questions](https://www.accaglobal.com/gb/en/student/sa/study-skills/objective-questions.html).

### IMA — CMA (US)
- Part 1 & Part 2: each **100 MCQ + 2 essays**; 4h (3h MCQ + 1h essays).
- **MCQ = 75% of score, essays = 25%.** **Scaled score 0–500; pass = 360 (~72%).** **No negative marking.**
- **Gating:** must score **≥ 50% on the MCQ section to reach the essay section**; MCQ auto-graded, **essays human-graded**.
Sources: [CMA-US structure & scoring](https://globalfinx.in/cma-us/blog/cma-us-exam-structure-understanding-parts-marks-and-passing-scores-2026-edition), [CMA grading](https://www.cmacoach.com/cma-exam-graded/).

## 2. What this means for the engine — beyond per-question scoring

The P6.2 policy engine (negative marking / partial / numeric) covers **per-question** scoring. Official mocks add **exam-level** requirements:

| Capability | Needed by | In P6.2 policy? |
| --- | --- | --- |
| Negative marking (−0.25) | CA Foundation P3/P4 | ✅ yes |
| Partial credit (MTQ/MRM) | ACCA | ✅ yes |
| Number-entry: unit + rounding + tolerance | ACCA, CMA-US, commerce numerics | ✅ yes (numeric contract) |
| **Section-weighted scoring** (MCQ 75% + essay 25%) | CMA-US; CA/CMA 30+70 | ➕ new: exam sections + weights |
| **Scaled score** (raw → 0–500) | CMA-US | ➕ new: score scaling |
| **Pass evaluation** (per-paper min % + aggregate %; 50%; 360/500; group-wise) | all | ➕ new: pass rules |
| **Exam blueprint** (sections, Q counts, marks/Q, duration) | all mocks | ➕ new: paper template |
| **Manual grading** of descriptive/essay | CA/CMA Inter+Final, CS, ACCA Skills+, CMA-US essays | ➕ new: manual queue; auto-score objective, hold descriptive |
| **MCQ gate** (≥50% MCQ to reach essays) | CMA-US | ➕ new (edge) |

## 3. Proposed model: an "Exam Paper Standard" layered on the policy engine

Keep the P6.2 scoring policy as the **per-question** layer. Add an **Exam Paper Standard** (the official pattern of one paper) as the **exam-level** layer, used only by the **exam simulator / mock** mode — not by ordinary quizzes:

```
ExamPaperStandard = {
  body/level/paper,                     # e.g. ICAI/Foundation/Paper 3
  duration_minutes,
  sections: [ { name, question_type, count, marks_each, scoring_policy } ],  # blueprint + per-section policy
  aggregation: "sum" | "weighted" | "scaled",
  weights?: { section -> weight },      # CMA-US MCQ 0.75 / essay 0.25
  scale?: { raw_max, scaled_max: 500, scaled_pass: 360 },   # CMA-US
  pass: { per_paper_min_pct, aggregate_min_pct, group? },   # CA/CMA 40/50; ACCA 50
  manual_sections: [ ... ],             # descriptive/essay → manual grading
}
```

- **Objective sections** auto-score via the P6.2 policy (negative/partial/numeric).
- **Descriptive/essay sections** are routed to **manual grading**; the result reports the auto objective score + "essay pending", then a combined score once graded (respecting weights/scaling).
- **Pass/fail** is computed from the standard's pass rule (and grouping for CA/CMA).

## 4. Recommended v1 scope (for the mocks that can be *fully* auto-scored now)

Fully auto-scorable end-to-end (objective-only, deterministic):
- **CA Foundation P3 & P4** (MCQ, −0.25, 40/50 pass).
- **CMA-India Foundation** (50 MCQ × 2, no negative, 40/50).
- **ACCA Applied Knowledge** (BT/MA/FA — OT, 50% pass, MRM partial).
- **CMA-US Part 1/2 MCQ section** (scaled contribution; essays manual).

Mixed papers (CA/CMA Inter+Final, CS, ACCA Skills+): auto-score the objective section now, route descriptive/essay to **manual grading** (a later increment), and present the combined result. This lets us ship real mocks for the objective-heavy papers immediately while descriptive grading follows.

## 5. How this changes the P6.2 plan

P6.2 stays the per-question **scoring policy engine** (unchanged proposal). We **add** an **Exam Paper Standard** layer (blueprint + section weights + scaling + pass rule + manual routing) used only by exam-simulator/mock mode. Suggested sequencing:
- **P6.2 (as planned):** per-question scoring policy (negative/partial/numeric) + zero-regression default. *(Quizzes + the objective scoring mocks need.)*
- **P6.2-EX (new):** Exam Paper Standard — sections, weighted/scaled aggregation, pass evaluation, manual routing for descriptive — instantiated per official paper, faculty-confirmed.

## 6. Decisions I need before coding

1. **v1 mock papers** — start with the fully auto-scorable set in §4 (CA Foundation P3/P4, CMA-India Foundation, ACCA Applied Knowledge, CMA-US MCQ)? Which one **first**?
2. **Descriptive/essay grading** — confirm it's **manual** for v1 (auto-score objective, route essays to a manual queue), not auto-graded.
3. **Scaled scoring (CMA-US 0–500)** — include the scale conversion in v1, or start with raw %/marks and add scaling when CMA-US mocks go live?
4. **Faculty confirmation** — agree each official standard is faculty-signed-off before its mock is enabled (rules change by session).

On approval + answers, I'll fold this into the P6.2 plan (per-question policy) plus a **P6.2-EX Exam Paper Standard** increment, and start coding.
