# Super Admin End-to-End Audit — 9 Sep 2026

## Scope and method

This is a diagnosis-only audit of the `super_admin` backend routes, frontend
pages, API client, dashboard role guard, Supabase profile trigger, and the
current configured Supabase data. No application behavior was changed.

The audit used:

- Static tracing from each frontend page through `frontend/lib/api.ts` to its
  FastAPI route and Supabase queries.
- Review of `get_current_profile`, `_require_super`, `handle_new_user`,
  `_set_provisioned_profile`, `create_admin`, `remove_admin`, and
  `onboard_institution`.
- A read-only integrity check against the configured Supabase project. It read
  counts and identifiers only; it did not print credentials or personal data.
- Backend tests, frontend lint, and a production frontend build.

The configured database appears shared rather than an isolated disposable
staging database, so the audit did not create or delete a live institution or
administrator. The create/login/remove loop therefore remains to be verified
after the provisioning fixes below, using a dedicated staging tenant.

## Result

The role boundary is correctly wired and no current cross-tenant relationship
error was found. The super-admin area is not ready to be treated as fully
complete because two platform metrics can become or already are incorrect,
provisioning compensation is not reliable under partial failure, and the
platform question-bank/courses UI is not implemented.

## Confirmed working

1. Every audited platform endpoint calls `_require_super(profile)` before its
   data access. An `institution_admin`, teacher, or student cannot call these
   platform APIs successfully.
2. The frontend dashboard maps `super_admin` to
   `/dashboard/super-admin` and redirects a logged-in user away from another
   role's dashboard tree. Backend authorization remains the security boundary.
3. `list_tenants`, `list_admins`, `platform_stats`, `platform_overview`,
   `platform_question_bank`, and `platform_ai_monitoring` are intentionally
   cross-tenant reads. That is appropriate for `super_admin`.
4. `create_admin` validates that the requested tenant exists. `remove_admin`
   loads the target by immutable user ID, verifies that its current database
   role is `institution_admin`, and refuses self-removal.
5. Both `create_admin` and `onboard_institution` create the Auth user with
   protected `app_metadata.provisioned_by_backend=true`, then call the same
   `_set_provisioned_profile` helper with the selected tenant and
   `institution_admin` role. Both set `must_change_password=true` in Auth
   metadata and in the authoritative profile.
6. The Auth trigger is synchronous and inserts one profile row. For trusted
   backend provisioning it validates an active tenant, creates the initial
   profile, and the backend promotes that same row. It does not insert a second
   profile during `_set_provisioned_profile`.
7. A removed admin loses API access even if an old JWT remains in a browser:
   the Auth user is deleted and the cascading profile row disappears, while
   every protected request reloads the profile from the database.
8. Platform accuracy is weighted correctly for rows returned to the endpoint:
   `sum(clamped total_score) / sum(variant total_marks)` for graded attempts.
9. The Institutions page has real loading, failure, empty, onboarding, list,
   and institution-detail states. Admin creation/removal is functional through
   the embedded `AdminManager` on that page.
10. The current database integrity sample was clean: 3 tenants, 17 profiles,
    2 courses, 4 subjects, 9 chapters, 574 questions, 18 quiz sets, 18
    variants, 23 attempts, 18 documents, and 125 events produced zero unknown
    tenant IDs and zero tenant mismatches across the checked relationships.
    All 17 profiles had matching Auth users, including all 3 institution-admin
    profiles.

## Findings

### SA-01 — Platform aggregates silently stop at the PostgREST row limit

- Classification: **Confirmed**
- Severity: **High**
- Affected routes: `platform_stats`, `platform_overview`,
  `platform_question_bank`, `platform_ai_monitoring`, and eventually
  `list_admins`
- Root cause: These functions call unbounded `.select(...).execute()` queries
  and calculate totals in Python. Supabase projects return at most 1,000 rows
  per request by default. The code does not paginate these table reads.
- Impact: Once questions, events, attempts, profiles, or quiz sets exceed the
  API row cap, totals, accuracy, approval rate, activity, and per-institution
  metrics become silently incomplete. With 574 questions already present,
  `questions` is approaching that threshold.
- Proposed fix: Move aggregates into tenant-aware SQL views/RPCs using `count`,
  `sum`, and grouped queries, or add a shared deterministic range-pagination
  helper for every raw collection. Keep the project row cap low as Supabase
  recommends instead of increasing it to hide the issue.
