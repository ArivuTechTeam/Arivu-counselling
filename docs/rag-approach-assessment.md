# RAG for the AI quiz generator — engineering assessment

**Purpose:** a focused, unbiased engineering analysis of adopting **RAG
(Retrieval-Augmented Generation)** in this project — the architecture it would
take *in our stack*, and honest **pros & cons**, especially evaluated against the
**large-document gap** in quiz generation (chapters truncated to ~24 pages today).

**Audience:** engineering + manager.
**Status:** analysis for decision — nothing built.
**Companion doc:** `docs/ai-quiz-generation-large-docs-decision.md` (the 3-option
decision brief). This doc goes deep on the RAG option specifically.

---

## 1. What RAG is (one paragraph)

Instead of sending a whole document to the LLM, RAG (1) **splits** the document
into small passages ("chunks"), (2) converts each into an **embedding** — a list
of numbers that captures its *meaning* so similar text has similar numbers — and
stores them in a **vector database**; then at generation time it (3) **retrieves**
only the passages whose meaning is closest to the topic/query and (4) feeds *just
those* to the LLM. In short: **fetch the relevant pages, not the whole book.**

## 2. The gap we're evaluating it against

Today the "Generate quiz" flow keeps only the first **60,000 chars (~24 pages)** of
a chapter and silently drops the rest (topic extraction has the same limit). For a
150-page chapter, ~84% is ignored. **Question for this doc: does RAG fix that, and
is it the right tool to fix it?**

---

## 3. RAG architecture — designed for THIS project

RAG is always two pipelines: **ingestion** (once per document) and **retrieval +
generation** (per quiz).

### 3a. Ingestion (runs once when a chapter document is uploaded)
```
Upload chapter document
   │
   ▼
Extract text                         ← already exists (pdfplumber / python-docx / OCR)
   │
   ▼
Chunk into passages                  ← reuse quiz_extraction._chunk_text
   │                                   (~800–1,200 tokens, ~15% overlap, split on
   │                                    paragraph/heading boundaries)
   ▼
Embed each chunk  ──►  Gemini embedding model  ──►  vector(768) per chunk
   │
   ▼
Store rows in Postgres (pgvector):
   document_chunks( tenant_id, subject_id, chapter_id, document_id,
                    chunk_index, content, page_start, embedding )
```

### 3b. Retrieval + generation (per quiz)
```
Topic (teacher-selected or from blueprint), e.g. "Ratio Analysis"
   │
   ▼
Embed the topic  ──►  query vector
   │
   ▼
Vector search in Postgres (tenant + chapter/subject scoped):
   "top-K chunks nearest to this query"
   │
   ▼
Retrieved passages (only the relevant few)
   │
   ▼
Prompt = SYSTEM(existing rules) + USER(retrieved passages + blueprint)
   │
   ▼
Gemini 2.5-flash ──(fallback)──► DeepSeek        ← unchanged
   │
   ▼
Questions → validate → Review queue → publish
```
The only change to generation is that `material` now comes from **retrieval**
instead of `text[:60000]`.

### 3c. Data model (the one new table)
```sql
create extension if not exists vector;

create table document_chunks (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),     -- multi-tenant, same as everywhere
  subject_id   uuid,                                     -- enables subject-wide retrieval
  chapter_id   uuid,                                     -- enables chapter-scoped retrieval
  document_id  uuid not null references documents(id) on delete cascade,
  chunk_index  int  not null,
  content      text not null,                            -- the passage
  page_start   int,                                      -- provenance
  embedding    vector(768),                              -- meaning-coordinate
  created_at   timestamptz not null default now()
);

create index on document_chunks using hnsw (embedding vector_cosine_ops);  -- fast ANN search
create index on document_chunks (tenant_id, document_id);                  -- + RLS policies
```
Retrieval query (the whole "smart search" in one statement):
```sql
select content, page_start
from document_chunks
where tenant_id = :tenant_id
  and (chapter_id = :chapter_id or subject_id = :subject_id)   -- scope = chapter or whole subject
order by embedding <=> :query_embedding                        -- cosine distance
limit :k;                                                      -- e.g. top 6
```

### 3d. Tech choices (project-specific)
| Concern | Choice here | Why |
|---|---|---|
| Vector store | **pgvector in Supabase** | Already Postgres; **no new service**; same tenant/RLS model |
| Embeddings | **Gemini `text-embedding-004`** (768-dim) | Existing key; cheap |
| Chunking | **reuse `quiz_extraction._chunk_text`** | Already written & tested |
| Generation | existing **Gemini → DeepSeek** + prompts | Unchanged |
| Orchestration | **plain Python** (no LangChain/LangGraph) | Simpler; frameworks are overkill for single-step RAG |

