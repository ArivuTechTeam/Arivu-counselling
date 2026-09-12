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

Deployment and security details are documented in `docs/deploy-runbook.md` and
`docs/api-security-hardening.md`. The collection, disclosure, processor and
deletion map is in `docs/personal-data-audit.md`.
