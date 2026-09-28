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

Verified on 26 September 2026:

- PR #65 was merged to `main` at `6dd08cd`. The resulting GitHub `Repository
  checks` run passed, including database migration harnesses, backend tests,
  frontend audit/lint/unit/build checks, and the public Playwright smoke suite.
- Vercel reported a successful production deployment for `6dd08cd`. The public
  institution login route returned HTTP 200 with the expected CSP, HSTS,
  clickjacking, MIME-sniffing, and framework-header protections.
- Railway API deployment `a4daadf2-d2f2-4dba-99d3-4ef7cde68c7c` reported
  `SUCCESS`, and `/health` returned HTTP 200. The worker was not redeployed in
  that operation because the merged remediation did not change worker runtime
  code or its job contract; its last observed deployment remains `8dfc43bc`.
- The operator reported migrations through 73 applied. PR #65 required no new
  database migration, and none was applied as part of this deployment.
- The repository now includes migration 74 for role-aware support. It has not
  been reported applied and must be run before deploying the matching API and
  frontend.

This snapshot proves deployment and basic public availability, not the open
authenticated-role, worker-recovery, backup/restore, or 200/500-user capacity
checks. Use the deploy runbook and Release A checklist for those gates.

## Historical material

Files under `akbar_changelog/` and `pavyaa_changelog/` are dated records. Their
provider names and “before/after” statements describe the code at that date and
must not be treated as the current architecture. The quarterly report, original
scope, RAG assessment, OCR research, build plans, and dated test evidence are
also historical decision inputs unless their header explicitly says otherwise.

When a historical file conflicts with the current references above, use the
current references and verify against `backend/app/lib/config.py`,
`backend/app/services/llm/`, and the relevant service.
