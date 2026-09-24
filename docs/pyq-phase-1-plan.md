# PYQ (Phase 1 of the PYQ / MTP / RTP program) - engineering plan

**Status:** design for sign-off. No code until approved.

**Program shape:** Phase 1 = **PYQ** (this doc). Phase 2 = **MTP + RTP** (similar, single phase, later). This phase makes *Previous Year Questions* a first-class, production-grade product surface built on the existing quiz **extraction** flow.

## 0. Confirmed product decisions (from the TL)

1. **Scope:** a student sees PYQ only for the subjects they are enrolled in (same scoping as normal quizzes).
2. **Storage:** each PYQ is a **frozen snapshot** taken at publish time (permanent, historical, independent of the quiz's later life).
3. **Duplicates:** the same PYQ appearing in two uploads is **de-duplicated** (one copy in the student pool).
4. **Student mode:** PYQ is taken as a **full quiz with a scorecard**, reusing the existing quiz-taking engine (answer one by one -> auto-graded -> scorecard -> see correct answers/explanations).
5. **Layout:** in the PYQ tab the student picks a **subject**, then sees the previous-year papers **grouped by exam + year** (e.g. "CA Foundation 2019"), each a takeable quiz. (An "All PYQ" option per subject may be added.)

## 1. Goal & the non-breaking guarantee

Turn PYQ from a lossy placeholder into a real product: detect PYQ robustly during extraction (year, exam, and *where* it is marked), store it in dedicated columns + a growing PYQ library, mark it through review/publish, and give students a dedicated PYQ practice surface that grows with every upload.

**Guarantee:** everything is additive and gated behind `PYQ_ENABLED` (default **off**). With the flag off, extraction, storage, review, publish, and the student dashboard are **byte-for-byte what they are today** (including the existing `is_pyq`/explanation-prefix behaviour). PYQ only adds behaviour when switched on.

## 2. What already exists (we extend, not rebuild)

- Extraction AI already emits `is_pyq` + `year` per question (`extraction_prompts.py`), carried on `ExtractedQuestion` (`quiz_extraction.py:61`).
- It is a **v1 placeholder**: `_prefix_pyq()` embeds `[PYQ <year>]` into the explanation string - explicitly *"no dedicated columns yet"*. Lossy, no exam, not queryable, no student surface.
- No `pyq` columns or table exist; an unused deterministic `pyq_parser.py` exists but is not wired in.

## 3. Data model (migration-60, additive)

### 3a. PYQ metadata on `questions` (nullable, default off)
- `is_pyq boolean not null default false`
- `pyq_year text` (e.g. "2019", "May 2022")
- `pyq_exam text` (e.g. "CA Foundation Paper 1")
- `pyq_source_note text` (evidence: where/how the marker was found - for teacher trust + audit)

These make draft -> review -> publish PYQ-aware and teacher-editable, and retire the explanation-prefix hack (only when the flag is on).

### 3b. `pyq_questions` table - the student-facing PYQ library
Populated at **publish** by snapshotting each **approved** `is_pyq` question.

| Column | Purpose |
| --- | --- |
| `id`, `tenant_id` | identity + isolation |
| `pyq_year`, `pyq_exam` | filters shown to students |
| `type, question_text, options, correct_answer, explanation, marks` | **frozen snapshot** of the content |
| `subject_id`, `course_id`, `course_level_id` | subject-scoped student delivery |
| `origin_question_id`, `source_quiz_set_id`, `source_document_id` | lineage / repair |
| `content_hash` | **dedup** key (with tenant + year + exam) |
| `created_by`, `created_at` | audit |

- **Unique** `(tenant_id, content_hash, coalesce(pyq_year,''), coalesce(pyq_exam,''))` -> dedup.
- Indexes: `tenant_id`, `subject_id`, `(pyq_exam, pyq_year)`.
- RLS: staff manage within tenant; students read their tenant's PYQ (subject filter applied in the API, mirroring the quiz-list path). Backend writes via service role.
- FKs scoped through the course->level->subject hierarchy (mirrors migration-56 paper_profiles pattern).

## 4. PYQ detection (the AI analysis)

Extraction is **chunked**, so a marker on page 1 will not reach questions extracted from page 8 in another chunk. Detection therefore has **two tiers**:

1. **Document-level PYQ context pass** - one lightweight call over the whole document's markers (headings, first/last pages, "PYP 2019 CA Foundation" banners). Returns `{default_exam, default_year, section_markers[], all_questions_have_answers}`. Threaded into every extraction chunk so attribution is consistent across the whole paper.
2. **Per-question inline detection** - extend the existing extraction prompt to also emit `pyq_exam` + `pyq_source_note`. An inline marker **overrides** the document default; otherwise the document/section default applies.
3. **Answer/option completeness** - computed deterministically after extraction (which PYQ lack a valid answer/options) and summarised for the teacher in the existing `import_summary`.

All three run only when `PYQ_ENABLED` is on; off = today's single-tier behaviour.

## 5. End-to-end flow

Teacher uploads MCQ doc -> extraction + PYQ context -> draft quiz_set with **PYQ badges** (year, exam) on the relevant questions -> teacher reviews/corrects the tags -> **publish**: all questions go to the quiz_set (as today) **and** each approved PYQ is snapshotted into `pyq_questions` (deduped; answerless ones excluded + flagged) -> **student "PYQ" tab** reads the live pool, subject-scoped, and the student practices it. The pool grows automatically with every publish (no manual sync).

**Lifecycle edges (handled):** re-publishing/editing a PYQ **upserts** its snapshot (by `origin_question_id`); rejecting a question removes it from the pool; archiving the source quiz does **not** remove the PYQ (a PYQ is historical). Answerless PYQ never enter the student pool.

## 6. Sub-phases (build + self-verify each; flag-gated)

- **PYQ-A - Data model & flag.** migration-60 (columns + `pyq_questions` + RLS + indexes) + `PYQ_ENABLED` (default off) + deployment_check probes. Behaviour-neutral.
- **PYQ-B - Detection.** Document-level context pass + exam detection + persist real PYQ columns (replace the explanation hack when on). Extraction byte-identical when off.
- **PYQ-C - Review & publish.** PYQ badges + editable year/exam in the teacher review card; publish-time snapshot into `pyq_questions` (dedup + completeness gate + upsert-by-origin).
- **PYQ-D - Student PYQ surface.** New "PYQ" nav item + page. Flow: pick **subject** (only enrolled subjects) -> see previous-year papers **grouped by exam + year**, each a takeable quiz -> **take it like a normal quiz** (one by one) -> **scorecard** + correct answers, reusing the existing quiz-taking + grading engine. New API: `GET /api/v1/pyq/subjects` (enrolled subjects + PYQ counts), `GET /api/v1/pyq/papers?subject_id=` (papers grouped by exam+year), and a take/start + submit path that reuses the attempt/scoring flow over PYQ snapshots.
- **PYQ-E - Tests + polish.** Full matrix + regression.

## 7. Test matrix (gates each increment)

- **A:** additive schema; flag-off is behaviour-neutral; deployment probes pass.
- **B:** inline / section / document / last-page markers each attribute year+exam to the right questions; exam detected; completeness computed; **flag off -> extraction byte-identical** (snapshot test on the prompt + no PYQ writes).
- **C:** approved PYQ snapshot into the pool; dedup across two uploads; answerless PYQ excluded + flagged; edit -> upsert; reject -> removed.
- **D:** a student sees only their subjects' PYQ; filter by year/exam; practice auto-grades; no cross-tenant / cross-subject leakage (access tests).
- **Regression:** full extraction + student suites green with the flag off.

## 8. Risks & mitigations

- **Cross-chunk markers (main technical risk).** -> Document-level context pass provides year/exam to every chunk; per-question inline overrides. Tested with markers in each position.
- **AI mis-tags PYQ.** -> Teacher review is the gate; `pyq_source_note` shows the evidence; nothing enters the student pool without teacher approval.
- **Library bloat / duplicates.** -> content-hash dedup + unique constraint.
- **Touching extraction (proven pipeline).** -> Flag-gated; off is byte-identical; snapshot tests prove the default prompt/flow unchanged.
- **Answerless PYQ shown to students.** -> Completeness gate excludes them from the pool.

## 9. Minor decisions taken as defaults (say if you disagree)

- **Year/exam are free text** (AI-detected, teacher-editable). Later we can optionally link `pyq_exam` to the P6.3 paper-profiles taxonomy.
- **Extraction-only** (not normal AI generation) - PYQ comes from uploaded real papers.
- **PYQ practice attempts** are recorded like other practice (history/analytics), scoped as PYQ.
- **Flag name:** `PYQ_ENABLED` (default off).

## 10. Decision before PYQ-A

Confirm the sequence **A -> B -> C -> D -> E** and the data model in section 3. On approval I start with **PYQ-A** (migration + flag, behaviour-neutral), plan -> build -> self-verify, with the matrix gating it.
