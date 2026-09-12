# Chunked quiz generation — architecture plan

**Goal:** when a teacher's chapter document is **large (> 40 pages)**, generate a
quiz that covers the **whole** chapter (not just the first ~24 pages) — **without
damaging the meaning/context of the material at chunk boundaries.**

**Scope:** the "Generate quiz" pipeline only (topic extraction + blueprint
generation). Extraction, review, publish, analytics, and the DB schema are
**unchanged**. Production/SaaS-grade: bounded, observable, idempotent, fails safe.

**Status:** architecture for approval — not built.

---

## 0. The one hard problem this must solve (your critical point)

If we naïvely cut the document every N characters, a boundary can fall **in the
middle of a topic/concept** — half a concept in chunk 1, half in chunk 2. Each
half is incomplete context, so the questions generated from it are shallow or
wrong. **A "content/teaching" document is meaning-continuous, so a bad cut poisons
generation.**

This architecture defends against that with **four layers** (detailed in §4):
1. **Structure-aware splitting** — cut only at *natural seams* (headings →
   paragraphs → sentences), never mid-sentence.
2. **Overlap** — each chunk repeats the tail of the previous one, so a concept
   straddling a seam is still seen whole by at least one chunk.
3. **Topic-aware generation** — chunks generate questions *tagged by the
   document-wide topics*, not blindly; the blueprint stays authoritative.
4. **Merge with de-duplication + count balancing** — overlap-induced duplicates
   are removed and the final quiz is balanced back to the blueprint exactly.

---

## 1. Design principles (non-negotiables)

- **Grounding preserved:** every question still comes from the real document text.
- **Blueprint preserved:** the teacher's topic emphasis + per-type counts are honoured
  in the *final* quiz, regardless of how many chunks were used.
- **Analytics & data untouched:** output is the same `quiz_set → variant →
  questions` (with `topic_id / chapter_id / subject_id`). Chunking is a
  **generation-time internal strategy** — invisible downstream. No schema change,
  no analytics change, no review-flow change.
- **One user action = one quota unit:** internal chunk calls must **not** multiply
  the teacher's AI rate-limit; the whole generation counts as **one**.
- **Bounded & safe:** capped concurrency, per-chunk retry, partial-failure policy,
  within the request timeout (or a background job for the extreme case).

---

## 2. When chunking activates (routing)

Decision is made on the **extracted text length** (the backend works on text, not
rendered pages). Rule of thumb: **~2,500 chars/page**, so **40 pages ≈ ~100,000
chars**.

```
Extract text from the uploaded chapter
        │
        ▼
len(text) ≤ CHUNKING_TRIGGER_CHARS (≈100,000 ≈ 40 pages)?
        │
   ┌────┴─────────────────────────┐
   YES                            NO
   │                              │
   ▼                              ▼
SINGLE-CALL path (today's flow)   CHUNKED path (this document)
 topics(1 call) → generate(1 call)  topics(whole doc) → generate(per chunk) → merge
```

- **≤ 40 pages → single call** (unchanged; the model reads it fine; cheapest).
- **> 40 pages → chunked path.**

This threshold is a **config knob** (`CHUNKING_TRIGGER_CHARS`) so ops can tune it
without a deploy.

---

## 3. End-to-end workflow (chunked path)

```
                ┌──────────────────────────────────────────────────────────┐
                │                    CHUNKED GENERATION                       │
                └──────────────────────────────────────────────────────────┘

Uploaded chapter text (> 40 pages)
        │
        ▼
[1] SPLITTER  ──►  structure-aware chunks WITH overlap
        │           (each chunk = coherent section(s), + tail of previous)
        ▼
[2] TOPIC PASS  ──►  extract topics from every chunk (parallel) → MERGE + dedupe
        │             → one document-wide topic list  → teacher picks/weights
        ▼
[3] BLUEPRINT (unchanged math)  ──►  per-topic counts + per-type mix (whole quiz)
        │
        ▼
[4] ALLOCATOR  ──►  split the blueprint's target across chunks
        │             (proportional to chunk size; topic emphasis carried in prompt)
        ▼
[5] PER-CHUNK GENERATION (parallel, capped)  ──►  each chunk returns questions,
        │                                          each tagged with its topic
        ▼
[6] MERGER  ──►  concatenate → DEDUPE (exact + near-dup) → BALANCE to blueprint
        │          (trim overflow; optional targeted top-up for a short topic)
        ▼
[7] PERSIST (unchanged)  ──►  quiz_set → variant → questions (topic_id/chapter_id)
        │
        ▼
     Review queue → publish
```

Only steps **[1], [2-merge], [4], [5], [6]** are new; **[3] and [7] are today's
code.** Steps [2] and [5] are the two LLM-call stages (topics, then generation).

---

## 4. The chunking strategy in depth (how we avoid breaking topics)

### Layer 1 — Structure-aware splitting (primary defence)
We never cut blindly. The splitter picks the **strongest natural boundary
available**, in priority order:

