# P6.2 — Scoring Policy Engine (phase 3 of 8): design for approval

**Status:** design for sign-off. No code until approved. This is the most correctness-critical refactor in the program (it touches the score of every attempt), so it is built to be **zero-regression by construction**.

## 1. Goal & the zero-regression guarantee

Replace today's two divergent, hard-coded graders with **one policy-driven scoring engine**, so a paper can score the way its real exam does (negative marking, partial credit, unit-aware numerics) — without changing any existing score.

The guarantee: the engine's **default policy reproduces today's behavior exactly**, because for the default policy the engine **delegates correctness to the existing `grade_answer`** (proven code) and only computes marks. So:
- A quiz with no policy → default → **byte-identical to today**.
- Practice keeps its current exam/daily negative marking (expressed as a policy).
- Richer per-paper policies are gated by `SCORING_POLICIES_ENABLED` and only apply to a quiz that has one attached.

## 2. Current state (verified)

| Path | Today | File |
| --- | --- | --- |
| Quiz submit | `grade_answer` → **full marks or 0**; total = Σ awarded; never negative | `student.py:758`, `grading.py` |
| Practice submit | `grade_answer`, then exam/daily applies **flat −neg** for wrong+answered, blank = 0, **total clamped ≥ 0** | `practice.py:440-480` |
| Types | mcq_single/true_false (string eq), mcq_multi (all-or-nothing), numerical (`|Δ| ≤ tolerance`), fill_blank (normalized), descriptive (always 0) | `grading.py` |
| Immutability | question content snapshotted at attempt start; **no scoring-policy snapshot** | `student.py`, `practice.py` |

## 3. The scoring policy model

A policy is a small, versioned, tenant-scoped JSON contract:

```
ScoringPolicy = {
  wrong_penalty:        number  (≥0)   # marks lost per wrong answer; default 0
  penalty_is_fraction:  bool            # true → penalty = wrong_penalty × question marks; default false
  omission_score:       number          # marks for a blank answer; default 0
  multi_mode:           "all_or_nothing" | "mrm_partial"   # mcq_multi; default all_or_nothing
  clamp_negative_total: bool            # floor the attempt total at 0; default true
  numeric:              NumericContract | null   # §5; default null (current tolerance behavior)
}
```

Worked examples:

| Policy | wrong_penalty | multi_mode | clamp | Result |
| --- | --- | --- | --- | --- |
| **Default** (all existing quizzes) | 0 | all_or_nothing | true | correct=marks, wrong=0, blank=0 → **identical to today** |
| **Practice-exam** (today, as a policy) | neg (abs) | all_or_nothing | true | reproduces current practice negative marking |
| **CA Foundation P3/P4** | 0.25 | all_or_nothing | true | −0.25 per wrong; blank 0 |
| **ACCA (MRM)** | 0 | mrm_partial | true | partial credit on multi-response |

## 4. The grade-contract change

```
score(question, student_answer, policy) -> Outcome
Outcome = { state: correct | wrong | blank | partial | needs_manual, awarded: Decimal }
```

Logic (safe by delegation):
- `descriptive` → `needs_manual`, 0 (never silently 0 in the total; routed to manual grading later).
- blank → `blank`, `policy.omission_score` (0 by default).
- `mcq_multi` + `mrm_partial` → per-selection partial: `awarded = marks × max(0, correct_chosen − wrong_chosen) / n_correct` (ACCA-style, floored at 0); state = correct/partial/wrong.
- otherwise → **call the existing `grade_answer`** for correctness; correct → `marks`; wrong+answered → `−(wrong_penalty × marks if fraction else wrong_penalty)`.

Attempt total = Σ awarded, floored at 0 iff `policy.clamp_negative_total`. Back-compat: `is_correct = state==correct`, `marks_awarded = awarded` — the existing `attempt_answers`/`total_score` columns are unchanged.

## 5. Numeric unit / currency / rounding contract (commerce numerics)

Extend `numerical` grading (opt-in via the question or policy `numeric`):
```
NumericContract = { unit?, currency_scale? (absolute|thousand|lakh|crore), rounding? (none|nearest|floor|ceil), decimals?, tolerance }
```
Grading uses **Decimal** arithmetic: normalize the student value and the expected value to a canonical scale, apply the declared rounding, then compare within tolerance. So "2.5 lakh" == 250000 only when the contract permits, "12%" ≠ 0.12 unless the unit says so, non-finite inputs are rejected, and unsupported cases fall back to the **current tolerance behavior** (no contract = today). Never executes model-produced code.

