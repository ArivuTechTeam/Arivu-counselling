# AI quiz generation — large-document gap & options (decision brief)

**Purpose:** decide how the "Generate quiz" pipeline should handle **large chapter
documents (120–150+ pages)**. Today it silently uses only a fraction of a big
chapter. This doc explains the current pipeline, the exact gap, the three options
(keep-as-is / chunked generation / RAG), honest pros & cons of each, where RAG
genuinely helps, and the decision we need to make.

**Audience:** engineering + manager.
**Status:** discussion / decision pending — nothing built yet.

---

## TL;DR (for a 30-second read)

- Today, when generating a quiz, we send the teacher's document text **plus** a
  topic blueprint to the AI. The document text **is** used (no hallucination).
- **But** we only keep the **first ~60,000 characters (~24 pages)** of the
  document and **silently drop the rest.** A 150-page chapter → ~84% ignored, with
  no warning. The topic-extraction step has the same limit.
- **The "Generate quiz" flow does NOT chunk.** (Chunking exists only in a
  different feature — "Extract quiz".)
- **Ways to fix it:**
  - **Option A0 — Raise the cap (do-now, one env var):** raise
    `GENERATION_MAX_TEXT_CHARS` from **60,000 → 150,000 chars (~50–60 pages)**. Both
    models hold it easily (Gemini ~1,000,000-token window; DeepSeek fallback
    ~160,000). No code change. Fixes the truncation for realistic chapters up to
    ~50–60 pages.
  - **Option B — Chunked generation:** process the whole chapter in pieces, merge.
    Right-sized fix for **very large** chapters (beyond ~60–80 pages) and for
    **guaranteed even coverage**, **no new infrastructure**, reuses code we have.
  - **Option C — RAG (knowledge base):** embed the document, retrieve relevant
    passages. Heavier (needs a vector store + embeddings), and it **targets
    relevant passages rather than guaranteeing full-chapter coverage** — better
    for *cross-chapter / whole-subject / search*, not strictly for "cover this one
    big chapter."
- **Recommendation:** **do Option A0 now** — raise the cap to **150,000 chars** so
  ~50–60-page chapters are fully used (immediate, one env var, negligible cost).
  Add **Option B (chunked generation)** when chapters routinely exceed ~60–80 pages
  or when *guaranteed* whole-chapter coverage is required. **Option C (RAG)** is a
  future investment worth it **only if** we add whole-subject quizzes, a question
  bank, or search. **LangChain/LangGraph are not needed.**

---

## 1. How the current pipeline works (verified from code)

The teacher picks a **subject → chapter**, uploads **one chapter's document**, and
generates a quiz. The "Generate quiz" wizard makes **2 AI calls**:

```
Upload chapter document
      │
Call 1  ── Topic extraction (topics.py) ── reads document text ──► [list of topics]
      │
Step    ── build_blueprint() ── pure math, NO AI ──► how many questions per topic
      │
Call 2  ── Blueprint generation (blueprint.py) ── reads document text AGAIN
           prompt = SYSTEM(rules) + USER(document text + blueprint)
                          │
                          ▼
              Gemini 2.5-flash ──(fallback)──► DeepSeek
                          │
                          ▼
              JSON questions → validate → Review queue → publish
```

**Confirmed facts (from the code):**
- **The full document text IS sent to Call 2**, embedded as `material`, together
  with the blueprint. Topics only steer *how many* questions per topic; the
  document is the actual source. → It does **not** generate from topic names
  alone; it is **not** hallucinating.
- The document text is **truncated**:
  - `blueprint.py`: `material = text[:60000]` → first 60,000 chars only.
  - `generation.py` (simpler path): skips ~8% front-matter, then 60,000 chars.
  - `topics.py`: `text[:60000]` → first 60,000 chars only.
- **`GENERATION_MAX_TEXT_CHARS`** — currently **60,000 (~24 pages)**, env-tunable.
  **Proposed new value: 150,000 (~50–60 pages)** — see Option A0 below.

---

## 2. The gap (the actual problem)

**60,000 characters ≈ ~24 pages.** A real chapter is often bigger.

For a **150-page chapter (~375,000 characters):**

