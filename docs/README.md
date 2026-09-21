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
  environment variables.
- [`dashboard-state-persistence.md`](dashboard-state-persistence.md) — what UI
  state survives a refresh and what must never be stored.
- [`personal-data-audit.md`](personal-data-audit.md) — personal-data handling.

## Historical material

Files under `akbar_changelog/` and `pavyaa_changelog/` are dated records. Their
provider names and “before/after” statements describe the code at that date and
must not be treated as the current architecture. The quarterly report, original
scope, RAG assessment, OCR research, build plans, and dated test evidence are
also historical decision inputs unless their header explicitly says otherwise.

When a historical file conflicts with the current references above, use the
current references and verify against `backend/app/lib/config.py`,
`backend/app/services/llm/`, and the relevant service.
