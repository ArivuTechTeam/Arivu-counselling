# Documentation map

Use this page before relying on an older design or progress document. Current
code remains the final source of truth.

## Current operational references

- [`PROJECT-TECHNICAL-DOCUMENT.md`](PROJECT-TECHNICAL-DOCUMENT.md) — overall
  architecture and product behavior.
- [`current-ai-document-workflow.md`](current-ai-document-workflow.md) — current
  document detection, topic analysis, provider routing, retry/resume, quiz
  generation, verification, and cost controls.
- [`llm-prompts.md`](llm-prompts.md) — prompt contracts and provider selection.
- [`chunked-generation-architecture.md`](chunked-generation-architecture.md) —
  implemented durable document-analysis and generation-job architecture.
- [`deploy-runbook.md`](deploy-runbook.md) — deployment and production
  environment variables, including the separate Railway API and faculty worker.
- [`dashboard-state-persistence.md`](dashboard-state-persistence.md) — what UI
  state survives a refresh and what must never be stored.
- [`personal-data-audit.md`](personal-data-audit.md) — personal-data handling.
- [`SCALABILITY-RELEASE-A-B-README.md`](SCALABILITY-RELEASE-A-B-README.md) —
  current 10-institution scalability plan, A1 capacity tooling/runbook, release
  gates, and the boundary between implemented tooling and pending staging proof.

## Current production snapshot

Verified on 28 September 2026:

- PR #66 was merged to `main` at `f5aa0f1`. GitHub `Repository checks` passed,
  including the backend, frontend, database-guarantee, and public smoke-test
  jobs. Vercel also reported a successful production deployment for that
  revision.
- Railway API deployment `ee42e89c-11e9-4685-a8d7-96e2be358ab7` reported
  `SUCCESS` with a running instance after the feature-switch redeploy, and the
  public `/health` endpoint returned HTTP 200. The worker was not changed by PR
  #66 and its last observed successful deployment remains `8dfc43bc`.
- The operator reported migration 74 applied, so the reported production
  migration level is now through 74. This documentation pass did not query the
  Supabase migration history directly.
- Railway directly reported `QUIZ_REUSE_ENABLED=true`,
  `REJECTED_PURGE_ENABLED=true`, `EXTRACTION_BLUEPRINT_ENABLED=true`, and
  `REGENERATE_SET_ENABLED=true` on the production API service. The last three
  remain `false` by default in code and are API-only switches.

This snapshot proves deployment and basic public availability, not the new
authenticated teacher/student workflows, worker recovery, backup/restore, or
200/500-user capacity checks. Use the deploy runbook and Release A checklist
for those gates.

## Historical material

Files under `akbar_changelog/` and `pavyaa_changelog/` are dated records. Their
provider names and “before/after” statements describe the code at that date and
must not be treated as the current architecture. The quarterly report, original
scope, RAG assessment, OCR research, build plans, and dated test evidence are
also historical decision inputs unless their header explicitly says otherwise.

When a historical file conflicts with the current references above, use the
current references and verify against `backend/app/lib/config.py`,
`backend/app/services/llm/`, and the relevant service.