```
|<------------------------- 150-page chapter (~375,000 chars) ------------------------->|
|  pages 1–24 (60,000 chars)  |            pages 25–150  (~315,000 chars)               |
|      ✅ SENT TO THE AI       |            ❌ SILENTLY DROPPED (never seen)              |
```

- **~84% of the chapter is thrown away**, with **no warning** to the teacher.
- It happens **twice**: topic extraction and generation both read only the first
  ~24 pages → topics and questions from pages 25–150 never appear.
- **The Generate flow does not chunk** — the extra pages are not summarised,
  sampled, or split; they are simply ignored. (Chunking exists only in the
  separate "Extract quiz" feature, `quiz_extraction.py`.)

**Impact:** a teacher believes the quiz covers the whole chapter; it covers the
first quarter. This is a **silent correctness gap**, not a crash.

---

## 2.5 The immediate fix — raise the cap (Option A0)

The context windows are far bigger than the cap, so raising it is the fastest fix.

**Verified context windows (2025–26):**
- **Gemini 2.5 Flash: ~1,048,576 tokens (~1M)** — max output ~65k.
- **DeepSeek (our fallback): ~163,840 tokens (~160k)** — max output ~16–32k.

**Sizing (rule of thumb: ~2,500 chars/page ≈ ~625 tokens/page):**

| Target | Chars needed | ≈ Tokens | Fits Gemini (1M)? | Fits DeepSeek (160k)? |
|---|---|---|---|---|
| 24 pages (today) | 60,000 | ~15k | ✅ | ✅ |
| **50 pages** | **~125,000** | **~31k** | ✅ (3%) | ✅ (19%) |
| 60 pages (headroom) | ~150,000 | ~37k | ✅ | ✅ |
| 150 pages | ~375,000 | ~94k | ✅ | ✅ (but near the safe input ceiling once output is added) |

**Recommended change (one env var, no code):**
```
GENERATION_MAX_TEXT_CHARS = 150000    # ~50–60 pages (was 60000 ≈ 24 pages)
```
This one setting fixes **both** topic extraction and generation. Cost stays
negligible (~2–3¢ per quiz). Restart the backend after changing it.
*(If chapters are text-dense, ~3,000–3,500 chars/page, use ~175,000.)*

