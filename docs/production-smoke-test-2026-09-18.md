# Production Smoke-Test Issues (Temporary)

- Started: 2026-09-18
- Frontend: `https://quiz-generator-drab-nine.vercel.app`
- Backend: `https://quiz-generator-production-7461.up.railway.app`
- Backend deployment: `4bccae9f-6ccc-4adc-8738-6b3332880a9d`
- Tested commits: `2890acc9776c4d11a5583133003f615b7998c530`, `1b0a5c7`

This is a retained record of the production smoke-test phases 1–8. Do not add
credentials, tokens, or other secrets to it.

## Phase 1 — Platform health

### ST-001 — Login/signup Google Fonts blocked by Content Security Policy

- Status: Fixed locally — pending deployment and production verification.
- Severity: Low
- Pages: `/login`, `/signup`
- Expected: Pages load without browser console or resource-loading errors and use their configured fonts.
- Actual: Both pages return HTTP 200, but Chrome blocks the Google Fonts stylesheet because `style-src` permits only `'self'` and `'unsafe-inline'`.
- Browser error: Loading `https://fonts.googleapis.com/...DM+Serif+Display...DM+Sans...` violates `style-src 'self' 'unsafe-inline'`.
- Source: `frontend/app/login/login.css:1`
- Impact: Authentication remains functional, but the intended DM Serif Display/DM Sans typography falls back to system fonts and produces a production console error.
- Resolution prepared: The login/signup stylesheet no longer imports Google Fonts. It uses the application's bundled/system font stacks instead, so the existing CSP remains strict. Frontend lint and production build pass locally; verify `/login` and `/signup` after deployment.

### Phase 1 checks that passed

- `/login`: HTTP 200.
- `/signup`: HTTP 200.
- Railway `/health`: HTTP 200 with `{"status":"ok"}`.
- CORS preflight accepts the exact Vercel production origin.
- Protected `/api/v1/courses` without a token correctly returns HTTP 401 with a request ID.
- No JavaScript runtime exceptions were detected on `/login` or `/signup`.

## Phase 2 — Student signup

No new defects were found.

### Checks that passed

- The production signup page loaded courses from the Railway API with HTTP 200.
- The configured active institution offered `B.Sc`, `BIOLOGY`, and `CA`.
- A disposable student was created successfully through the real signup UI.
- A fresh login succeeded and redirected to `/dashboard/student`.
- Student profile, statistics, and attempts requests returned HTTP 200.
- Reusing the same email returned: `An account with this email already exists. Sign in instead.`
- A five-character password was rejected with: `Choose a stronger password and try again.`
- Expected Auth failures logged only the stable code and status (`user_already_exists`/`weak_password`, HTTP 422); raw provider messages and secrets were not exposed.
- No unexpected runtime, network, or service-unavailable errors were detected.

### Test artifact and deferred check

- Disposable account: `smoke-student-069560f64b@test.arivupro.com` (remove during Phase 8 cleanup).
- Its temporary credentials are stored outside the repository at `/private/tmp/quiz-smoke-student-credentials.json` with owner-only permissions.
- The inactive-institution course-list case is deferred to Phase 3, where institution state can be inspected safely using the super-admin context. No live institution was deactivated during Phase 2.

## Phase 3 — Super-admin

No new defects were found.

### Checks that passed

- A real production super-admin session reached `/dashboard/super-admin` and loaded the platform overview with HTTP 200.
- Institutions, institution details, institution admins, Question Bank, and Question Quality all rendered without generic error panels or runtime exceptions.
- The authenticated platform APIs for overview, tenants, admins, question-bank monitoring, and AI-quality monitoring returned HTTP 200.
- Without authentication, all readable super-admin APIs returned HTTP 401 with a request ID. The POST-only tenant endpoint rejected GET with HTTP 405.
- The known inactive institution returned zero public signup courses, while the active ArivuPro institution returned three.
- The disposable `alliance university` tenant was deactivated and immediately reactivated through the production UI; both PATCH requests returned HTTP 200 and its final status is active.
- The disposable `john@gmail.com` institution-admin password was reset through `Reset & copy`; the API returned HTTP 200, the one-time credential dialog matched the correct tenant/account, and the Copy credentials confirmation appeared.
- The clipboard was cleared after verifying the copy action.

