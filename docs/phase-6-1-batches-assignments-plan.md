# P6.1 — Batches + Assignments (phase 2 of 8): design for approval

**Status:** design for sign-off. No schema/code until approved (migrations are applied by hand and this changes student access — highest-care area).

## 1. Goal & the non-breaking guarantee

Today a student sees **every published quiz in their enrolled subjects** (course-wide). For commerce, a quiz must be deliverable to **specific batches** (cohorts), and one batch's paper must never reach another batch.

**The guarantee that makes this safe:** we introduce an explicit **audience mode** per quiz plus a **`BATCHES_ENABLED` flag**, so nothing existing changes:

- `quiz_sets.audience_mode` defaults to **`legacy_course`** → existing and non-commerce quizzes behave **exactly as today** (enrolled-subject + published).
- `assigned_batches` → visible only to active members of an **assigned** batch, within the availability window.
- With **`BATCHES_ENABLED=false`** (default), audience mode and assignments are **ignored entirely** → today's behavior, byte-for-byte. We turn it on per rollout.

A quiz with no assignment is never accidentally public (legacy stays course-scoped) nor accidentally batch-restricted-to-nobody (only `assigned_batches` requires an assignment).

## 2. Data model (logical — final SQL at build time)

| Table | Columns | Rules |
| --- | --- | --- |
| `batches` | id, tenant_id→tenants, course_id→courses, name, exam_session?, starts_on?, ends_on?, status(active/archived) default active, created_by, created_at | unique(tenant_id, course_id, name); course must be same tenant. A branch is **not** a tenant. |
| `batch_memberships` | id, tenant_id, batch_id→batches, profile_id→profiles, membership_role(student/teacher) default student, active bool default true, valid_from?, valid_to?, created_at | unique(tenant_id, batch_id, profile_id); a student may be in many batches. |
| `quiz_assignments` | id, tenant_id, quiz_set_id→quiz_sets, batch_id→batches, available_from?, available_to?, status(active/withdrawn) default active, created_by, created_at | unique(tenant_id, quiz_set_id, batch_id); idempotent create. |
| `quiz_sets` (alter) | + `audience_mode` text default `legacy_course` | additive, nullable-safe default; existing rows unchanged. |

All tenant-scoped, RLS + grants mirroring existing tables, indexed on (tenant, course/batch/quiz, active). Same-tenant integrity enforced by carrying `tenant_id` on every row + RLS (`tenant_id = current_tenant_id()`); backend keeps its explicit `tenant_id` filters (service-role). Migration is **additive, nullable, rerunnable** (`add column if not exists`, `create table if not exists`) so applying it changes no current behavior.

Config: `BATCHES_ENABLED` (default false).

## 3. Access resolution (the core — one source of truth)

A single module (`student_access` / a new `batch_access.py`) computes visibility, so every read path uses identical logic:

- **`legacy_course` set:** published quizzes in the student's enrolled subjects (today's query).
- **`assigned_batches` set (only when flag on):** published quizzes whose `audience_mode='assigned_batches'` that have an **active** `quiz_assignment` to a batch where the student is an **active member** (`batch_memberships.active` + within valid dates) **and** now within `[available_from, available_to]`.
- **Visible = union.** With the flag off, only the legacy set is used and `assigned_batches` quizzes are treated as invisible-by-default (they only exist once we roll batches on).

Two helpers back everything:
- `student_visible_quiz_set_ids(service, profile)` → for list endpoints.
- `student_can_access_quiz(service, profile, quiz_set_id)` → for attempt-start and any direct-ID load.

## 4. Enforcement points (every read path — no gaps)

This is the security surface; all five must use the resolver:

1. **Quiz list** — `GET /student/quizzes`.
2. **Attempt start** — `POST /student/attempts` (the critical gate; re-checks membership + window at start).
3. **Practice** — `selector.py`: extend the existing "published-quiz" leak-protection so a question linked to an `assigned_batches` quiz is practiceable **only** if the student is in an assigned batch for it. (Prevents exam items leaking into another batch's practice pool.)
4. **Challenge** — `challenge.py`: questions sourced from `assigned_batches` quizzes respect membership the same way.
5. **Direct-ID** — any endpoint loading a quiz/attempt/question by id for a student goes through `student_can_access_quiz`.

Answer embargo (no `correct_answer`/`explanation` before submission) is unchanged and must continue to hold on all of these.

## 5. Rostering, admin & faculty surfaces (decisions locked)

**Student rostering = self-selection at signup** (owner decision). Signup already self-selects **course**; we extend the identical pattern to **batch**:
- New public `GET /api/v1/public/batches?tenant_id=…&course_id=…` (mirrors public `courses`), so the signup batch dropdown is filtered by the chosen course.
- On signup the student's `batch_membership` (role `student`) is created the same way enrollment is today.
- Trust level is unchanged from today's self-selected course. **Admin/teacher get a roster view + correction** to fix mis-selections (the safety net; no bulk upload needed).

**Teacher batch membership = yes.** `batch_memberships.membership_role='teacher'` scopes a teacher to the batches they run, so:
- The faculty assign screen only shows the teacher's own batches.
- Different teachers can own different batches of the same subject (2026 vs 2027).
- The cross-batch "goes to both batches" problem is solved by the **assignment step** (assign to a specific batch); teacher membership scopes *which* batches are pickable.

**Faculty API:** assign a **published** quiz to one or more of the teacher's batches with an **optional** availability window; list/withdraw. Assigning sets `audience_mode='assigned_batches'`.

**Institution-admin API:** batches CRUD + a **roster view/correction** screen (move/remove a student's batch, deactivate membership). No bulk import in Phase 1 (self-signup is the primary path).

**Deferred (noted, not built in P6.1):** batch-level curriculum/progress tracking (which chapters a batch has covered). For now the teacher assigns the right quiz to the right batch manually.

## 6. Increment breakdown (each ships safely, flag-gated)

| # | Deliverable | Exit gate |
| --- | --- | --- |
| **P6.1-1** | Migration (3 tables + `audience_mode` + RLS + indexes) + `BATCHES_ENABLED` config | Schema applies cleanly; `deployment_check` probes new tables when flag on; **zero behavior change** (flag off / all legacy). |
| **P6.1-2** | `batch_access` resolver + helpers (pure logic, unit-tested) | Unit tests: legacy set, assigned+member+window, non-member denied, window boundaries, flag off = legacy only. Not yet wired. |
| **P6.1-3** | Enforce on all 5 read paths behind the flag | Cross-batch student **denied** on list/start/direct-ID/practice/challenge; window respected; **legacy quizzes byte-identical**; answer embargo holds. Full regression green. |
| **P6.1-4** | Institution-admin batches/memberships API + import-preview | Two batches in one course; membership import previews additions/dupes/unmapped, applies atomically; tenant-safe. |
| **P6.1-5** | Faculty assignment API (assign/list/withdraw + window) | Assign published quiz to batches; idempotent; sets audience_mode; only assigned batches see it. |
| **P6.1-6** | Frontend: admin batch/membership mgmt + faculty assign UI | Admin manages batches/rosters; faculty assigns; student list already returns assigned quizzes. |

Dependencies: 1 → 2 → 3 (core). 4 and 5 can follow 1 (need the schema). 6 after 4/5. The **launch-blocking core is 1–3 + 5** (schema, enforcement, and the ability to actually assign).

## 7. Test matrix (must all pass before rollout)

- **Legacy compatibility:** a `legacy_course` quiz behaves identically with flag **off and on**.
- **Assigned visibility:** only active members of an assigned batch, within window, see/start it.
- **Cross-batch denial:** a student in batch B is denied a quiz assigned only to batch A — on list, start, direct-ID, practice, and challenge.
- **Window:** before `available_from` / after `available_to` → denied.
- **Membership revoked** (`active=false` / past `valid_to`) → denied.
- **Flag off:** assignments ignored; everything legacy.
- **Answer embargo:** holds on every path.
- **Import-preview:** additions, duplicates, unmapped rows surfaced before apply; apply is atomic.
- **Multi-tenant isolation:** batch/assignment of tenant A never visible to tenant B (two-tenant test).

## 8. Risks & mitigations

- **Breaking current visibility** → audience_mode default `legacy_course` + `BATCHES_ENABLED` off by default; legacy path untouched.
- **Exam items leaking via practice/challenge** → extend leak-protection to batch membership (P6.1-3); explicit tests.
- **Concurrent assign/publish races** → idempotent `quiz_assignments` (unique constraint) + it composes with the existing reuse/release-lock (assignments never mutate frozen content).
- **Manual migration** → additive/nullable/rerunnable; `deployment_check` gains probes.
- **Scope** → the admin/faculty UI (P6.1-6) can be minimal first; the launch-critical core is 1–3 + 5.

## 9. Decisions locked (owner-confirmed)

1. **Rostering** — students **self-select their batch at signup** (like course today); staff can view/correct. No bulk upload.
2. **Teacher-in-batch** — **yes**, `membership_role='teacher'` scopes teachers to their batches; assignments prevent cross-batch leak.
3. **Availability window** — **optional**; no window = available while published.

## 10. Revised increment order (reflecting §5/§9)

| # | Deliverable |
| --- | --- |
| P6.1-1 | Migration (batches, batch_memberships, quiz_assignments, `audience_mode`) + RLS/indexes + `BATCHES_ENABLED` config. Behavior-neutral. |
| P6.1-2 | `batch_access` resolver + helpers (pure, unit-tested). |
| P6.1-3 | Enforce on all 5 student read paths behind the flag (security-critical; heavy tests). |
| P6.1-4 | Signup batch selection (public batches endpoint + membership-on-signup) + admin batch CRUD + roster view/correction. |
| P6.1-5 | Faculty assign API scoped to the teacher's batches (+ teacher membership management). |
| P6.1-6 | Frontend: signup batch dropdown, admin batch/roster mgmt, faculty assign UI. |

On your go, I start with **P6.1-1** (additive schema + config, changes no existing behavior), then proceed increment by increment with the §7 test matrix gating each.
