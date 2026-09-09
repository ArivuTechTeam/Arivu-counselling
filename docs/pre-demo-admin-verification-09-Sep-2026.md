# Pre-Demo Super Admin and Institution Admin Verification — 9 Sep 2026

## Environment

- Branch: `fix/pre-demo-super-institution-admin`
- Scope: local branch only; not pushed to GitHub
- Local frontend: `http://localhost:3001`
- Local backend: `http://localhost:8001`
- Backend health: `200 {"status":"ok"}`
- Frontend login page: HTTP 200

## Issues fixed

### High — Platform totals silently truncated at 1,000 database rows

- Before: Platform overview, stats, question bank, AI monitoring, tenant list,
  and admin list used one unbounded PostgREST request per table. Supabase can
  cap those responses at 1,000 rows, producing plausible but incomplete demo
  metrics.
- After: A shared deterministic pagination helper reads all result pages while
  retaining endpoint filters. Platform-wide calculations now receive the full
  collection.

### High — AI Monitoring displayed the wrong published-quiz total

- Before: The page counted `quiz.published` events, but the publish endpoint
  never emitted that event. The configured data had 13 published quiz rows and
  zero publish events, so Question Quality displayed zero.
- After: The current-state KPI is read from `quiz_sets.status='published'` and
  now matches Platform Overview. Publishing also records the event for future
  historical activity analysis.

### High — Provisioned role and password lock were written separately

- Before: `_set_provisioned_profile` promoted the role/tenant first and set
  `must_change_password` in a second request, allowing a partial state if the
  second write failed.
- After: Tenant, role, name, and mandatory password-change flag are written in
  one profile update for institution admins and teachers.

### High — Failed provisioning cleanup was silent

- Before: Auth cleanup errors were swallowed. Institution onboarding then
  deleted the tenant without guarding or reporting rollback failure.
- After: Auth cleanup is checked. A failed tenant deletion triggers immediate
  tenant deactivation and a clear operator-review error instead of reporting a
  normal validation failure. Teacher and institution-admin creation use the
  same checked cleanup behavior.

### Medium — Institution Admins page was only a redirect

- Before: `/dashboard/super-admin/admins` redirected to Institutions even
  though admin management was a required demo page.
- After: The route renders the existing fully wired Admin Manager and appears
  in the super-admin sidebar.

### Medium — Question Bank page was unreachable

- Before: `/dashboard/super-admin/courses` redirected to the dashboard and no
  frontend used the implemented platform question-bank endpoint.
- After: The sidebar links to a real Platform Question Bank page with totals,
  institution attribution, per-course coverage, loading, failure, and empty
  states.

### Medium — Repeated review events distorted AI quality

- Before: A question approved and later rejected was counted once in both
  states, inflating the reviewed denominator and retaining an obsolete
  approval.
- After: Review events are folded to each question's latest timestamped
  decision before approved/rejected and kept-as-is metrics are calculated.

## Read-only end-to-end verification

Short-lived locally signed role tokens were used only against the local
FastAPI server. The server loaded the real authoritative profiles and current
configured database data.

- Super admin: platform overview, platform stats, tenants, admins, question
  bank, and AI monitoring all returned 200.
- Institution admin: overview, analytics, teachers, courses, quizzes, and
  teacher analytics all returned 200.
- Role boundary: super admin was rejected from institution-admin overview;
  institution admin was rejected from platform overview.
- Cross-page consistency: institution teacher, course, quiz-set, published
  quiz, and accuracy values matched between overview, analytics, and list APIs.
- Platform consistency: published-quiz count now matches between Platform
  Overview and AI Monitoring.
- No unexpected backend 4xx/5xx errors were present in local container logs;
  the two observed 403 responses were the intentional cross-role checks.

## Write-path verification boundary

The code paths for onboarding, admin creation/removal, teacher creation, and
profile promotion were inspected. Super-admin onboarding, admin
creation/removal, trigger behavior, and profile promotion were regression-tested
locally with mocks. A
real create/login/remove run was not executed because this checkout is wired
to a shared remote Supabase project rather than a disposable local/staging
database. Creating and deleting temporary tenants and Auth users there requires
explicit confirmation that this exact project may be mutated for the test.

## Automated verification

- Backend: 77 tests passed, plus 60 subtests.
- Frontend lint: passed with no warnings or errors.
- Frontend production build: passed; all 36 routes generated.
- Docker backend and frontend: built, started, and healthy.
- Added regressions for PostgREST pagination, one-write profile provisioning,
  current-state published metrics, the super-only platform guard, onboarding
  with a first admin, and administrator removal.
