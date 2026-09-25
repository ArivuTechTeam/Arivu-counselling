# Knowledge Base: PYQ / MTP / RTP papers - engineering plan

**Status:** design for sign-off. No code until approved. Supersedes the student-side
model of the earlier PYQ Phase 1 plan and generalises it to three paper types.

## 0. Confirmed decisions (from the TL)

1. **One generalised table.** PYQ, MTP, RTP share a single `paper_questions` bank
   with a `paper_type` column. (Evolves the `pyq_questions` table already built.)
2. **Teacher yes/no gate on extraction.** After a teacher uploads an MCQ/paper
   document (extraction engine), BEFORE generating, ask: *"Does this document
   contain PYQ / MTP / RTP questions?"* Yes -> AI analyses & classifies the paper;
   No -> normal extraction, byte-identical to today.
3. **Descriptive is graded by AI semantic comparison.** The document supplies the
   model answer; the AI stores a concise **answer summary**. When a student answers
   a descriptive question, the AI summarises the student's answer and compares it to
   the stored model summary; **>= 90% match -> full marks, else 0**. This applies
   ONLY inside PYQ/MTP/RTP; general quizzes still skip descriptive.
4. **Student feature "Mock Test & PYQ":** three options (PYQ / MTP / RTP); pick
   subject -> chapter -> question type -> number of questions; the system pulls a
   RANDOM matching set from the bank; take one-by-one -> scorecard. Teacher logs are
   deferred.

## 1. Goal & the non-breaking guarantee

Build a **knowledge base of classified exam questions** (PYQ / MTP / RTP), fed by the
existing extraction engine, and a student practice surface that draws random,
filtered sets from it - with descriptive questions graded by AI.

**Guarantee:** additive and gated behind `PAPER_BANK_ENABLED` (default off) PLUS the
per-upload teacher yes/no. With the flag off - or the teacher answering "No" -
extraction, review, publish, generation and the student dashboard are **byte-for-byte
what they are today**. General MCQ generation and quizzes are never touched.

## 2. Relationship to PYQ Phase 1 (evolve, don't rebuild)

| PYQ Phase 1 (built) | Generalised here |
| --- | --- |
| `pyq_questions` table | `paper_questions` (+ `paper_type`, `chapter_id`, descriptive fields) |
| PYQ detection pass | classification of PYQ/MTP/RTP, gated by the teacher yes/no |
| snapshot PYQ at publish | snapshot any classified question by `paper_type` |
| student PYQ tab (papers by year) | "Mock Test & PYQ": 3 types -> filters -> random set |

The detection pass, snapshot-at-publish, and take+scorecard code are reused; the
student UI model changes from "papers by year" to "filtered random set".

## 3. Data model (migration set)

### 3a. `paper_questions` - the knowledge base (generalise `pyq_questions`)
- `id`, `tenant_id`
- `paper_type` text check in ('pyq','mtp','rtp')
- `subject_id`, `chapter_id`  (student filters)
- `exam`, `year`  (metadata, shown per question)
- `type` (question_type incl. `descriptive`), `question_text`, `options`,
  `correct_answer`, `explanation`, `marks`
- `model_answer` text  (descriptive: the suggested answer from the document)
- `answer_summary` text  (descriptive: AI-condensed key points, used for grading)
- `content_hash` (dedup), `origin_question_id`, `source_quiz_set_id`, `source_document_id`
- `created_by`, `created_at`; RLS mirrors the current pyq policy.
- Unique `(tenant_id, paper_type, content_hash, coalesce(year,''), coalesce(exam,''))`.
- Indexes: `(tenant_id, paper_type, subject_id, chapter_id, type)` for the random pull.

### 3b. Question columns (evolve the PYQ columns on `questions`)
- `paper_type text`, `paper_year text`, `paper_exam text`, `paper_source_note text`
- `model_answer text`, `answer_summary text` (descriptive)
- (`is_pyq` from Phase 1 is subsumed by `paper_type is not null`.)

### 3c. Document classification (the "knowledge base" of documents)
- `documents` already stores every upload with `chapter_id`. Add
  `contains_papers jsonb` = `{pyq:bool, mtp:bool, rtp:bool}` (what the analysis found)
  and reuse it to power the **"use a previous document"** picker.

## 4. Extraction engine changes

1. **Two entry choices** in the Import UI: **upload new** OR **use a previous
   document** (lists the teacher's earlier uploads for the subject/chapter; re-extract
   from storage, no re-upload).
