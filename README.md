# Quiz Generator

## Secret safety before deployment

Copy `.env.example` to `.env`, then replace every placeholder through your
local environment or deployment platform's encrypted secret store. Never
commit `.env` files. Browser code may receive only the `NEXT_PUBLIC_*` values
listed in the template: the Supabase URL and anon key, tenant identifier,
backend URL, and optional non-secret development account labels/emails.

The Supabase anon key is public and is safe only while Row Level Security is
enabled on every exposed table. `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_JWT_SECRET`, `DEEPSEEK_API_KEY`, and `GEMINI_API_KEY` are server-only
secrets and must never use a `NEXT_PUBLIC_` or `REACT_APP_` prefix.

> **Git history warning:** If any credential was ever hardcoded or committed,
> removing it from the current files is not enough. Rotate every previously
> hardcoded secret immediately; the old value remains recoverable from Git
> history. This repository previously included a development-account password
> in `NEXT_PUBLIC_DEV_ACCOUNTS_JSON` inside
> `frontend/.env.local.example`; rotate any account that ever used that value.
> Purge history separately if required by your incident policy.

Environment templates:

- Root / Docker Compose: `.env.example`
- Backend: `backend/.env.example`
- Frontend: `frontend/.env.local.example`

Start with [`docs/README.md`](docs/README.md) for the current documentation
map. Deployment and security guidance live in
[`docs/deploy-runbook.md`](docs/deploy-runbook.md) and
[`docs/api-security-hardening.md`](docs/api-security-hardening.md); the
collection, disclosure, processor, and deletion map is in
[`docs/personal-data-audit.md`](docs/personal-data-audit.md). Migration 59 was
reported applied on 2026-09-24; the production AI-log raw-payload columns were
also verified absent that day. Railway production now has two services: the
public `quiz-generator` API and the private `quiz-generator-worker` for durable
faculty jobs. The obsolete `quiz-generator-retention` cron was deleted on
2026-09-24 after its code and target columns were removed. API and worker
deployments are independent; see the deploy runbook before updating either.

Local coding-assistant guidance is gitignored: Codex loads `AGENTS.md` and
`.codex/` when present; Claude Code uses `.claude/`. These files are not
included in a fresh clone unless copied over separately.