**Honest caveats (why raising the cap isn't a total fix for very large docs):**
1. **"Fits" ≠ "even coverage."** Even in a 1M window, models attend best to the
   start/end and under-read the middle ("lost in the middle"). Mild at ~50 pages;
   real by ~150 pages.
2. **Output is the bottleneck, not input.** The model still outputs only the N
   questions asked for and cherry-picks salient themes — more input ≠ broader
   coverage of the tail.
3. **The fallback (DeepSeek, ~160k total incl. output) is the binding limit.** Keep
   input under ~120k tokens (~480k chars) so a fallback call still has room. Fine
   for ≤ ~50–60 pages; not for a 400-page book.

**Verdict:** for the stated **~50-page** target, **Option A0 (raise cap to 150,000)
is sufficient and correct** — chunking/RAG would be over-engineering. Chunking
(Option B) only becomes necessary beyond ~60–80 pages or when *guaranteed* even
coverage is required.

---

## 3. The options to fill the gap

| | **A. Keep as-is (truncate)** | **B. Chunked generation** | **C. RAG (knowledge base)** |
|---|---|---|---|
| Idea | Send first ~24 pages | Split chapter into pieces, generate from each, merge | Embed doc into a vector store, retrieve relevant passages per topic |
| Covers a big chapter fully | ❌ no (first 24 pages) | ✅ **yes — every page** | ⚠️ covers *relevant* passages, not guaranteed all |
| Whole-subject quiz (across chapters) | ❌ | ⚠️ clumsy (loop each chapter) | ✅ **best fit** |
| Search / question bank / dedupe | ❌ | ❌ | ✅ **only option** |
| New infrastructure | none | **none** (reuse existing chunk code) | **vector DB (pgvector) + embeddings + ingestion** |
| Per-quiz cost | send 60k chars | send whole doc in pieces (more calls) | send only a few small chunks (cheapest at scale) |
| Upload-time cost | none | none | embed all chunks (one-time, cheap) |
| Complexity / maintenance | ~none | low | **medium** (re-embed on edit, index tuning, retrieval quality) |
| Time to ship | shipped | days | ~1–2 weeks |
| Main failure mode | silently drops pages 25+ | duplicates across pieces (handled by de-dupe) | **retrieval miss** (relevant passage not fetched) |

---

## 4. Pros & cons — the CURRENT approach (truncate)

**Pros**
- Simplest possible; already shipped and stable.
- Grounded in the real document (no hallucination) for the part it sends.
- Cheap and fast; predictable cost.
- Perfectly adequate for **small chapters (≤ ~24 pages)**.

**Cons**
- **Silently drops everything past ~24 pages** — misleading for big chapters.
- Same limit hits **topic extraction**, so later-page topics never surface.
- `blueprint.py` keeps the *first* 60k with **no front-matter skip** — for a book
  that first slice can be cover/TOC/preface (low-value pages).
- Does not scale with real chapter sizes; the failure is invisible to the teacher.

---

## 5. Pros & cons — CHUNKED GENERATION (Option B)

**Pros**
- **Guarantees full-chapter coverage** — every page is used.
- **No new infrastructure**: reuses the chunk-split/merge logic already written for
  the "Extract quiz" feature.
- Bounds each AI call's size → avoids "lost-in-the-middle" and output-limit issues.
- Fixes both the topic step and the generation step the same way.
- Fast to ship (days), low maintenance.

**Cons**
- More AI calls per quiz on a big doc → modestly higher cost/latency (still cents).
- Re-reads/re-sends the document each generation (no reuse across quizzes).
- Doesn't help with cross-chapter/whole-subject quizzes or search (out of scope).
- Needs sensible question-allocation across chunks + de-duplication at merge.

---

## 6. Pros & cons — RAG / KNOWLEDGE BASE (Option C)

**What RAG is (plain):** turn each passage of the document into a "meaning
address" (an **embedding** = list of numbers), store them in a **vector database**;
at quiz time, find the passages whose meaning is closest to the topic and feed
**only those** to the AI. ("Retrieval-Augmented Generation".)

**Pros**
- **Removes the page limit entirely** — retrieval can pull relevant passages from
  anywhere in the document (page 5 or page 130), not just the front.
- **Unlocks new capabilities** the others can't: **whole-subject quizzes** (across
  all chapters), **semantic search**, a reusable **question bank**, **duplicate
  detection**, recommendations.
- **Cheap to adopt in our stack:** Supabase = Postgres, and Postgres has
  **`pgvector`** built in → a vector database with **no new service** and the same
  tenant isolation/RLS we already use.
- **Embed once, reuse forever:** future quizzes on the same doc reuse the
  embeddings; per-quiz we send only a few small relevant chunks (cheapest at scale).
- **Topic precision:** "20 questions only on Liquidity Ratios" fetches exactly
  those passages.

**Cons**
- **For a single chapter it can UNDER-cover.** RAG fetches the *top-K relevant*
  passages per topic — it does **not guarantee the whole chapter is used**. For
  "cover this entire big chapter," chunked generation is actually the safer fit.
- **New, subtle failure mode — "retrieval miss":** if chunking or the top-K is
  off, a relevant passage isn't fetched and the quiz silently omits it (a
  *different* silent failure than truncation). Retrieval quality is its own tuning
  discipline (chunk size, overlap, K, sometimes hybrid keyword+vector search).
- **Real added complexity & lifecycle:** an ingestion pipeline (chunk → embed →
  store), **re-embedding when a teacher edits/re-uploads** (stale chunks = wrong
  quizzes), a migration to enable `pgvector`, and an index (HNSW) to tune.