---

## 4. Does RAG actually fill THE gap? (honest, this is the crux)

The gap is **"a big chapter is truncated to ~24 pages."** RAG's effect on it:

- ✅ **It removes the page limit.** Retrieval can pull a relevant passage from page
  5 *or* page 130 — it indexes the whole document, so content is no longer confined
  to the front 24 pages. On this axis, RAG **does** fix the gap.
- ⚠️ **But RAG optimises for *relevance*, not *coverage*.** It fetches the top-K
  passages that match each topic query. Parts of the chapter that don't match a
  queried topic **still won't be used**. So RAG gives **topic-targeted** coverage,
  not **guaranteed whole-chapter** coverage. If the requirement is literally
  "generate a quiz that covers the entire chapter," **chunked generation** (which
  processes *every* chunk) is the stronger guarantee.
- ⚠️ **The topic step must change too.** Topics are currently extracted from the
  truncated first 24 pages. RAG on generation alone still misses later-page topics
  unless topic discovery is also reworked (e.g. cluster all chunks, or generate
  topic queries differently). RAG fixes the pipeline **only if applied end-to-end.**

**Net:** RAG *can* fill the gap in the sense of "use content from anywhere in the
document," but it is **not the most direct or complete fix for "cover this whole
big chapter."** Its decisive value is the *new capabilities* it unlocks (below),
not the truncation fix per se.

---

## 5. PROS of RAG — for this project (and the gap)

1. **Breaks the page limit for good** — any document size; content isn't confined
   to the front slice. Directly addresses the "later pages ignored" symptom.
2. **Unlocks capabilities the alternatives can't:**
   - **Whole-subject / mixed-revision quizzes** (retrieve across *all* chapters).
   - **Semantic search** and a reusable **question bank**.
   - **Duplicate-question detection**, "find similar questions", recommendations.
3. **Unusually cheap to adopt in our stack** — `pgvector` is built into Postgres/
   Supabase, so a vector DB with **no new vendor/service** and the **same RLS/tenant
   model** we already use.
4. **Embed once, reuse forever** — future quizzes on the same doc reuse embeddings;
   per-quiz we send only a few small relevant chunks → **cheapest per quiz at scale**
   (no re-sending 60k+ chars every time).
5. **Topic precision** — "20 questions only on Liquidity Ratios" fetches exactly
   those passages instead of hoping the model focuses inside a big blob.
6. **Avoids "lost-in-the-middle"** — the LLM sees short, focused, relevant context
   rather than a 100k-token blob it under-reads in the middle.
7. **Reusable platform infrastructure** — the embeddings power search, dedupe, and
   recommendations, so the investment compounds beyond quiz generation.

## 6. CONS of RAG — for this project (and the gap)

1. **Doesn't *guarantee* whole-chapter coverage** — it retrieves *relevant* top-K,
   so for "cover the entire big chapter" it can under-cover. For the **gap as
   stated**, chunked generation is a safer, more direct fix.
2. **New silent failure mode — "retrieval miss":** bad chunking / low K → a
   relevant passage isn't fetched and the quiz silently omits it. We'd be **trading
   one silent failure (truncation) for another (bad retrieval)**, and retrieval
   quality is an ongoing tuning discipline (chunk size, overlap, K, sometimes
   hybrid keyword+vector).
3. **End-to-end rework needed** — the truncated **topic-extraction** step must also
   change, or RAG on generation alone still misses later-page topics.
4. **Real added complexity & lifecycle:** an ingestion job (chunk → embed → store),
   **re-embedding when a teacher edits/re-uploads/deletes** a chapter (stale chunks
   = wrong quizzes), a `pgvector` migration, and an HNSW index to build/tune.
5. **New dependency + latency:** an embeddings API call on every upload (and per
   query) — another external call that can fail/rate-limit, plus upload-time
   processing before the first quiz.
