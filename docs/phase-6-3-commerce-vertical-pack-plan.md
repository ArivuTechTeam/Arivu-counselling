# P6.3 — Commerce Vertical Pack (phase 4 of 8): design for approval

**Status:** design for sign-off. No code until approved. This phase makes the AI *commerce-aware* — its highest-value, most defensible feature — while treating the working generation pipeline as sacred: everything is additive, flag-gated (`COMMERCE_PACK_ENABLED`), and generation is unchanged when off.

## 1. Goal & the non-breaking guarantee

Give generation/extraction commerce competence: **independently verify numerical answers**, carry **assessment-year/jurisdiction context**, and **preserve Indian number formats & tables**. The guarantee: with `COMMERCE_PACK_ENABLED` off, the generation prompt, extraction, and verification retain their previous behavior. The current switch is deployment-wide; the stored paper context itself is tenant- and course-level-scoped.

## 2. The four components (sequenced by risk — safest first)

| # | Component | Value | Risk | Touches |
| --- | --- | --- | --- | --- |
| **A** | **Numeric-check registry** — independently recompute a generated numerical's answer and flag wrong AI math | **Very high** (the "verified numericals" edge) | **Low** — additive verification step; never blocks generation | verification only |
| **B** | **Commerce context** — assessment-year / jurisdiction / framework in the prompt + on the question | High | Medium — adds to the generation prompt (flag-gated) | generation prompt |
| **C** | **Numeric & table extraction fidelity** — preserve numbers/currency/tables faithfully across ALL conventions: Indian (`₹1,00,000`, lakh/crore) AND international (ACCA `£1,000,000`, CMA-US `$1,000,000`). Never rejects or converts a format | High | Medium — extraction validation | extraction |
| **D** | **Paper-profile binding** — course → body/level/paper/AY (feeds B, and the exam standards from P6.2) | Medium | Low — additive data model | data model |

**Recommended order: A → C → D → B.** A is self-contained and safe (start here); B (prompt changes) comes last, after the safe pieces prove the pattern.

## 3. Component A in detail — the numeric-check registry (first increment)

**Principle (from the architecture doc):** *a numeric checker must recompute from independently parsed inputs — comparing the model's answer to its own explanation is not verification.* So the generator emits the **inputs**, and we recompute with tested code.

1. **Registry of tested calculators** — a bounded set of commerce families, each a pure, unit-tested function:
   - `simple_interest`, `compound_interest`, `straight_line_depreciation`, `break_even_units`, `percentage`, `ratio`. (Extended later from faculty fixtures — never a claim of universal accounting validation.)
2. **Generator emits an optional structured calc** for numerical questions (additive prompt field, flag-gated):
   `"calc": { "family": "simple_interest", "inputs": {"principal": 1000, "rate": 5, "time": 2} }`.
   If the flag is off or the family is unsupported, the field is simply absent — no prompt change.
3. **Verification recomputes** (`question_verification.verify_generated_questions`): for a numerical question with a `calc`, run `registry[family](inputs)` (Decimal) and compare to `correct_answer.value` within tolerance.
   - **Mismatch** → downgrade the question's `verification_status` to `needs_teacher_review` + warning `numeric_check_failed` (the teacher reviews it; it is never auto-published or auto-changed).
   - **No calc / unsupported family** → `not_checked` (no downgrade) — never a false "verified".
4. **Never executes model-produced code** — only the registry's own functions run, on validated numeric inputs (non-finite rejected).

This reuses the P6.2 numeric contract for the comparison, hooks into the existing verify pipeline, and is **purely additive**: with the flag off, no calc is emitted and verification is unchanged.

## 4. Components B/C/D (summary — detailed at their turn)

- **B — Commerce context:** relevant courses carry assessment-year / jurisdiction / accounting framework; the generation prompt includes them ("value under AY 2025-26, Indian GAAP"), and the question records the version so a later syllabus change never silently invalidates old questions. Flag-gated; no prompt change when off.
- **C — Numeric & table extraction fidelity:** during import, **preserve numbers, currency symbols, and tables exactly as written**, across BOTH conventions — Indian (`₹1,00,000`, lakh/crore, 2-digit grouping) and international (ACCA `£1,000,000`, CMA-US `$1,000,000`, 3-digit grouping). It validates that numeric data survives extraction (a misread `1,00,000 → 100` is caught) and **never rejects or converts** an international format. Additive validation; falls back to today's behavior when off.
- **D — Paper profiles:** a small `paper_profiles` table (course → body/level/paper/AY/framework), the single place B, C, and the P6.2 exam standards read commerce context from. Additive/nullable.

## 5. Test matrix (gates each increment)

- **A:** each calculator unit-tested (interest/depreciation/break-even/ratio, rounding, non-finite rejected); a generated numerical with a *wrong* answer is flagged `numeric_check_failed`; a *correct* one passes; no calc → `not_checked`; **flag off → verification byte-identical** (no calc emitted, no downgrades).
- **B:** prompt includes AY/jurisdiction only when a profile is set; flag off → prompt unchanged (snapshot test).
- **C:** `1,00,000`/₹/lakh/table fixtures preserved; flag off → extraction unchanged.
- **D:** additive schema; `deployment_check` probes; behavior-neutral.
- **Regression:** full generation + extraction suites green with the flag off.

## 6. Risks & mitigations

- **Touching generation (B).** → Flag-gated; the prompt addition is appended only when a profile exists; snapshot tests prove the default prompt is unchanged; B is sequenced **last**, after A/C/D prove the pattern.
- **Over-claiming numeric coverage (A).** → Only the bounded, tested families are checked; everything else is `not_checked`, never a false pass. The registry grows only from faculty-validated fixtures.
- **Extraction drift (C).** → Additive validation with fallback to current behavior; heavy fixtures.

## 7. Decisions before P6.3-A

1. **Confirm the sequence A → C → D → B** (safe-first), starting with the **numeric-check registry (A)**.
2. **First calculator families** — I propose **simple/compound interest, straight-line depreciation, break-even, percentage, ratio**. Add/remove any?
3. **Flag name** `COMMERCE_PACK_ENABLED` (default off) — OK, or fold under an existing flag?

On approval, I start with **P6.3-A** (numeric-check registry — additive, generation unchanged when off), plan → build → self-verify, with the matrix gating it.