1. **Section/heading boundaries** — if the document exposes structure (headings,
   numbered sections like "3.2", ALL-CAPS titles, "Chapter/Unit/Topic" markers,
   or PDF/DOCX heading styles). A chunk = one or more **whole sections**. Because
   sections *are* topics, a topic almost never spans a section cut.
2. **Paragraph boundaries** (blank-line separated) — if no headings. Never cut
   mid-paragraph.
3. **Sentence boundaries** — only if a single paragraph exceeds the max size.
4. **Hard character cut** — last resort for a pathological single block (huge
   table). Rare; logged.

**Target sizes (config):** each chunk ~**40,000 chars (~10k tokens)** — big enough
to be a self-contained, coherent teaching unit; small enough that the model reads
it fully (no "lost in the middle") and output stays bounded. **Minimum chunk
~8,000 chars** so we never create tiny orphan chunks (merge small trailing pieces
into the previous chunk).

### Layer 2 — Overlap (safety net for straddling content)
Each chunk **repeats the tail of the previous chunk** at its start — an **overlap
of ~10–15% (~5,000 chars ≈ 1–2 paragraphs)**, snapped to a sentence/paragraph
boundary. So if a concept's lead-in sat at the end of chunk 1, **chunk 2 still sees
it.** This is the direct fix for "the topic is split between chunk 1 and chunk 2."

```
Chapter text:  [=========== section A ===========][===== section B =====][== C ==]
Chunk 1:       [=========== section A ===========][ overlap→B-lead ]
Chunk 2:                        [ ←A-tail overlap ][===== section B =====][ovl→C]
Chunk 3:                                              [ ←B-tail overlap ][== C ==]
```
Overlap guarantees every seam is covered by **two** chunks, so no concept is only
ever seen half.

### Layer 3 — Topic-aware generation (blueprint stays boss)
The blueprint is **document-wide** (topics + counts). We do **not** tell a chunk
"make 5 questions." Instead each chunk gets: *the passage* + *the full topic list*
+ instruction: **"generate questions ONLY from this passage, for whichever of these
topics it actually covers, and tag each question with its topic."** So:
- A chunk that doesn't cover a topic simply won't produce questions for it (no
  forcing → no hallucination).
- Coverage of a topic is naturally pooled from **all** chunks that touch it.

### Layer 4 — Merge: de-duplicate + balance to the blueprint
Because of overlap and multiple chunks, we may get **duplicate/near-duplicate**
questions and **uneven counts**. The merger:
1. **De-duplicates** — exact match on normalised question text, plus a near-dup
   check (same answer + high text similarity) to catch overlap twins.
2. **Balances to the blueprint** — group by topic/type, **trim overflow** to hit
   the target counts, keeping the highest-quality/most-distinct items.
3. **Targeted top-up (optional)** — if a priority topic came up short, one small
   extra generation call scoped to that topic's chunk(s) fills the gap.

Result: the final quiz **matches the blueprint exactly**, despite being assembled
from many chunks. This is what makes chunking invisible to the teacher.

---

## 5. Topic extraction for large docs (fixing the other half of the gap)

Today topic extraction also truncates to ~24 pages. In the chunked path we run
**topic extraction over every chunk in parallel, then merge + de-duplicate** into
one document-wide list (same "merge + dedupe" utility as extraction already uses).
So the teacher sees topics from the **whole** chapter — not just the front.

---

## 6. Concurrency, performance & cost (SaaS-grade)

- **Parallel chunk processing** with a **capped worker pool** (config, e.g. 4) —
  reuses the exact pattern already in the extraction pipeline.
- **Latency:** a 150-page doc ≈ ~8–10 chunks; at concurrency 4 that's ~3 waves.
  Kept **within the request timeout**. (See §9 for the background-job escape hatch.)
- **Cost:** more calls, but each is small; a large-doc quiz is still a few cents.
  Predictable and bounded by chunk count.
- **Rate limit:** the **whole generation consumes ONE** unit of the teacher's
  hourly AI quota — internal chunk calls are *not* individually counted.

---

## 7. Failure handling & partial results (production policy)

