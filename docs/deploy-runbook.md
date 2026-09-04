# Deploy Runbook — quiz-generator-v1

A practical, repeatable guide to getting this app live. Two deployables:
**frontend (Next.js → Vercel)** and **backend (FastAPI → a host that runs
uvicorn)**, both talking to one **Supabase** project.

> Backend note: there is no `vercel.json`, so the FastAPI backend is **not**
> set up for Vercel serverless. It runs on a host that runs `uvicorn` directly
> (zero adapter work) — **Render** and **Railway** both work; **confirmed live
> on Railway as of 2026-09-04** (verified in the Railway dashboard: service
> `quiz-generator`, project `ExamApp`, environment `production`, domain
> `quiz-generator-production-7461.up.railway.app`). Render remains a valid
> alternative if you're setting this up fresh, but isn't what's deployed today.
> The frontend goes on Vercel.

---

## 0. One-time: get the code on GitHub `main`

Merge your work to `main` first (see `docs/merge-workflow.md`).

- **Frontend (Vercel):** builds automatically from GitHub via Vercel's
  standard integration (not independently re-verified this session — confirm
  in the Vercel dashboard if unsure).
- **Backend (Railway): does NOT auto-deploy from GitHub.** Confirmed
  2026-09-04 via `railway status --json` → the service's `"source"` field is
  `null`. Merging to `main` alone does nothing to the backend — after
  merging, you must manually deploy (see Step 2).

---

## 1. Database (Supabase SQL Editor)

These files live in `migrations/` at the project root. Run these **once, in
order**, top-to-bottom (skip any already applied). Note there is **no
migration 03** — the seed library was removed; `04` drops it.

```
schema.sql
migration-01-enrollments.sql
migration-02-events.sql
migration-04-drop-seed-library.sql
migration-05-practice.sql
migration-06-revised-topics.sql
migration-07-challenges.sql
migration-08-exam-config.sql
```

(Our live Supabase already has 01–08 applied; this list is for a fresh project.)

---

## 2. Backend → Railway (confirmed) or Render (also supported)

- **Build:** Docker, via `backend/Dockerfile` (confirmed via `railway status
  --json` → `"builder": "DOCKERFILE"`). The Dockerfile itself runs `pip
  install -r requirements.txt` — there is no separate dashboard build command.
- **Root directory:** there is **no** dashboard "root directory" setting for
  this service (confirmed `"rootDirectory": null`). Instead, every deploy
  must scope the build to `backend/` at the CLI level:
  `railway up backend --path-as-root --service quiz-generator` (wrapped by
  `scripts/deploy.sh` — use that script rather than a bare `railway up`).
  Running `railway up` from the repo root without `--path-as-root` fails
  ("Railpack could not determine how to build the app").
- **Start command:** leave the Railway dashboard's custom Start Command
  **blank** so it falls back to the Dockerfile's own `CMD`. A leftover custom
  override (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, predating the
  Dockerfile) caused a production outage on 2026-09-04: for a Docker-built
  service, Railway passes a custom Start Command straight to the container
  without shell expansion, so uvicorn received the literal string `$PORT`
  instead of a number and crash-looped (every request 502'd). Cleared in the
  dashboard, and `backend/Dockerfile`'s `CMD` now uses shell form
  (`CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`) so this
  can't regress even if Railway ever re-applies a plain string command.
- **Python:** 3.12 (set by `FROM python:3.12-slim` in the Dockerfile).

**Environment variables** (from `backend/.env.example`) — confirmed present
on the live Railway service as of 2026-09-04 (existence checked in the
dashboard; values themselves not re-verified this session):

| Var | What |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | anon public key |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key (server-only, **secret**) |
| `SUPABASE_JWT_SECRET` | for verifying JWTs (ES256 via JWKS) |
| `FRONTEND_ORIGIN` | the deployed **frontend URL** (for CORS) |
| `GEMINI_API_KEY` | quiz generation (primary) |
| `DEEPSEEK_API_KEY` | quiz generation (fallback) |

**Deploying a change (Railway):** merge to `main` first, then run
`scripts/deploy.sh` from `main` (or `railway up backend --path-as-root
--service quiz-generator` directly) — merging alone does not deploy, see
Step 0. On first-ever setup (fresh Render project, or a from-scratch Railway
project), copy the **backend URL** after the first deploy (e.g.
`https://…onrender.com`); for the current Railway deploy, see the live URL in
Notes/gotchas below.

---

## 3. Frontend → Vercel

- **Root directory:** `frontend`
- **Framework:** Next.js (auto-detected) · Build: `next build`

**Environment variables** (from `frontend/.env.local.example`):

| Var | What |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon public key |
| `NEXT_PUBLIC_DEFAULT_TENANT_ID` | ArivuPro tenant id (signup default) |
| `NEXT_PUBLIC_API_BASE_URL` | the deployed **backend URL** from step 2 |

→ After it deploys, copy the **frontend URL**.

---

## 4. Cross-wire the two

1. Set backend `FRONTEND_ORIGIN` = the Vercel frontend URL → redeploy backend.
2. Set frontend `NEXT_PUBLIC_API_BASE_URL` = the backend URL → redeploy frontend.

(They point at each other; CORS on the backend already allows the configured
origin, plus any `localhost` port for dev.)

---

## 5. Post-deploy smoke test (5 minutes)

1. Open the frontend URL → **/login** loads.
2. Log in as super-admin → Overview + Question Quality load.
3. Log in as a student → Dashboard → **Smart Quiz** → take & submit → score shows.
4. **Daily Challenge** → start → streak ticks. **Exam Simulator** → timer counts down.
5. **Leaderboard** shows your course. **Revision** two tabs work.

If a page 500s, check the backend logs and that all env vars are set + migrations run.

---

## Notes / gotchas

- **`next build` runs ESLint and fails on errors** — always run `pnpm build`
  locally before deploying, not just `tsc` (tsc misses lint-level errors).
- **Never commit `.env` / `.env.local`** — only the `.example` files are tracked.
- **Heavy routes** (attempt/practice/class-monitor ≈ 640 kB First Load) pull in
  recharts + the PDF renderer. Fine for now; a future win is lazy-loading the PDF
  and chart bundles.
- **Free-tier note:** Render/Railway free tiers sleep on idle (first request is
  slow to wake) — acceptable for a demo, upgrade for real usage.
- **Live backend URL:** `https://quiz-generator-production-7461.up.railway.app`
  (Railway dashboard, verified 2026-09-04). This is where Vercel's
  `NEXT_PUBLIC_API_BASE_URL` should point in production — check the Vercel
  dashboard's env vars, not `frontend/.env.local`, to confirm what's actually
  configured there.