- **New dependency + latency:** an embeddings API call on upload and per query.
- **Weaker on numbers/formulas/tables:** embeddings match prose meaning well but
  are mediocre at quantitative/tabular content — relevant for a CA/CMA platform
  (mitigable with hybrid search, but that's more work).
- **Zero benefit for today's #1 path** (one normal chapter → quiz): adds all the
  above for no gain when the chapter already fits.

---

## 7. Does RAG actually fill THIS gap? (the honest nuance)

The gap = "a big single chapter is truncated." RAG **breaks the page limit** (good)
**but** it is built to fetch *relevant* passages, **not to sweep the whole chapter**.
So:

- If the goal is **"a quiz that covers the whole big chapter"** → **chunked
  generation** is the better, safer fit (it touches every page). RAG could leave
  gaps.
- If the goal is **"targeted questions on specific topics"** or **"pull from a
  huge book / across many chapters / search"** → **RAG is the right tool**, and it
  scales to any size.

Also: whichever we pick, **topic extraction is truncated today too** — the fix must
cover the whole pipeline, not just the final call. Chunked generation handles this
naturally; a RAG approach would need the topic step addressed as well.

---

## 8. Where RAG genuinely helps (so we invest for the right reason)

RAG earns its keep when we want to go **beyond a single chapter**:
1. **Whole-subject / mixed-revision quiz** — pull from *all* chapters of a subject.
2. **Question bank + semantic search** — "find all questions/passages about X."
3. **Only a sub-topic inside a very large chapter** — jump straight to it.
4. **Duplicate-question detection / recommendations** — reuse the embeddings.

For a **normal single-chapter quiz**, RAG adds machinery for little gain.

---

## 9. Frameworks: do we need LangChain / LangGraph? (researched)

**No — not for this.** They are frameworks: LangChain chains simple steps;
LangGraph is for **agentic loops/branches/retries**. Current (2025–26) guidance:
LangChain is often considered **bloated/overkill for simple RAG**, and many teams
prefer **plain Python + a vector store** for speed and easier debugging. We already
have `pgvector` + Gemini embeddings, so **vanilla Python is simpler and enough**.
Revisit **LangGraph only** if we later build an agentic "generate → self-check →
retry" loop.

---

## 10. Recommendation & the decision to make

This is **roadmap-driven**, not "RAG good/bad":

- **Do now, regardless (Option A0):** raise `GENERATION_MAX_TEXT_CHARS` from
  **60,000 → 150,000** (~50–60 pages). One env var, negligible cost, fits both
  models — removes the truncation for realistic chapters immediately.
- **If chapters routinely exceed ~60–80 pages, or exhaustive coverage is required**
  → **add Option B (chunked generation).** Fixes the current gap with **no new
  infra**, ships in days, and we can add RAG later without throwing B away.
- **If we plan whole-subject quizzes, a question bank, or search soon** → **invest
  in Option C (RAG) now.** Our `pgvector`-in-Supabase advantage makes this an
  unusually cheap time to adopt it, and the embeddings become reusable platform
  infrastructure. (Note: for pure "cover a big chapter," still pair it with, or
  prefer, chunked coverage.)
- **Either way:** consider adding a **grounding check** (verify each generated
  question is supported by the source) — a real quality win, independent of RAG.

**Decision questions for the team:**
1. Do we need **whole-subject quizzes** (across chapters) in the next 1–2 quarters?
2. Do we want a **searchable question bank** / duplicate detection?
3. What's the **real maximum chapter size** teachers upload (settles urgency)?
4. Is **exhaustive chapter coverage** the requirement, or **topic-targeted** quizzes?

If the answer to 1 or 2 is "yes, soon" → RAG. If it's "not yet" → chunked
generation now, RAG later.

---

## 11. References (research, 2025–26)

- Survey on Retrieval-Augmented Generation with LLMs: https://arxiv.org/pdf/2509.10697
- LongRAG (RAG + long-context tradeoffs, positional bias): https://arxiv.org/pdf/2406.15319
- Advanced chunking strategies for RAG: https://arxiv.org/pdf/2504.19754
- LangChain retrieval docs: https://docs.langchain.com/oss/python/langchain/retrieval
- LangChain vs LangGraph (2026): https://atlan.com/know/ai-agent/ai-agent-memory/langchain-vs-langgraph/
- RAG frameworks compared (LangChain / LangGraph / LlamaIndex): https://aimultiple.com/rag-frameworks
- "Is LangChain too complex for simple RAG?" (community, 2025): https://github.com/orgs/community/discussions/182015

---

## Appendix — key code references

- `backend/app/services/blueprint.py` → `material = text[:60000]`; document text +
  blueprint both sent to Call 2.
- `backend/app/services/generation.py` → `_select_material` (front-matter skip +
  60k truncate).
- `backend/app/services/topics.py` → `text[:60000]` (topic extraction truncation).
- `backend/app/services/quiz_extraction.py` → `_chunk_text` / chunk-and-merge
  (**this is the chunking code — it lives in EXTRACTION, not generation**).
- `GENERATION_MAX_TEXT_CHARS` (default 60,000) — env-tunable cap.