- Reference: [Supabase select limits and range pagination](https://supabase.com/docs/reference/csharp/v0/select)

### SA-02 — AI Monitoring reports zero published quizzes while 13 are published

- Classification: **Confirmed**
- Severity: **High**
- Affected route/page: `platform_ai_monitoring` and Question Quality
- Root cause: `published_quizzes` is counted only from `quiz.published` events,
  but `publish_quiz_set` never writes `QUIZ_PUBLISHED`. Event logging is also
  documented as best-effort, so an event count cannot be the authoritative
  current published count.
- Evidence: The read-only database check found 13 current `quiz_sets` rows with
  `status='published'` and 0 `quiz.published` events. The Platform Overview
  therefore shows 13 while AI Monitoring shows 0.
- Proposed fix: Read the current published total from `quiz_sets`. Separately
  add a publish event for historical throughput and label that event metric by
  period. Do not use the best-effort ledger as the source of truth for current
  state.

### SA-03 — Provisioning rollback can leave a partial tenant or account

- Classification: **Probable**
- Severity: **High**
- Affected flows: `create_admin` and `onboard_institution`
- Root cause: Provisioning spans separate tenant insert, Auth user insert,
  profile updates, and compensation calls. `_delete_auth_user_quietly` swallows
  deletion failures. Onboarding then attempts a tenant deletion without
  checking its result or protecting that rollback. Because profiles reference
  tenants without `ON DELETE CASCADE`, a remaining profile can make the tenant
  rollback fail.
- Impact: A request can report failure while leaving an Auth user, profile, or
  tenant behind. A retry may then fail on duplicate email/subdomain, and in the
  worst case an account may exist even though the UI said it was not created.
- Proposed fix: Put tenant/profile provisioning in one security-definer RPC or
  implement explicit, verified compensation states. If Auth cleanup fails,
  disable/quarantine the account and return an operational incident ID. Add
  fault-injection tests for failure after each step.

### SA-04 — The platform Courses/Question Bank feature has no usable frontend

- Classification: **Confirmed**
- Severity: **Medium**
- Affected files: `super-admin/courses/page.tsx`, `getQuestionBank`, and
  `platform_question_bank`
- Root cause: The Courses page only redirects to the dashboard. The API client
  and backend implement a global question-bank response, but no frontend page
  calls `getQuestionBank`, and the sidebar contains no route for it.
- Impact: A built backend capability is unreachable, and the route listed as a
  super-admin feature is a 151-byte redirect stub.
- Proposed fix: Either build a Question Bank/Courses page from the existing API
  and add it to navigation, or remove the dead route and API surface if this is
  intentionally out of scope.

### SA-05 — Institution detail is a summary, not the requested full picture

- Classification: **Confirmed**
- Severity: **Medium**
- Affected page: `super-admin/institutions/[id]/page.tsx`
- Root cause: The page downloads the entire platform overview, finds one row in
  the browser, and displays eight totals. It has no institution admins, course
  health, recent quizzes, review backlog, or teacher drill-down.
- Impact: A super admin can identify a tenant but cannot investigate it from
  the detail page. The page explicitly tells the user to sign in as an
  institution administrator for management.
- Proposed fix: Add a super-only tenant-detail endpoint scoped by path tenant
  ID and render read-only operational details. Keep role separation; do not
  impersonate an institution admin unless an audited impersonation feature is
  deliberately designed.

### SA-06 — AI behavioral quality can count one question in conflicting states

- Classification: **Confirmed**
- Severity: **Medium**
- Affected route: `platform_ai_monitoring`
- Root cause: Approval and rejection events are accumulated into independent
  sets. If a question is approved and later rejected, it exists in both sets;
  `reviewed_n = approved_n + rejected_n` counts it twice and its old approval
  can still contribute to kept-as-is statistics.
- Impact: Quality rates diverge from the current question state and can be
  distorted by repeated review actions.
- Proposed fix: Fold events per question in timestamp order into a latest-state
  model, or query current review state for state KPIs and reserve event counts
  for clearly labeled action/activity metrics.

### SA-07 — Platform totals include inactive institutions

- Classification: **Confirmed code behavior; product intent is ambiguous**
- Severity: **Low**
- Affected route: `platform_overview`
- Root cause: The response exposes `active_institutions`, but teachers,
  students, admins, content, attempts, and accuracy aggregate every tenant,
  including inactive tenants.
- Current impact: None in the checked data because all 3 tenants are active.
- Future impact: After an institution is deactivated, headline operational
  numbers can still include its historical accounts and activity without
  saying so.
- Proposed fix: Decide and label whether headline metrics mean all-time
  platform or active institutions. If operational, filter all headline metrics
  consistently to active tenant IDs while retaining separate historical totals.

### SA-08 — Standalone Admins route is a redirect and admin management is duplicated

- Classification: **Confirmed**
- Severity: **Low**
- Affected page: `super-admin/admins/page.tsx`
- Root cause: The standalone route redirects to Institutions, where the full
  admin manager is embedded below the institution table.
- Impact: Direct bookmarks do not open a dedicated Admins view, and the long
  Institutions page combines two management jobs. Functionality itself is
  present.
- Proposed fix: Choose one information architecture: make `/admins` render
  `AdminManager` and link it in navigation, or delete the legacy route and
  clearly keep admin management within institution detail.

### SA-09 — No automated tests cover the super-admin contract

- Classification: **Confirmed**
- Severity: **Medium**
- Affected areas: all platform endpoints and provisioning paths
- Root cause: The 71-test backend suite has role/security tests for other
  features but no tests for `platform_overview`, `platform_question_bank`,
  `platform_ai_monitoring`, `onboard_institution`, `create_admin`, or
  `remove_admin`.
- Impact: Aggregation drift, missing event wiring, guard regressions, and
  partial rollback behavior can reach main without CI detecting them.
- Proposed fix: Add focused service-client mocks for super-only rejection,
  aggregate math, >1,000 row pagination/RPC behavior, profile flags, tenant
  attribution, deletion, and every provisioning failure boundary.

### SA-10 — Three Auth identities currently have no profile

- Classification: **Confirmed observation; cause is a hypothesis**
- Severity: **Low / operational cleanup**
- Evidence: The configured project has 20 Auth identities and 17 profile rows;
  all 17 profiles have an Auth match, while 3 Auth identities have no profile.
- Likely cause: Abandoned or incomplete OAuth onboarding can intentionally
  leave a new identity without a profile until course selection finishes. The
  audit did not inspect personal data, so this cause was not proven.
- Impact: These users are authenticated by Supabase but receive `403 No profile
  found` from application APIs and cannot enter a dashboard.
- Proposed fix: Add a scheduled cleanup or resumable onboarding report for
  profile-less Auth identities. Confirm age/provider before deletion.

### SA-11 — Tenant consistency relies on application code for several foreign keys

- Classification: **Probable risk; current data is clean**
- Severity: **Medium**
- Affected relationships: subject→course, chapter→subject,
  question→chapter, variant→quiz set, attempt→variant/student
- Root cause: These references use single-column IDs while each child also has
  a separate `tenant_id`; the database does not enforce that both sides share
  a tenant. Some newer relationships such as `teacher_subjects` do use
  composite tenant-aware foreign keys.
- Impact: A future service-role bug or manual import could create a valid
  foreign-key relationship with mismatched tenant IDs. Python aggregation then
  trusts the child tenant and can misattribute metrics.
- Evidence: The live read-only check found zero such mismatches today.
- Proposed fix: Add composite `(id, tenant_id)` uniqueness and tenant-aware
  foreign keys incrementally, after a pre-migration integrity query and with
  careful handling of existing constraints.

### SA-12 — Admin listing scans the entire Auth directory for email addresses

- Classification: **Confirmed**
- Severity: **Low now; Medium at large scale**
- Affected route: `list_admins`
- Root cause: It paginates correctly but loads every Auth user in batches of
  1,000 even when only a small subset are institution admins.
- Impact: Correct at 200 users, but latency and Auth Admin API traffic grow with
  every account on the platform.
- Proposed fix: Denormalize a normalized email into the protected profile for
  admin display, or fetch only the required Auth IDs through a server-side
  database function if supported by the chosen Auth boundary.

## Endpoint and page wiring matrix

| UI/page | API | Guard | Status |
|---|---|---|---|
| Super dashboard | `GET /api/v1/platform/overview` | `_require_super` | Wired; affected by SA-01 |
| Institutions list/detail | `GET /api/v1/platform/overview` | `_require_super` | Wired; detail is shallow (SA-05) |
| Onboard institution | `POST /api/v1/platform/tenants` | `_require_super` | Wired; rollback risk (SA-03) |
| Embedded admin manager | `GET /tenants`, `GET/POST /admins`, `DELETE /platform/admins/{id}` | `_require_super` | Wired |
| Standalone Admins | Redirect only | N/A | Function lives on Institutions page (SA-08) |
| Question Quality | `GET /api/v1/platform/ai-monitoring` | `_require_super` | Wired; metric defects (SA-01, SA-02, SA-06) |
| Courses/Question Bank | `GET /api/v1/platform/question-bank` | `_require_super` | Backend/client only; UI absent (SA-04) |
| Legacy platform stats | `GET /api/v1/platform/stats` | `_require_super` | Client wrapper exists; no current super page uses it |

## Prioritized fix plan for approval

1. **P0 — Make metrics trustworthy:** replace unbounded platform reads with SQL
   aggregates or pagination; source current published count from `quiz_sets`;
   add the missing publish event for historical analysis; correct event
   lifecycle folding.
2. **P0 — Make provisioning failure-safe:** redesign onboarding/admin creation
   around verified compensation or an atomic database boundary and cover every
   partial-failure step with tests.
3. **P1 — Add super-admin contract tests:** role rejection, platform sums,
   tenant attribution, profile flags, deletion behavior, and large datasets.
4. **P1 — Complete product wiring:** decide whether to ship the platform
   Question Bank/Courses page, and expand institution detail into a read-only
   tenant operational view.
5. **P2 — Strengthen data integrity:** migrate eligible relationships to
   tenant-aware composite foreign keys and add orphan/profile cleanup tooling.
6. **P2 — Clean navigation and scale admin email lookup:** settle the Admins
   route location and avoid scanning the full Auth directory as usage grows.

## Verification results

- Backend: **71 passed, 60 subtests passed**.
- Frontend lint: **passed with no warnings or errors**.
- Frontend production build: **passed; all 36 routes generated**.
- Read-only Supabase integrity check: **passed for current tenant links**.
- Live mutation/login loop: **not run**, because the configured database was
  not proven to be disposable staging and diagnosis-only work should not create
  or remove shared accounts.
