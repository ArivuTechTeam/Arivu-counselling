# Chunked quiz generation — BUILD PLAN (for approval)

**This is the plan to approve before any coding.** It finalises the decisions from
discussion and lays out exactly what will be built, in what order.

**Companion:** `docs/chunked-generation-architecture.md` (the "why/how", incl. the
4-layer boundary-safety design). This doc is the "what we build".

**Status:** awaiting approval. **No code will be written until you say go.**

---

## 0. Confirmed decisions (from you)

1. **Trigger:** chunk only when the document **> 40 pages (~100,000 chars)**;
   ≤ 40 pages uses today's single-call path (unchanged).
2. **Background job: YES.** Generation runs as an **asynchronous, resumable job**,
   not inside the request.
3. **Documents are structured** (headings/sections) → structure-aware splitting is
   the primary boundary defence, backed by overlap.
4. **Decentralised, per-section generation.** Each chunk generates its own
   questions independently; results are **checkpointed to the DB as each chunk
   finishes**.
5. **Resumable retry.** On timeout/failure, **completed chunks are already saved**;
   a retry **reads DB state and only (re)generates the failed/pending chunks** —
   never regenerates everything.

---

## 1. How it works in the background (plain walkthrough)

```
Teacher clicks "Generate" on a 150-page chapter
        │
        ▼  (returns immediately)
[ENQUEUE]  create a JOB + plan the CHUNKS (stored in DB), status = "generating"
        │
        ▼  (a background worker takes over)
[SPLIT]    document → structured chunks (with overlap)  → saved as chunk rows (pending)
        │
        ▼  (each chunk, in parallel, capped)
[PER-CHUNK GENERATION]
    chunk 1 → questions → SAVED to DB, chunk 1 = succeeded   ✅ checkpoint
    chunk 2 → questions → SAVED to DB, chunk 2 = succeeded   ✅ checkpoint
    chunk 3 → (timeout/error) → chunk 3 = failed             ⚠️ recorded, others keep going
    ...
        │
        ▼  (only when ALL chunks succeeded)
[FINALIZE]  read every chunk's saved questions → de-duplicate → balance to the
            blueprint → write the final quiz_set / variant / questions
        │
        ▼
     Review queue → publish
```

**Key idea (your requirement):** each chunk's questions are **persisted the moment
that chunk finishes**. So if the job times out or a section fails, everything done
so far is safe in the DB. **Retry = resume:** the worker looks at the job, sees
chunks 1 & 2 = succeeded and chunk 3 = failed, and **re-runs only chunk 3**, then
finalizes. Nothing already generated is thrown away or re-billed.

---

## 2. Boundary safety (recap — the "don't split a topic" guarantee)

Because your docs are structured, the splitter cuts at the **strongest natural
seam**: heading/section → paragraph → sentence (never mid-sentence). Plus **~12%
overlap** so any concept straddling a seam is seen whole by an adjacent chunk. Then
the finalize step **de-duplicates** the overlap twins and **balances** counts back
to the blueprint. (Full detail in the architecture doc, §4.) Net: whole chapter
covered, context never broken, blueprint honoured.

---

## 3. Data model (2 new tables + 1 migration)

Chunk state and per-chunk results live in Postgres — **this is what makes the job
resumable** (Postgres is the source of truth; a crash/restart loses nothing).

```
quiz_generation_jobs
  id            uuid pk
  tenant_id     uuid            -- multi-tenant + RLS
  created_by    uuid            -- the teacher
  document_id   uuid
  subject_id    uuid
  chapter_name  text
  params        jsonb           -- question_types, cognitive_level, difficulty, type_counts, total
  blueprint     jsonb           -- computed once (pure math)
  topics        jsonb           -- whole-document topic list (from the topic pass)
  status        text            -- queued | running | partial | completed | failed
  total_chunks  int
  done_chunks   int
  quiz_set_id   uuid null       -- set only at finalize
  error         text null
  created_at / updated_at

quiz_generation_chunks
  id            uuid pk
  job_id        uuid  -> quiz_generation_jobs(id) on delete cascade
  tenant_id     uuid
  chunk_index   int
  char_start    int             -- provenance: which slice of the doc
  char_end      int
  status        text            -- pending | running | succeeded | failed
  questions     jsonb null      -- the chunk's generated questions (until finalize)
  attempts      int default 0
  error         text null
  updated_at
  unique(job_id, chunk_index)
```

- Tenant-scoped, RLS, same pattern as every other table.
- `questions` is staged JSONB on the chunk row — no separate staging table needed;
  finalize reads these and writes the real `questions` rows via today's code.
- **On delete of the document/job**, chunks cascade — no orphans.

*(This mirrors the existing `ai_extraction_jobs` idea, extended with per-chunk
tracking for resumability.)*

---

## 4. Resumability & failure policy (exactly your rule)

- **Atomic claim:** a worker claims a chunk with
  `UPDATE ... SET status='running' WHERE status IN ('pending','failed') RETURNING`
  so two workers never double-process the same section.
- **Per-chunk retry:** each chunk retries once or twice on a transient error before
  being marked `failed`.
- **Checkpoint:** on success, the chunk's questions + `status='succeeded'` are
  written immediately; `done_chunks` incremented.
- **Timeout / crash:** succeeded chunks remain in the DB. A stuck `running` chunk
  past a timeout is reset to `pending` by a periodic sweeper (or the teacher's
  retry).
- **Retry = resume:** re-run **only** chunks in `{pending, failed}`; succeeded
  chunks are **reused from the DB** (not regenerated, not re-billed). Then finalize.
- **Partial state:** if some sections still fail after retries, job = `partial`
  and the teacher sees "generated from 9 of 10 sections — retry section 10". They
  retry → resume → finalize. (No silent drop; no regenerate-all.)