### Test artifacts and scope notes

- New credentials for the disposable `john@gmail.com` account are stored outside the repository at `/private/tmp/quiz-smoke-institution-admin-credentials.json` with owner-only permissions. Use them in Phase 4, then delete them during Phase 8 cleanup.
- Institution onboarding was not repeated because there is no institution-delete workflow and another successful submission would permanently add test data. Existing production data plus tenant lifecycle and administrator-reset mutations exercised the relevant super-admin wiring without creating an orphan tenant.

## Phase 4 — Institution admin

### ST-002 — Reset temporary passwords could lock an administrator out of the dashboard

- Status: Resolved and production-retested.
- Severity: Medium
- Affected workflows: Super-admin reset of an institution-admin login; institution-admin reset of a teacher login uses the same state pattern.
- Reproduction: Reset the disposable `john@gmail.com` administrator from the super-admin UI, then sign in using the newly issued temporary password.
- Expected: The forced **Set a new password** dialog opens immediately, allowing the account to replace its temporary password and continue.
- Actual: Sign-in reaches `/dashboard/institution-admin`, but every protected dashboard request returns HTTP 403: `You must change your temporary password before continuing.` The forced dialog does not open, so the account cannot change its password through the UI.
- Confirmed cause: The reset API updates `profiles.must_change_password` to `true`, which correctly activates the backend fail-closed gate. It does not also set `auth.users.raw_user_meta_data.must_change_password` to `true`. The frontend dashboard modal relies on that Auth metadata flag, which remains `false` in the signed-in session, so it never opens.
- Relevant code: `backend/app/api/admin.py` (`reset_admin_temporary_password` and `reset_teacher_temporary_password`) updates only `profiles`; `frontend/app/dashboard/layout.tsx` reads `user.user_metadata.must_change_password`.
- Impact: Newly created admin/teacher accounts work because creation sets both values, but any account whose password is reset through the new reset-and-copy controls is blocked after sign-in until repaired externally.
- Resolution: Both reset endpoints now set the password and Auth `user_metadata.must_change_password` together, while retaining the authoritative `profiles` update. Regression coverage covers the super-admin → institution-admin and institution-admin → teacher reset paths.

### Checks completed before the blocker

- The disposable institution-admin login was accepted by Supabase Auth and routed to the correct tenant dashboard.
- The backend temporary-password guard failed closed as intended; no tenant data was exposed before password replacement.
- The browser session confirmed the Auth metadata flag is `false` while the backend profile flag is `true` (boolean values inspected only; no session token was read or printed).

### Resolution verification

- Local verification: targeted reset tests passed; full backend suite passed (`406 passed`, `115 subtests`, with two existing third-party deprecation warnings).
- Production verification: after a super-admin reset, the real `john@gmail.com` disposable institution-admin account was forced to the **Set a new password** dialog. Password replacement returned HTTP 200, sign-out completed, and a fresh login with the replacement password reached `/dashboard/institution-admin`.
- This confirms the former lockout is fixed without weakening the backend's fail-closed temporary-password gate.

### Phase 4 checks that passed

- The institution-admin dashboard, courses, teachers, quizzes, and analytics pages rendered without generic error panels or runtime errors.
- The authenticated institution-admin course API created the disposable `Smoke Test Course Phase 4` course (HTTP 200).
- The authenticated subject API created `Smoke Test Subject Phase 4` within that course (HTTP 200).
- The authenticated teacher API created `Smoke Test Faculty` with the course and subject assignment (HTTP 200); the teacher then appeared in the Teachers UI.
- The faculty's one-time test credentials are held outside the repository in `/private/tmp/quiz-smoke-teacher-credentials.json` with owner-only permissions, for use in Phase 5 only. The course, subject, faculty account, and credential file are all scheduled for removal in Phase 8 cleanup.

## Phase 5 — Faculty

No new defects were found.

### Checks that passed