- **Per-chunk retry once** on a transient model error (reuse extraction's pattern).
- **Partial-failure policy (explicit decision):** if a chunk still fails after
  retry, **continue with the remaining chunks** and **record which sections were
  skipped**, surfacing a clear notice ("generated from 9 of 10 sections — 1 section
  failed, retry?"). We do **not** silently drop, and we do **not** fail the whole
  job for one bad chunk. (Alternative — abort-all — is available via config if the
  team prefers all-or-nothing.)
- **Idempotency:** a generation run is atomic at persist time (same
  quiz_set/variant transaction + compensation-on-failure as today), so a retry
  never leaves half a quiz.

---

## 8. Data integrity & analytics (explicitly: no impact)

- The persisted output is **byte-for-byte the same shape** as today: one
  `quiz_set`, one `variant`, N `questions` tagged with `topic_id/chapter_id/
  subject_id`.
- Chunks are **transient** — used only during generation, **not stored**, **not**
  surfaced to teachers or students, **not** in analytics.
- The events ledger (`question.generated`) fires per question exactly as today.
- ⇒ **Review queue, dashboards, subject metrics, and all analytics are unaffected.**

*(If we later also build RAG, chunks would be persisted+embedded — but that is a
separate feature. This plan keeps chunks ephemeral.)*

---

## 9. The scale escape hatch (very large docs)

Parallel chunking keeps typical large chapters (≤ ~10–12 chunks) inside the
request timeout. For a **pathologically large** upload (hundreds of pages →
many chunks), the same design runs as a **background job**:
- The request returns immediately with a "generating…" state; a worker processes
  chunks; the Document Log / review page shows progress (the "extracting…" status
  pattern already exists).
- This is a **drop-in extension** of the same pipeline (no redesign) — recommended
  only if uploads routinely exceed the sync budget.

---

## 10. Configuration knobs (ops-tunable, no deploy)

| Knob | Default | Meaning |
|---|---|---|
| `CHUNKING_TRIGGER_CHARS` | 100,000 (~40 pages) | above this → chunked path |
| `GENERATION_CHUNK_CHARS` | 40,000 (~10k tokens) | target chunk size |
| `GENERATION_CHUNK_OVERLAP_CHARS` | 5,000 (~12%) | overlap between chunks |
| `GENERATION_CHUNK_MIN_CHARS` | 8,000 | merge smaller trailing pieces |
| `GENERATION_CHUNK_CONCURRENCY` | 4 | parallel chunk workers |

---

## 11. Components & responsibilities (where things live)

| Component | Responsibility | Reuse? |
|---|---|---|
| **Router** | pick single-call vs chunked by `CHUNKING_TRIGGER_CHARS` | new (tiny) |
| **Splitter** | structure-aware + overlap chunking | extend existing `_chunk_text` |
| **Topic pass** | per-chunk topic extraction → merge/dedupe | reuse extraction merge |
| **Allocator** | spread blueprint targets across chunks | new (small) |
| **Chunk generator** | per-chunk, topic-tagged generation (parallel, retry) | reuse extraction concurrency + existing generation prompt |
| **Merger** | dedupe + balance to blueprint (+ optional top-up) | extend existing merge/dedupe |
| **Persistence** | quiz_set/variant/questions + events | **unchanged (today's code)** |

Most of this is **assembling existing, tested building blocks** (chunk/merge from
extraction; prompt/persist from generation) — not green-field.

---

## 12. Rollout & testing

**Rollout (phased, low-risk):**
1. Splitter (structure-aware + overlap) as a pure function + unit tests on real CA/
   CMA chapter samples (verify no mid-sentence cuts; every seam double-covered).
2. Router + chunked path behind a flag; single-call path unchanged for ≤40 pages.
3. Topic pass over chunks; merge/dedupe.
4. Allocator + per-chunk generation + merger (dedupe/balance).
5. Enable for real large docs; monitor coverage + duplicate rate + latency.

**Evaluation (what "good" means):**
- **Coverage:** questions reference content from *late* sections, not just early.
- **No broken context:** spot-check that no question depends on a concept that was
  cut (the overlap + structure split should make this ~zero).
- **Blueprint fidelity:** final counts/mix match the blueprint after balancing.
- **Duplicate rate:** near-zero after dedupe.
- **Latency & cost** within budget for the p95 large doc.

---

## 13. Decisions I made (defaults) — override any of these

1. **Trigger at ~40 pages / 100,000 chars** (per your instruction). ≤ that = today's
   single call.
2. **Structure-aware split + ~12% overlap** as the boundary-safety mechanism
   (recommended). Chunk ~40k chars, min ~8k.
3. **Topic-tagged generation + merge-balance** (Layer 3/4) rather than a rigid
   "topic→single-chunk" mapping — more robust to topics that span sections.
4. **Partial-failure = continue + report** (not abort-all).
5. **Synchronous with parallelism** now; background-job escape hatch only if
   uploads routinely exceed the timeout.

**Open questions for you (won't block the design, but will tune it):**
- Typical + maximum real chapter size teachers upload? (sets concurrency/timeout).
- Do your chapter PDFs have **clear headings/structure** we can split on, or are
  they flat text? (decides how strong Layer 1 can be vs relying more on overlap).
- Is **abort-all** ever preferred over partial results for a failed section?

---

## 14. TL;DR

- **> 40 pages → chunked generation; ≤ 40 → unchanged.**
- **Boundary problem solved by 4 layers:** structure-aware cuts (never mid-idea) +
  **overlap** (every seam seen twice) + **topic-tagged generation** + **dedupe &
  balance** back to the blueprint.
- **Whole chapter covered**, **blueprint honoured**, **analytics/schema untouched**,
  **one quota unit**, bounded/parallel, fails safe.
- Built mostly by **assembling existing chunk/merge/generation building blocks** —
  feasible and production-ready.