---

## 5. Execution mechanism (feasible on our stack, honest)

Postgres **is** the job queue (no Redis/Celery needed):
- **Kick-off:** the generate request enqueues the job and starts processing via a
  background task, then returns immediately.
- **Durability:** because all state is in Postgres and checkpointed per chunk, a
  process restart/deploy doesn't lose work.
- **Recovery:** a lightweight **periodic sweeper** re-queues jobs stuck in
  `running` (worker died) and resumes them; the teacher's **manual retry** does the
  same on demand.
- **Growth path:** if volume grows, move processing to a **separate worker
  service** (same code, same DB queue) — no redesign. Redis/Celery only if we ever
  outgrow DB polling.

---

## 6. API & UX (SaaS-grade async)

- `POST /generate` → validates, computes blueprint, enqueues job, **returns
  `{ job_id, status: "generating" }` immediately** (no long wait).
- `GET /generation-jobs/{id}` → `{ status, done_chunks, total_chunks, quiz_set_id? }`
  for the progress UI.
- `POST /generation-jobs/{id}/retry` → resumes (re-runs failed/pending only).
- **Frontend:** the wizard shows a **"Generating… (7/10 sections)"** progress state
  (reuse the Document Log "extracting…" status pattern). On `completed` → open the
  review screen for `quiz_set_id`. On `partial/failed` → "retry" button → resume.
- **Rate limit:** the whole job counts as **one** unit of the teacher's hourly AI
  quota (charged at enqueue), regardless of chunk count.

---

## 7. What stays UNCHANGED (guardrails)

- **≤ 40 pages** → today's single-call generation, untouched.
- **Extraction**, **review/publish**, **subject metrics**, **dashboards**, and the
  **`quiz_set / variant / questions` schema + events** — all unchanged.
- Chunks are **transient generation state**; they are not shown to teachers/
  students and are **not** in analytics.

---

## 8. Build phases (the actual plan — ordered, each independently testable)

**Phase 1 — Splitter (pure logic, no AI, no DB).**
- Structure-aware chunker (heading → paragraph → sentence) + ~12% overlap + min/
  target sizes (config).
- Unit tests on **real CA/CMA chapter samples**: assert no mid-sentence cuts, every
  seam double-covered, chunk sizes within bounds.

**Phase 2 — Migration + data model.**
- `quiz_generation_jobs` + `quiz_generation_chunks` tables, enums, indexes, RLS.
- Config knobs: `CHUNKING_TRIGGER_CHARS`, `GENERATION_CHUNK_CHARS`,
  `..._OVERLAP_CHARS`, `..._MIN_CHARS`, `..._CONCURRENCY`, sweeper interval/timeout.

**Phase 3 — Topic pass for large docs.**
- Run topic extraction over all chunks (parallel) → merge + dedupe → whole-document
  topic list (fixes the truncated-topics half of the gap). Store on the job.

**Phase 4 — Job orchestration service (the core).**
- `enqueue()`: create job + plan/insert chunk rows.
- `process_chunk()`: claim → generate (chunk text + full topic list + allocation,
  reusing the existing generation prompt, topic-tagged) → checkpoint questions.
- `finalize()`: gather chunk questions → dedupe → balance to blueprint → persist
  via today's quiz_set/variant/questions code → set `quiz_set_id`, status.
- Bounded concurrency (reuse extraction's parallel pattern) + per-chunk retry.

**Phase 5 — Execution & recovery.**
- Background kickoff on enqueue; **resume** endpoint; **periodic sweeper** for
  stuck jobs.

**Phase 6 — API + frontend.**
- Route the generate endpoint (>40 pages → job path); job-status + retry endpoints;
  wizard "generating (x/N)" + retry UI.

**Phase 7 — Tests & evaluation.**
- **Resumability test (critical):** kill the worker mid-job → confirm retry re-runs
  only failed/pending chunks and reuses saved ones.
- Coverage (questions from late sections), no-broken-context spot check, blueprint
  fidelity after balancing, near-zero duplicate rate, latency/cost within budget.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Overlap → duplicate questions | dedupe (exact + near-dup) in finalize |
| A topic spans sections | structure split + overlap + topic-tagged pooling |
| Worker dies mid-job | DB checkpoints + sweeper + manual retry (resume) |
| Double-processing a chunk | atomic claim (`WHERE status IN ('pending','failed')`) |
| Blueprint counts drift | balance step trims/top-ups to exact targets |
| Numeric/table content | keep whole sections intact (structure split helps) |
| Cost/latency on huge docs | capped concurrency + background (no request timeout) |

---

## 10. Definition of done

- A 150-page structured chapter → a quiz whose questions demonstrably come from
  **across the whole chapter**, matching the blueprint, with no broken-context
  questions and no duplicates.
- Killing the process mid-generation and retrying **resumes** and only regenerates
  the failed sections.
- ≤ 40-page flow, extraction, review, analytics, and schema **unchanged**.

---

## 11. Open items (small, won't block approval)

- Exact default chunk size / overlap / concurrency values (start with §10 of the
  architecture doc; tune after Phase 7 eval).
- Sweeper interval + "stuck running" timeout (start ~a few minutes).
- Whether to offer "finalize with partial" as a teacher option, or always require
  all sections (default: require all; retry fills gaps).

---

## TL;DR
Large (>40p) chapters generate via a **resumable background job**: split into
**structured, overlapping** sections → each section generates **independently and
is saved to the DB as it finishes** → when all are done, **merge + dedupe + balance
to the blueprint**. A timeout/failure keeps completed sections; **retry resumes and
regenerates only the failed ones.** Whole chapter covered, context intact, blueprint
honoured, analytics/schema untouched. **Approve this and I'll start Phase 1.**
