# ExamApp handoff contract

The quiz-generator backend creates a short-lived, one-way browser handoff to
ArivuPro ExamApp. ExamApp redeems the token; quiz-generator has no callback.

## Token

- Algorithm: HS256.
- Signing key: `HANDOFF_SHARED_SECRET`, with the same independently generated
  value in both backends. It must be random, at least 32 bytes, must never be
  the Supabase JWT secret, and must never be committed or exposed to a browser.

| Claim | Required | Value |
|---|---|---|
| `iss` | Yes | `quiz-generator` |
| `aud` | Yes | `examapp` |
| `iat` | Yes | UTC issue time |
| `exp` | Yes | Exactly 60 seconds after `iat` |
| `jti` | Yes | New UUIDv4 for every mint |
| `sub` | Yes | Caller's Supabase Auth user ID |
| `email` | Yes | Caller's verified email |
| `name` | Yes, nullable | Server-side profile name |
| `role` | Yes | `student`, `teacher`, `institution_admin`, or `super_admin` |
| `tenant_id` | Yes, nullable | Authoritative profile tenant UUID; null for `super_admin` |
| `tenant_name` | Yes, nullable | Authoritative tenant name; null for `super_admin` |
| `exam_type` | Optional, student-only | Linked `catalog_courses.code` |
| `exam_level` | Optional, student-only | Linked `catalog_course_levels.name` |

Tenant and role claims always come from `get_current_profile()`, which loads the
server-side `profiles` row. Request data, headers, and JWT metadata cannot
override them.

For students only, quiz-generator best-effort maps the tenant enrollment through
`courses.catalog_course_id` and `course_levels.catalog_level_id` into the global
catalog. Both optional keys are omitted for non-student roles. If a student has
no enrollment or their tenant course has no global catalog link, both keys are
omitted rather than sent as null or empty strings. A catalog-linked course may
still provide `exam_type` without `exam_level` when its operational level is
missing or unlinked.

Students whose course is not linked to the global catalog will therefore arrive
at ExamApp without a course/level match. This is a known limitation, not a bug,
until every tenant course is linked to the global catalog.

## Transport

The authenticated browser calls:

```text
POST /api/v1/handoff/examapp
```

The optional JSON field `next` defaults to `/`. It must be a relative path that
starts with one `/`; absolute URLs, scheme-bearing values, network-path values
beginning with `//`, backslashes, and control characters are rejected.

The response is:

```json
{"redirect_url":"https://examapp.example/auth/handoff#token=<jwt>&next=<relative path>"}
```

The token and `next` are carried in the URL fragment only, never in the query
string. The browser navigates with `window.location.assign(redirect_url)`.
quiz-generator does not log or persist the token. Each successful mint appends
an `events` row containing the actor ID, authoritative profile tenant ID, role,
event type, and requested next path—but no token or redirect URL.

## Dedicated institution gate

The handoff is enabled per institution only by:

```text
tenants.handwritten_evaluation_enabled
```

This boolean defaults to `false` and is read and written directly. A
`super_admin` is exempt from the gate. The handoff deliberately bypasses
`tenants.feature_flags` and `effective_feature_flags()` because the current
general mechanism forces flags on platform-wide and ignores stored per-tenant
values. Keeping this gate separate prevents that behavior—and future changes to
the general feature system—from silently enabling or disabling ExamApp access.

## Deployment configuration

- Quiz-generator backend: `HANDOFF_SHARED_SECRET` and
  `EXAMAPP_FRONTEND_URL` (origin only).
- ExamApp backend: the identical `HANDOFF_SHARED_SECRET`.
- Apply `migration-76-examapp-handoff.sql` before deploying the API/frontend.
- Enable the new column explicitly for each approved institution from the
  super-admin institutions screen.
