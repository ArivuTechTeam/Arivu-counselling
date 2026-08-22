# Architecture & Scalability Plan

**Status:** Draft for review — no code changes yet
**Date:** August 2026
**Purpose:** Answer one question honestly — *"Will our current schema, backend, and frontend hold up when data gets large?"* — and lay out a right-sized foundation so the super-admin **"Is the AI good enough?"** product-intelligence cockpit can be built on solid ground.

---

## 1. Verdict (the short answer)

| Layer | Scales as-is? | Why |
|---|---|---|
| **Core schema** (tenants, users, quizzes, questions, attempts) | ✅ Mostly yes | Normalised, `tenant_id` everywhere, FKs, RLS via `current_tenant_id()`/`is_staff()`/`is_super_admin()`, good single-column indexes, pgvector index ready for future semantic search. |
| **Backend analytics** (dashboards, stats endpoints) | ❌ No | Every analytics endpoint fetches whole tables and aggregates **in Python**. Fine at 90 rows; slow/timeout at millions. |
| **Instrumentation** (what happened, when) | ❌ Missing | We store only *final state* (e.g. `review_status`), not *actions*. We literally cannot measure our own #1 metric: "approved **without** edits". |
| **Frontend lists** | ⚠️ Partly | Dashboards show aggregates (fine), but lists (question bank, users, history) fetch **everything** with no pagination. |

**Bottom line:** the transactional foundation is sound. The **analytics + instrumentation layer** is the part that will not scale — and it happens to be exactly what the super-admin role now needs. So hardening it is not a detour; it is the prerequisite.

---

## 2. Findings (concrete, with locations)

### F1 — Analytics aggregate in Python, not in the database
Every stats endpoint follows the pattern `select(...) → pull all rows → loop & sum in Python`:
`platform_overview`, `institution_overview`, `platform_question_bank`, `platform_ai_monitoring` ([admin.py](../backend/app/api/admin.py)), `class_overview`, `class_monitor` ([teacher.py](../backend/app/api/teacher.py)), `student_stats`, `student_weak_analysis` ([student.py](../backend/app/api/student.py)).

Example: `platform_overview` pulls **all** profiles, quiz_sets, questions, variants, attempts, documents across **all** tenants into memory on every page load. It is already visibly slow at tiny scale.
**Analogy:** to get a class average we carry every answer sheet from the store room and add them by hand, every time — instead of asking the database for one number.

### F2 — `_count` counts by fetching every row
[admin.py](../backend/app/api/admin.py) `_count()` does `select("id")...execute()` then `len(...)`. Counting students = fetch all student-id rows. Should be a `count='exact', head=True` request that returns just the number.

### F3 — N+1 query loops
`list_quizzes` ([student.py](../backend/app/api/student.py)) calls `_ordered_approved_questions(variant_id)` **once per variant** (a query per row). `class_overview`/`class_monitor` loop over attempts. At scale these explode into thousands of round-trips.

