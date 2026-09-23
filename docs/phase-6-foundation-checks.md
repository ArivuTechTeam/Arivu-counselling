# P6.0 — Foundation checks: route/execution/flag inventory + timeout root cause

**Item 5 of P6.0.** Purpose: record the *actual* generation/extraction execution paths, the flags that route them, and the reproduced root cause of the "generation runs forever / times out" report — grounded in code and one observed live incident, with no speculative timeout claims. This is the baseline P6.1+ builds on.

## 1. Active flags (verified)

From `backend/.env` + `app/lib/config.py` defaults on the reviewed branch:

| Flag | Value | Effect |
| --- | --- | --- |
| `FACULTY_JOBS_ENABLED` | **true** | Durable separate-process worker path is available; the UI routes final generation/extraction through it. |
| `FIGURE_ATTACH_ENABLED` | **true** | Figure extraction + attachment active (Phases 1–2). |
| `QUIZ_REUSE_ENABLED` | **true** | Safe-reuse release locks + atomic publish (migration 51 after integration renumbering). |
| `FACULTY_WORKER_STALE_SECONDS` | 120 (default) | Backlog older than this with no live worker lease = "stalled" (P6.0 item 2). |
| `AI_LOG_RAW_RETENTION_DAYS` | 30 (default) | Raw AI-log payloads blanked after 30 days (P6.0 item 4). |
| `CHUNKING_TRIGGER_CHARS` / `GENERATION_MAX_TEXT_CHARS` | 100000 (default) | Documents beyond this use the chunked map-reduce analysis path. |

## 2. Execution inventory — there are TWO parallel background mechanisms

The single most important fact: **final quiz generation can run in two different places**, and which one runs depends on the flag + which endpoint the UI calls.

| Flow | Endpoint | Execution | Persistence table | Recovery if the process dies |
| --- | --- | --- | --- | --- |
| Topic analysis (outline / map-reduce) | `POST /quiz-sets/analyze` | **In-process daemon thread** (`generation_jobs.py` `GenerationJobRunner`) | `quiz_generation_jobs` | Job row is resumable, but a daemon thread is **not** multi-process safe; an API restart mid-run relies on retry. |
| Final generation — **durable path** | `POST /faculty-jobs` (kind `blueprint` / `analysis_quiz`) | **Separate worker process** (`faculty_worker.py`), lease + heartbeat + checkpoint | `faculty_jobs` | DB lease recovers the job when a worker is running. **Requires the worker process to exist.** |
| Final generation — **in-process path** | `POST /quiz-sets/generate-blueprint/async`, `/generation-jobs/{id}/generate-async` | **In-process daemon thread** → `generate_blueprint_quiz` (synchronous, no `persist_result`) | `quiz_generation_jobs` | Daemon thread; lost on API restart (job row records a retryable failure). |
| Final generation — **synchronous** | `POST /quiz-sets/generate`, `/generate-blueprint`, `/generation-jobs/{id}/generate` | **Inline in the request** (blocks) | direct write | None — bounded by the request timeout (frontend 15 min; each provider call capped 180–600 s). |
| Extraction (import) | `POST /extraction/extract` (background) or `POST /faculty-jobs` (kind `extraction`) | Durable worker when enabled; else in-process | `faculty_jobs` / `ai_extraction_jobs` | Same as durable path above. |

Frontend timeouts (`frontend/lib/api.ts`): generation/upload **15 min**, extraction **5 min**; on `request_timeout`/`network_error` the UI **retries as a background job** and then polls.

## 3. Reproduced timeout — root cause (observed, not theorized)

**Report:** "generated a quiz, waited >10 min, no quiz, backend kept running."

**Observed evidence (live DB, 21-Sep):** the newest `faculty_jobs` row was
`kind=analysis_quiz, status=queued, attempts=0, lease_expires_at=null, updated_at==created_at` — i.e. **enqueued but never claimed**. The topic-analysis `quiz_generation_jobs` for the same session had already `completed` (in-process). So analysis finished, final generation was enqueued on the **durable faculty path**, and then nothing processed it.

**Root cause:** with `FACULTY_JOBS_ENABLED=true`, final generation is enqueued to `faculty_jobs`, which **only the separate `faculty_worker` process can execute**. That worker was **not running** (a live process check returned none). The job sat in `queued` indefinitely; the UI polled forever; uvicorn "kept running" because it was never doing the work. **This was an operational gap (absent worker), not a code timeout or an infinite loop** — the LLM client and generation retries are all bounded (single provider pass; per-call timeouts 180 s / 600 s; one correction + one repair attempt).

**Confirmation:** starting the worker (`scripts/start-faculty-worker.ps1`) caused it to claim the job within seconds (`status=running`, live lease) and the quiz completed.

## 4. What now prevents a silent recurrence (built in P6.0)

- **Detection (item 2):** `worker_health` reports `stalled` when a queued/orphaned backlog older than `FACULTY_WORKER_STALE_SECONDS` has no live worker lease — surfaced by the deployment preflight and `GET /api/v1/platform/worker-health` (super-admin).
- **Auto-restart (item 2):** `scripts/supervise-faculty-worker.ps1` runs the worker in a restart-on-crash loop locally; production must run the worker as a managed service with its own restart policy.

## 5. Residual risks / explicitly unproven

- **Worker liveness in production is not proven here.** The durable path is only as reliable as the deployed worker service. Treat "worker is running + heartbeating" as a deploy requirement and alert on `worker-health` = `stalled`.
- **Two mechanisms coexist** (durable faculty path vs. in-process daemon path). This is a consolidation candidate for a later phase; for now, the durable path is the intended one when `FACULTY_JOBS_ENABLED=true`, and the in-process paths remain as fallback/legacy.
- **Topic analysis runs in-process** (daemon thread), so it is not restart-safe on its own; a mid-analysis API restart depends on retry.
- **Synchronous endpoints** (`/generate`, `/generate-blueprint`) can still block up to the request timeout; they are not the UI's primary path when the durable queue is enabled.

## 6. P6.0 status

| Item | Status |
| --- | --- |
| 1 — Approve-all covers valid pending/flagged | Done |
| 2 — Worker supervision (detect stalled + auto-restart) | Done |
| 3 — Figure storage hygiene (erase on account deletion; re-analyze already idempotent) | Done |
| 4 — AI-log raw-payload redaction after 30 days | Done |
| 5 — This inventory + timeout root cause | Done |

Next: **P6.1 — batches + assignments** (phase 2 of 8).