- The disposable `Smoke Test Faculty` account signed in with its administrator-issued temporary password and immediately received the mandatory **Set a new password** dialog.
- The password replacement completed, and a fresh login with the replacement password reached `/dashboard/teacher`.
- Teacher-scoped production APIs returned HTTP 200 for the assigned-course list, document log, subject metrics, and class overview.
- The collection `GET /api/v1/subjects` correctly returned HTTP 405 because teacher subject access is exposed through teacher-scoped endpoints instead of an unscoped subjects collection.
- A teacher upload of an intentionally invalid `.txt` file correctly returned HTTP 400. It created no document and confirmed that file-type validation is enforced before processing.
- Institution-administration boundaries held: `/api/v1/users` and `/api/v1/admin/analytics` both returned HTTP 403 for the faculty session.
- The faculty Subjects, Document log, Extract quiz, Generate quiz, Review queue, and Class monitor pages all loaded without generic error panels or runtime errors.

### Test artifact

- The disposable faculty credential remains outside the repository at `/private/tmp/quiz-smoke-teacher-credentials.json` with owner-only permissions. It and the Phase 4 test course/subject/account remain in place only until Phase 8 cleanup.

## Phase 6 — Student learning flow

No new defects were found.

### Checks that passed

- The disposable student signed in and reached `/dashboard/student`.
- Student statistics, published-quizzes list, attempt history, practice subjects, weak-area analysis, and revision topics APIs all returned HTTP 200.
- A published quiz variant was available to the disposable student. Starting it returned answer-stripped questions: no `correct_answer` or explanation was exposed before grading.
- Attempt autosave returned HTTP 200.
- A normal submission with no answers correctly returned HTTP 400, enforcing the requirement to answer every question. The supported explicit **leave quiz** finalization then graded the disposable attempt with unanswered questions scored as zero and added it to the student's history.
- The student attempt-history endpoint returned HTTP 200 with one graded disposable attempt recorded.
- Teacher document access and institution user administration both returned HTTP 403 for the student session.
- Student Subjects, History, Smart Quiz, Weak areas, Revision, Daily, Leaderboard, Exam simulator, and Challenge pages loaded without generic error panels or runtime errors.

### Test artifact

- The graded disposable student attempt and the Phase 2 disposable student account remain only until Phase 8 cleanup.

## Phase 7 — Cross-role permissions

No new defects were found.

### Checks that passed

- A student session navigating to `/dashboard/teacher` was redirected to `/dashboard/student`.
- A faculty session navigating to `/dashboard/institution-admin` was redirected to `/dashboard/teacher`.
- An institution-admin session navigating to `/dashboard/super-admin` was redirected to `/dashboard/institution-admin`.
- The student session received HTTP 403 from teacher documents, institution users, institution analytics, teacher class overview, and platform overview APIs.
- The faculty session retained its intended HTTP 200 access to documents and its own class overview, while institution users, institution analytics, and platform overview returned HTTP 403.
- The institution-admin session retained HTTP 200 access to its own users and analytics, while teacher documents, teacher class overview, and platform overview returned HTTP 403.
- All checks used the existing isolated test sessions and read-only API requests; no Phase 7 production data was changed.

## Phase 8 — Evidence review and cleanup

### Cleanup completed

- Preflight resolved exactly one `Smoke Test Faculty` account, one `Smoke Test Course Phase 4` course, and its `Smoke Test Subject Phase 4` subject before any deletion occurred.
- The disposable faculty account was deleted through the institution-admin API (HTTP 200).
- The disposable course was deleted through the institution-admin API (HTTP 200), removing the associated disposable subject and assignment. Follow-up lists confirmed zero matching courses and zero matching teachers.
- The exact Phase 2 disposable student account deleted itself through the account-deletion API (HTTP 200).
- The deleted student's prior access token received HTTP 403 from the student statistics API afterward. This is fail-closed: the identity/profile no longer has authorization, even though the old signed-in tab still held a now-useless token.
- Private smoke-test credentials are removed after this log entry. This log remains deliberately uncommitted for the requested next-day reference.

### Final smoke-test outcome

- Phases 1–8 are complete.
- **ST-001** is fixed locally and awaits deployment plus a final production browser verification of `/login` and `/signup`.
- ST-002, the temporary-password reset lockout, was fixed and production-retested successfully.