6. **Weaker on numbers/formulas/tables** — embeddings match prose meaning well but
   are mediocre at quantitative/tabular content, which is common in CA/CMA material
   (mitigable with hybrid search, but that's extra work).
7. **Zero benefit for today's #1 path** — one normal chapter (≤ ~50–60 pages) that
   already fits in the model window. RAG adds all the above for no gain there.
8. **Harder to debug** — "why didn't it ask about X?" becomes "was X retrieved?", a
   search-quality investigation rather than "was it in the prompt?".

---

## 7. RAG vs the cheaper options — strictly for filling the gap

| For the gap ("big chapter not fully used") | Raise the cap | Chunked generation | RAG |
|---|---|---|---|
| Effort | 1 env var | days (reuse existing code) | ~1–2 weeks |
| New infra | none | none | pgvector + embeddings + ingestion |
| Fixes ≤ ~50–60-page chapters | ✅ | ✅ | ✅ (overkill) |
| Fixes very large (100–150+ pages) | ⚠️ fits window but uneven coverage | ✅ full coverage | ✅ (relevance, not full coverage) |
| Guarantees whole-chapter coverage | ❌ | ✅ | ❌ (relevance-based) |
| Adds cross-chapter / search / bank | ❌ | ❌ | ✅ |

**Reading of the table:** if the objective is *only* "stop truncating big
chapters," **raise the cap** (small docs) or **chunked generation** (large docs) do
it with far less effort and — for guaranteed coverage — actually *better*. **RAG is
not the most efficient tool for the gap alone.**

---

## 8. When RAG IS the right call (decision criteria)

Adopt RAG when one or more of these is on the near-term roadmap — because then RAG
is the *only* clean solution, and it fixes truncation as a side effect:
1. **Whole-subject / mixed-revision quizzes** (pull from all chapters at once).
2. A **searchable question bank** / semantic search across content.
3. **Duplicate-question detection** / recommendations.
4. Uploads far larger than a single chapter (whole books).

If the roadmap is **only per-chapter quizzes for now**, RAG is **premature** — its
cost lands today, its payoff lands later.

---

## 9. Effort, rollout & risks (if we green-light it)

**Rollout (phased):**
1. Migration: enable `vector`, create `document_chunks` + HNSW index + RLS.
2. Ingestion: on upload, chunk → embed (Gemini) → store (tenant/subject/chapter
   tagged). Backfill existing documents.
3. Retrieval module: `retrieve(query, scope) -> passages` (plain Python + SQL).
4. Wire generation to use retrieved passages; rework topic discovery to be
   whole-document (cluster chunks or per-chunk topic extraction).
5. Lifecycle: re-embed on document edit/replace; cascade delete on document delete.

**Top risks to manage:**
- Retrieval quality (chunking + K + possibly hybrid search) — needs evaluation.
- Embedding-model/version pinning (dims must stay fixed; re-embed if changed).
- Stale chunks on document edits.
- Numeric/tabular recall for accounting content.

**Cost:** embedding a 150-page doc ≈ fractions of a cent (one-time); per-quiz cost
*drops* (send a few chunks vs 60k+ chars). Infra cost ≈ storage of vectors in the
DB you already run.

---

## 10. Verdict (unbiased)

- **RAG is a strong, stack-friendly investment** — `pgvector` makes it unusually
  cheap here, and it becomes reusable platform infrastructure (search, bank,
  dedupe), not a single-use feature.
- **But for the truncation gap *specifically*, RAG is not the most efficient or
  complete fix.** "Cover this whole big chapter" is a *coverage* problem; RAG
  optimises *relevance*. The direct fixes are **raise the cap** (≤ ~50–60 pages)
  and **chunked generation** (larger / guaranteed coverage) — less effort, no new
  infra, and for coverage, actually better.
- **Therefore:** justify RAG by the **capabilities** (whole-subject quizzes,
  search, question bank), not by the gap. If those are on the roadmap → build RAG
  (it fixes truncation as a bonus). If not → fix the gap with the cap/chunking now
  and adopt RAG later; nothing is wasted.
- **Frameworks:** not needed — plain Python + `pgvector` + Gemini embeddings.
  Consider LangGraph only if a future agentic "generate → self-check → retry" loop
  is wanted.

---

## 11. References (2025–26)
- Survey on Retrieval-Augmented Generation with LLMs: https://arxiv.org/pdf/2509.10697
- LongRAG (RAG + long-context tradeoffs, positional bias): https://arxiv.org/pdf/2406.15319
- Advanced chunking strategies for RAG: https://arxiv.org/pdf/2504.19754
- LangChain retrieval docs: https://docs.langchain.com/oss/python/langchain/retrieval
- RAG frameworks compared (LangChain / LangGraph / LlamaIndex): https://aimultiple.com/rag-frameworks
- "Is LangChain too complex for simple RAG?" (community, 2025): https://github.com/orgs/community/discussions/182015
