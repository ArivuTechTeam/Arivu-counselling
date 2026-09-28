# Audit remediation — 21 Sep 2026

This records the disposition of the findings in the 21 September full audit.
It distinguishes implemented fixes from accepted or separately-scoped work so
future reviews do not repeatedly report the same observations as new defects.

## Fixed on `fix/audit-remediation-2026-09-21`

- Student answer autosaves serialize requests and automatically retry unsaved
  revisions with bounded backoff. This avoids both the reported no-retry state
  and stale overlapping writes.
- Initial unauthenticated navigation preserves validated, same-origin
  `/dashboard` destinations through login. The post-login role guard remains
  authoritative.
- The super-admin API-log detail sheet uses the shared accessible `Dialog`, with
  focus containment/restoration, Escape handling, backdrop dismissal, and dialog
  semantics.
- Docker Compose forwards every runtime variable in `backend/.env.example`
  except `SEED_STUDENT_EMAIL`, which belongs only to a standalone seed script.
- All document-driven generation/topic prompts share an explicit boundary that
  treats uploaded text as untrusted data rather than model instructions.
- API-log responses and document archive responses now have Pydantic response
  models. Active guidance no longer falsely claims every legacy endpoint already
  has one.
- `pyq_parser.py` is labelled as a legacy, intentionally-unwired experiment;
  `quiz_extraction.py` remains the supported production path.

## Accepted or separately scoped

- Historical note: production CSP retained `script-src 'unsafe-inline'` at the
  time of this audit because Next.js
  emits framework bootstrap scripts that require it in this static deployment.
  Removing it safely requires a nonce-based dynamic rendering/middleware project
  and production browser verification. `object-src 'none'`,
  `frame-ancestors 'none'`, restrictive connection/image origins, and the absence
  of production `unsafe-eval` remain in force. The nonce-based implementation
  was subsequently added; deployment verification remains required.
- Legacy dictionary-returning routes are migrated to Pydantic when touched. A
  bulk conversion of dozens of unrelated endpoints is deliberately excluded
  from this bug-fix branch because it changes response filtering and can break
  clients. New endpoints must declare response models.
- The audit found no concrete tenant-isolation defect. Its 255-call scan remains
  review evidence, not a formal certification.
- Railway, Vercel, Supabase migration state, and provider health require a live
  deployment audit and are not inferred from repository tests.