### F4 — Indexes are single-column; analytics need composites
Existing indexes cover `tenant_id` and FKs well. Missing the composite indexes our filters actually use, e.g.:
- `quiz_sets(created_by)` and `quiz_sets(tenant_id, status)` — teacher/admin filters
- `quiz_attempts(variant_id, status)` and `quiz_attempts(student_id, status)` — every accuracy calc
- `attempt_answers(attempt_id, is_correct)` — weak-area/accuracy
- `questions(tenant_id, review_status)` composite (today they're two separate indexes)

*(Enrollments already has good indexes — no change there.)*

### F5 — No pagination on lists
[api.ts](../frontend/lib/api.ts) list calls return the full set (question bank, users, admins, history). A 100k-row table would choke the API payload and the browser.

### F6 — No event/action instrumentation *(the important one)*
The schema records **outcomes**, not **actions**. We keep `questions.review_status = approved`, but not:
- whether the teacher **edited** before approving (blocks the "approved without edits" KPI),
- how many **regenerations** it took,
- how long **review** took,
- where teachers **drop off** (generated-but-never-published),
- generation/extraction **failures** and which provider was used.

These are precisely the signals the **"Is the AI good enough?"** dashboard is made of. They can't be back-computed from current tables — they must be **recorded as they happen**.

### F7 — Cross-tenant platform scans grow with tenants
`platform_*` endpoints scan every tenant's data. One institute today; unbounded tomorrow.

---

## 3. Proposed foundation (right-sized — not over-engineered)

> Guided by our own generation-direction doc: **no** data warehouse, **no** streaming/Kafka, **no** LangChain/LangGraph, **no** premature materialised views. Plain Postgres + FastAPI, done correctly.

### P1 — Push aggregation into Postgres (views + RPC functions)
Move the math to the database. Two tools:
- **Views** for reusable shapes (e.g. `v_ai_quality`, `v_student_progress`).
- **RPC functions** (`create function ... returns table`, called via Supabase `.rpc()`) for parameterised aggregates (date range, tenant, filters).

The API then returns one small JSON instead of scanning tables in Python. This single change removes most of F1–F3.

### P2 — An append-only `events` table *(the backbone)*
```sql
create table events (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  actor_id     uuid,            -- who did it (null = system)
  actor_role   text,            -- denormalised for fast slicing
  event_type   text not null,   -- see taxonomy below
  subject_type text,            -- 'question' | 'quiz_set' | 'attempt' | 'document'
  subject_id   uuid,
  metadata     jsonb,           -- flexible: {type, difficulty, edited_fields, provider, latency_ms, score_pct, ...}
  created_at   timestamptz not null default now()
);
create index idx_events_tenant_time on events(tenant_id, created_at desc);
create index idx_events_type_time   on events(event_type, created_at desc);
create index idx_events_subject      on events(subject_type, subject_id);
-- RLS: super_admin reads all; staff read own tenant; inserts server-side only.
```

**Event taxonomy (v1)** — enough to power the AI-quality north star:
| Event | Key metadata | Powers |
|---|---|---|
| `question.generated` | type, difficulty, cognitive_level, subject_id, provider, batch_id | volume, mix, provider usage |
| `question.edited` | edited_fields[] | **"approved without edits"**, weak types |
| `question.approved` | was_edited (bool) | approval rate, as-is rate |
| `question.rejected` | — | rejection rate |
| `question.regenerated` | — | rework rate |
| `quiz.published` | quiz_set_id | teacher funnel completion |
| `attempt.submitted` | score_pct, variant_id, subject_id | student outcomes/trends |
| `document.uploaded` / `document.extraction_failed` | file_type, error | funnel top, failure health |
| `generation.failed` | provider, error | system health, fallback usage |

Why append-only events scale: writes are cheap and never contended; reads are time-ranged and indexed; old data can be rolled up or archived. Every future institute and every future metric plugs into the same stream.

### P3 — Daily rollups *(defer until needed)*
When events themselves get large, add a `metrics_daily(tenant_id, date, metric, dims jsonb, value)` table refreshed by a scheduled job (Supabase cron), so trend charts read pre-aggregated rows. **Not now** — P1+P2+indexes carry us a long way. Listed so the path is known.

### P4 — Add the composite indexes from F4.

### P5 — Pagination everywhere lists appear
Cursor/keyset pagination (`created_at, id`) via Supabase `.range()`; frontend uses "load more"/infinite scroll. Counts via `count='exact', head=True` (fixes F2).

---

## 4. How the "Is the AI good enough?" cockpit maps onto this

| Cockpit insight | Reads from | New instrumentation needed |
|---|---|---|
| Approval rate, **as-is vs edited**, rejected, regenerated | `events` (`question.*`) via RPC | ✅ yes (F6) |
| Quality by type / difficulty / subject, trended | `events` + `v_ai_quality` | ✅ |
| Teacher funnel upload→generate→review→publish + drop-off | `events` | ✅ |
| Student improvement over time | `attempt.submitted` events + existing `attempt_answers` | partial |
| Generation/extraction failures, provider fallback | `events` (`*.failed`) | ✅ |
| Content coverage / weightage usage | existing tables (DB aggregation) | ❌ (P1 only) |

The cockpit is essentially **"read the event stream through good SQL."** That's why the foundation comes first.

---

## 5. Suggested sequencing (phases)

- **Phase 0 — Instrumentation foundation:** create `events` table + RLS; add a tiny server-side `log_event(...)` helper; emit events from the existing generate / review (approve/edit/reject/regenerate) / publish / attempt / upload paths. *(No user-visible change yet; starts collecting truth.)*
- **Phase 1 — DB-side aggregation + indexes:** add composite indexes; convert the heaviest endpoints (`platform_overview`, `class_overview`, `student_stats`) to Postgres views/RPC; fix `_count`.
- **Phase 2 — The AI-quality cockpit:** build the super-admin "Is the AI good enough?" dashboard on top of the events + RPC.
- **Phase 3 — Pagination pass:** lists → cursor pagination + frontend load-more.
- **Phase 4 (later, only if needed):** daily rollups for very large event volumes.

Each phase is independently shippable and reversible.

---

## 6. Non-goals (deliberately NOT doing)
Data warehouse • streaming/Kafka • microservices • LangChain/LangGraph • materialised views before events prove insufficient • rewriting the transactional schema (it's fine).

---

## 7. Risks & notes
- **Events add write overhead** — negligible (one indexed insert per action); wrap in the service layer so a failed log never breaks the user action.
- **RLS on `events`** — must mirror existing policies (super_admin all; staff own tenant; inserts server-side via service role).
- **Backfill** — historical actions can't be recovered (we didn't record them). Metrics that need events start accumulating from go-live; document-derived metrics (coverage, current approval status) work retroactively.
- **Migrations** — additive only (new table, new indexes, new functions). No destructive changes; safe to run alongside the running app.

---

## 8. Open questions for you
1. **Scale target:** what's the realistic 12–18 month size (institutes, students, questions, attempts)? It decides whether Phase 4 rollups matter soon or much later.
2. **Instrumentation depth:** for edits, is a boolean `was_edited` + `edited_fields[]` enough, or do you also want before/after snapshots (heavier, but enables "what do teachers change")?
3. **Priority order:** happy with Phase 0 → 1 → 2, or do you want a first visible AI-quality screen sooner (Phase 2 partially, on current data, with the known limits)?