2. **Teacher yes/no gate** (before generate): *"Does this document contain PYQ / MTP /
   RTP questions?"* The extraction request carries `analyze_papers: bool`.
3. **When yes (and flag on):** run the **paper-analysis** path:
   - classify each question's `paper_type` (pyq/mtp/rtp) + year/exam, using the
     document-level context pass (labels/banners/footers) generalised from PYQ-B;
   - **also extract descriptive & numerical** questions (today's extractor skips
     descriptive) with their **model answer**;
   - for each descriptive question, generate a concise `answer_summary`.
4. **When no (or flag off):** exactly today's extraction (MCQ-only, no classification,
   no descriptive) - byte-identical.

## 5. Descriptive AI grading (the novel piece)

- **At extraction** (paper mode): store `model_answer` + AI `answer_summary` per
  descriptive question. A descriptive question WITHOUT a model answer fails the
  completeness gate and never enters the bank (can't be graded).
- **At student submit:** collect all descriptive answers of the attempt and grade them
  in a **single batched AI call** (an LLM judge): for each, compare the student's
  answer to the stored `answer_summary` and return a coverage score 0-100.
  **>= 90 -> full marks, else 0.** Objective questions (MCQ/TF/numerical/fill-blank)
  are graded deterministically as today. The scorecard combines both.
- **Resilience:** if the judge call fails, descriptive questions are marked
  "pending" (0 for now) with a clear note rather than failing the whole scorecard.
- **Cost/latency:** one batched judge call per attempt (not per question). Noted.

## 6. Review

Each question shows a **paper badge** (`PYQ`/`MTP`/`RTP` . year . exam). Descriptive
questions show their model answer. Teacher can approve/reject as today.

## 7. Publish -> snapshot

At publish, each approved classified question is frozen into `paper_questions`
(subject+chapter scoped, deduped, completeness-gated, upsert-by-source-quiz), tagged
with its `paper_type`. Same engine as PYQ-C, now type-aware.

## 8. Student "Mock Test & PYQ"

- Nav item -> three tabs: **PYQ / MTP / RTP**.
- Config: **subject** (enrolled) -> **chapter** -> **question type** -> **number of
  questions**. The UI shows how many are available so a thin bank is obvious.
- Backend: `GET /api/v1/papers/options` (subjects/chapters/types with counts) and a
  start/submit pair that **randomly** selects `count` questions of the chosen
  `paper_type` + subject + chapter + type from the bank.
- Take one-by-one -> **scorecard** (objective auto-graded + descriptive AI-graded).

## 9. Phases (each flag-gated, self-verified)

- **KB-A** - data model: `paper_questions` (generalise) + question columns +
  document classification + `PAPER_BANK_ENABLED` + probes. Behaviour-neutral.
- **KB-B** - extraction: teacher yes/no gate, PYQ/MTP/RTP classification, descriptive
  extraction + `answer_summary`, "use a previous document" picker. Byte-identical when
  the teacher says No / flag off.
- **KB-C** - review badges (3 types) + publish snapshot into the typed bank.
- **KB-D** - student "Mock Test & PYQ": filters -> random pull -> take -> scorecard,
  with the batched descriptive AI grader.
- **KB-E** - tests + full regression. (Teacher logs deferred.)

## 10. Risks & mitigations

- **Descriptive AI grading accuracy / cost.** -> single batched judge per attempt;
  90% threshold; graceful "pending" on failure; only inside the paper bank.
- **Descriptive extraction (new capability).** -> only on the paper path (teacher
  said Yes); general extraction/generation untouched; completeness gate drops
  answerless descriptive.
- **Misclassification of type.** -> teacher yes/no gate scopes the AI; review is the
  gate; per-question `paper_source_note` shows the evidence.
- **Thin bank -> tiny random quiz.** -> counts surfaced in the UI; cap request to
  what's available.
- **Touching the proven extractor.** -> the whole paper path is behind the flag + the
  teacher's "No"; snapshot tests prove the default prompt/flow are unchanged.

## 11. Naming

`PYQ_ENABLED` (Phase 1) is renamed to **`PAPER_BANK_ENABLED`** (umbrella for
PYQ/MTP/RTP). The Phase-1 `pyq_questions` table/columns are migrated into the
generalised `paper_questions` model in KB-A.

## 12. Decision before KB-A

Confirm the phase sequence **A -> B -> C -> D -> E** and the data model in section 3.
On approval I start with **KB-A** (generalise the schema + flag, behaviour-neutral).