## 6. Data model & flag (additive)

| Change | Purpose |
| --- | --- |
| `scoring_policies` (id, tenant_id, name, rules jsonb, created_by, created_at) | named, reusable policies; immutable once attached |
| `quiz_sets.scoring_policy_id` uuid null → scoring_policies (on delete set null) | a quiz's scoring rules; **null = default full/zero** |
| `quiz_attempts.scoring_policy_snapshot` jsonb | policy frozen at attempt start (immutability) |
| `practice_sessions` | reuse existing `config`/snapshot to carry the resolved policy |
| config `SCORING_POLICIES_ENABLED` (default false) | when off, attached policies are ignored → everything default/current |

## 7. Resolution & snapshot flow

At **attempt/session start**: resolve policy = (flag on AND quiz has `scoring_policy_id` → that policy) else (practice-exam → the existing config negative-marking policy) else **default**. **Snapshot** the resolved policy onto the attempt. Grading reads the **snapshot**, so changing a policy never alters a past attempt.

## 8. Enforcement points (where scoring happens)

1. **Quiz submit** (`student.py`) — replace the `grade_answer` loop with `score(…, attempt.policy_snapshot)`.
2. **Practice submit** (`practice.py`) — replace the manual grade+negative loop with `score(…, session.policy_snapshot)`; the current exam/daily behavior becomes the practice-exam policy.
3. **Challenge** — runs through practice, so covered.

## 9. Increment breakdown

| # | Deliverable | Exit gate |
| --- | --- | --- |
| **P6.2-1** | Migration (policies table + quiz link + attempt snapshot) + `SCORING_POLICIES_ENABLED` | Additive; behavior-neutral (flag off, no policies attached). |
| **P6.2-2** | `scoring.py`: policy model + `score()` (delegates default to `grade_answer`) + default policy | Unit tests: **default == `grade_answer` for every type**; negative; MRM partial; blank vs wrong. |
| **P6.2-3** | Resolve + snapshot policy at attempt/session start; wire quiz + practice submit | Full regression green (existing scores byte-identical); practice-exam negative marking preserved; policy snapshot immutable. |
| **P6.2-4** | Numeric unit/currency/rounding contract | ₹/lakh/crore, rounding-boundary, %-vs-fraction, non-finite fixtures pass; no-contract == today. |
| **P6.2-5** | Frontend: create a policy + attach to a quiz (admin/faculty) | Teacher attaches CA-Foundation policy; a mock scores with negative marking end-to-end. |

Core = 1–3 (+4 for commerce numerics). 5 is the UI, can follow.

## 10. Test matrix (gates rollout)

- **Regression:** default policy == `grade_answer` for mcq_single/multi/true_false/numerical/fill_blank; full quiz + practice submit unchanged with flag off.
- **Negative marking:** CA-Foundation −0.25 (wrong+answered = −0.25, blank = 0, correct = marks, total clamped).
- **Partial:** ACCA MRM multi-response awards partial, floored at 0.
- **Numeric:** currency scale, rounding boundaries, %/fraction, zero-denominator, non-finite → rejected.
- **Immutability:** change a policy after an attempt → the attempt's score is unchanged (snapshot).
- **Flag off:** a quiz with an attached policy still scores default.
- **Descriptive:** `needs_manual`, never silently 0 in a way that misreports.

## 11. Risks & mitigations

- **Most correctness-critical file.** → Default path **delegates to the proven `grade_answer`** (zero logic change for the default); exhaustive regression; `SCORING_POLICIES_ENABLED` gates non-default policies.
- **Practice behavior drift.** → Practice-exam negative marking reproduced exactly as a policy; regression-tested.
- **Manual migration.** → Additive/nullable; `deployment_check` gains probes.

## 12. Decisions I need before P6.2-1

1. **First policy to build + test** — recommend **CA Foundation P3/P4 (−0.25)** (it's the main negative-marking commerce case), with **ACCA MRM** as the partial-credit case. OK?
2. **Policy attaches at the quiz level** (`quiz_sets.scoring_policy_id`) for P6.2 — a per-batch/assignment policy can come later. OK?
3. **Confirm the defaults:** existing quizzes stay full/zero; practice keeps its current exam/daily negative marking. (This is the plan; just confirming.)

On approval + answers, I start with **P6.2-1** (additive schema + flag), then the engine (2), wiring (3), numerics (4) — each behind the flag and gated by the regression matrix.
