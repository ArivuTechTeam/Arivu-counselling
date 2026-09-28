# Personal data flow and deletion audit

Last reviewed: 2026-09-28

This document describes application behavior visible in this repository. Hosting
providers may additionally process IP addresses, user-agent strings, and request
metadata in infrastructure logs; verify their retention settings separately.

## Collection and data-flow map

| Entry point | Data collected | Route after collection | Destination and retention |
|---|---|---|---|
| Email/password signup | Full name, email, password, selected course and level | Browser sends the identity directly to Supabase Auth over HTTPS. Supabase's signup trigger copies full name to `profiles`, validates Course + Level together, and derives tenant/enrolment from that pair. | Email, password verifier and Auth metadata in Supabase Auth; name/role/tenant in `profiles`; course and level membership in `enrollments`. The application database never receives a password hash or plaintext password column. |
| Google sign-in/signup | Google-verified name, email, provider identity; selected course and level for a new student | Google OAuth → Supabase Auth → browser callback. The callback sends the selected course and level UUIDs to `complete_google_signup`. | Provider identity/email in Supabase Auth; name and derived tenant/role in `profiles`; course and level membership in `enrollments`. |
| Login | Email and password | Browser → Supabase Auth over HTTPS. The FastAPI backend receives only the resulting bearer access token on later API calls. | Supabase Auth validates the password. Access/refresh session material is kept in the browser tab's `sessionStorage`, not `localStorage` or application cookies. |
| Admin-created teacher/admin | Full name, email, temporary password, tenant and, for teachers, Course → Level → Subject assignments | Browser → FastAPI → Supabase Auth Admin API and tenant-scoped database writes. | Identity/password verifier in Supabase Auth; name/role/tenant in `profiles`; teacher assignments in `teacher_subjects`/`enrollments`. Plaintext passwords exist only in form memory and encrypted request bodies and are never returned by an API. |
| Password change/reset | Current and new password, or browser-generated temporary password | Browser → FastAPI → Supabase Auth over HTTPS. | Supabase Auth replaces its password verifier. The API returns only a success boolean. |
| Document upload/extraction | File bytes, original filename, type, content hash, uploader UUID | Browser → FastAPI → private Supabase Storage and `documents`. Text is extracted in backend memory. | Original file in private Storage; random object path and document metadata in `documents`. Filename/content may itself contain personal data supplied by the uploader. |
| AI quiz generation/topic extraction | Extracted study-document text and generation settings | FastAPI → DeepSeek first, with Gemini as the configured text fallback. | Provider receives system instructions plus a bounded document excerpt or full extraction chunk. The application stores validated questions and provider name. No account name, email, tenant ID, token, or password is added to an AI prompt. |
| Scanned quiz extraction | PDF/image bytes and extraction instructions | FastAPI → Gemini multimodal API. | Gemini receives the uploaded scan inline. Extracted questions are stored in Supabase. DeepSeek never receives raw file bytes. |
| Question regeneration/AI tutor | Question text, options, correct answer and existing explanation | FastAPI → Gemini or DeepSeek. | Provider output is validated; tutor output is cached in `ai_explanations`. No student answer, score, name, or email is included. |
| AI operational telemetry | Provider/model, call type, fallback flag, token counts, estimated cost, latency, status, stable error class/status | FastAPI → `api_call_logs` through a best-effort backend write. | Metadata only. Migration 59 permanently drops the former raw request/response columns; prompts, document text, and provider responses are not stored or exposed by the admin API. |
| Quiz/practice activity | Answers, autosave state, scores, timestamps, bookmarks, revision topics | Browser → FastAPI → tenant- and user-scoped Supabase tables. Grading is local deterministic code, not AI. | `quiz_attempts`, `attempt_answers`, `practice_sessions`, `practice_answers`, `bookmarks`, and `revised_topics`. |
| In-quiz rough work | Calculator input, typed notes, and drawing strokes | Current React component memory only | Never sent to an API or written to browser storage; discarded on refresh or when leaving the attempt. |
| Paper-bank practice (flag-gated) | Selected questions, submitted answers, and (for descriptive grading) free text up to 2,000 characters | Browser → FastAPI → private `paper_attempts`; descriptive answers also go to DeepSeek preferred, Gemini fallback. The provider prompt does not add the student's name, email, tenant ID, or access token. | The server stores a frozen question/answer-key snapshot and the graded report in `paper_attempts`. Its answer key is never sent while taking; the report is returned only after every selected question is answered and the attempt is graded. Paid grading calls are capped per student per rolling hour. |
| Dashboard recovery state | Non-sensitive filters/selections and opaque durable job/resource identifiers | Current browser tab only | Stored in `sessionStorage` to survive refresh. Names, emails, filenames, chapter/topic text, question/answer drafts, passwords, uploaded `File` objects, and destructive confirmation state are excluded. Supabase session/PKCE material is the one sensitive exception and is needed for per-tab authentication. Backend/Supabase records remain authoritative. |
| Challenges/leaderboards | Creator display name, opaque share token, participant identity, scores | Browser → FastAPI → Supabase. A same-course/institution audience receives display names and scores. | `challenges` and linked practice sessions. Account deletion replaces the creator name with `Deleted user` and removes the account pointer. |
| Operational product events | Actor UUID/role, event type, subject UUID, minimal event metadata, timestamp | FastAPI → Supabase `events`. | Used for internal product-quality analytics. Account deletion removes every event for that actor. Application logs never contain the event payload. |
| Feedback and support | Optional 1–5 app rating, selected topic, free-text message and any staff reply; authenticated requester, role, and tenant identity are attached by the backend | Student/faculty/institution-admin Settings → FastAPI → private `student_contact_requests` table. Faculty/admin requests and general/app support route to ArivuPro super-admins; student course/access/quiz support routes to that tenant's institution admins. | No email or third-party ticket service receives the message. Requesters see only their own requests; staff see only their destination and, for institution admins, their tenant. The super-admin inbox labels each request with verified role and institution. The API returns a short public reference, not internal IDs. Profile deletion cascades to these requests. Free text may contain personal data, so it is never logged. |
| User-initiated WhatsApp share | Challenge URL/question count, or quiz title and score percentage | Browser opens `wa.me` only when the user chooses Share. | WhatsApp receives the pre-filled share text and URL. No email, token, internal account UUID, or answer detail is included. |
| Theme preference | `light`/`dark` | Browser only | The sole `localStorage` value. It is not personal data and is not sent to an API. |

## Data not collected by application code

There are no application fields or SDKs for phone/mobile number, postal address,
date of birth, card/payment data, advertising identifiers, device fingerprint,
or precise location. FastAPI does not read or store client IP or user-agent.
Supabase, Vercel, Railway, Google, Gemini, DeepSeek and WhatsApp may process IP,
device and request metadata as infrastructure providers; that processing is
outside this repository and requires a vendor retention/DPA review.

## Third-party disclosures

| Processor | Data sent | Minimized boundary |
|---|---|---|
| Supabase Auth/Database/Storage | Email, name/provider identity, password during Auth operations, session tokens, tenant/role/enrolment links, uploaded files, quiz/activity records | Passwords go directly to Auth and are not copied into application tables. Storage is private; database access is tenant/role scoped with RLS and backend authorization. |
| Google OAuth | OAuth protocol data and the Google identity fields returned to Supabase Auth | The app requests authentication identity only; it does not call Google profile, contacts, mail, or analytics APIs. |
| DeepSeek | Extracted document text/chunks, generation instructions, question material, and (only for enabled paper-bank descriptive grading) the student's bounded free-text answer | No account name, email, password, bearer token, tenant UUID, or score is added. |
| Gemini | The same bounded text task data when used as fallback, including the paper-bank descriptive answer if DeepSeek fails; PDF/image bytes for vision extraction | No application identity fields are added. Raw request/response copies are no longer kept in `api_call_logs`. |
| WhatsApp | Only user-initiated share text: challenge link/count or quiz title and score percentage | No automatic SDK transmission; no email, account UUID, answer detail, or Auth token. |
| Vercel/Railway and vendor edge infrastructure | Network-level IP, user-agent, request time, route and operational metadata may be processed outside application code | Application logs use route templates and never log request bodies, query strings, identity fields, document IDs, filenames, tokens, or provider payloads. Vendor retention still requires configuration/DPA review. |

No analytics, advertising, error-tracking, payment, email-delivery, Twilio,
Firebase, AWS application SDK, or card processor is present in this repository.

## Role-scoped API disclosure

- Students receive only their own attempts, answers, history, bookmarks and
  revision state. Challenge and course leaderboards deliberately expose display
  names and aggregate scores to the permitted cohort, not emails.
- Teachers receive names and performance for students in their assigned class
  scope. They do not receive passwords, Auth metadata or session tokens.
- Institution admins receive teacher/student names and emails needed for roster
  and account administration, restricted to their tenant. Their support inbox
  includes only institution-routed requests from their tenant.
- Super admins receive institution-admin names/emails, platform aggregates, and
  each institution's operational Course → Level → Subject offering tree/counts.
  Their support inbox includes only platform-routed requests and shows the
  verified requester role, requester name when available, and institution.
  The AI API logs page also receives opaque call/tenant/document/job identifiers
  for paper grouping, filtering and safe metadata drill-down. Uploaded filenames,
  raw prompts and provider responses are excluded; legacy error text is replaced
  with a generic provider-failure message. Migration 73 adds metadata-only
  generation/import run IDs, status and a link to the resulting quiz. The admin
  summary joins the quiz title for identification without copying it into logs.
  Run totals aggregate all matching calls across pages. Historical calls without
  a run ID remain explicit legacy paper totals, never guessed per-quiz costs.
  The editable INR conversion is a view estimate; call details separately show
  the originally recorded INR cost. Missing usage/pricing is marked incomplete.
- Opaque record UUIDs remain in responses only where the client needs them for
  navigation, registration, updates, deletion or drill-down. The public
  institution-branding response includes a tenant UUID solely to scope its
  Course + Level signup choices. Other tenant IDs, ownership pointers, storage
  paths, content hashes, provider error bodies and Auth tokens are not returned
  unless an explicitly public workflow requires registration metadata or an
  opaque share token.

Identity diagnostic endpoints return only authentication status or
role/password-change state. The authenticated account-settings endpoint returns
the caller's own full name, email, role, and display-only academic assignments;
every enrollment/assignment lookup is filtered by the authoritative user and
tenant. It omits internal user/tenant IDs. Question mutation endpoints use an
explicit response model that drops database ownership and tenant fields.

## Password controls

Supabase Auth is the credential store and performs password hashing. The app has
no password or password-hash database column. Plaintext passwords are transient:
they exist in controlled form state, an HTTPS request body, and Supabase Auth's
credential-processing call. They are never logged, persisted in browser storage,
written to the application database, or returned in an API response.

## Browser storage and cookies

- The application creates no cookies, so there are no application cookie flags
  to configure.
- Supabase Auth is deliberately configured with per-tab `sessionStorage` for
  PKCE/session continuity. This is JavaScript-readable and therefore still
  depends on the CSP/XSS controls, but it is cleared with the tab and is not
  shared across tabs like `localStorage`.
- `localStorage` contains only the non-personal theme preference.
- Temporary passwords live only in React component memory until refresh and may
  enter the OS clipboard only after an administrator explicitly chooses Copy.

## Account deletion behavior

`DELETE /api/v1/auth/account` requires an authenticated session and an exact
`DELETE` confirmation from the role-specific Settings page. The destructive
action is not exposed directly in the avatar menu. It:

1. revokes all Supabase Auth sessions for the supplied access token;
2. deletes the account's original private Storage objects, whose bytes may
   themselves contain personal data;
3. deletes private paper attempts containing submitted answers and answer-key snapshots;
4. calls the service-role-only `anonymize_account_data` database function,
   which deletes attempts/answers, practice activity, bookmarks, revision state,
   enrolments, assignments, batch memberships, rate-limit rows, actor event rows,
   copy requests, transient document chunks, generation jobs/checkpoints and
   linked AI telemetry; it clears extraction raw output;
5. removes names, avatar, filenames and author/reviewer links from retained
   institution-owned teaching content;
6. anonymizes challenge authorship; and
7. hard-deletes the Supabase Auth identity, cascading the remaining profile.

The profile cascade also deletes that requester's feedback/support messages and
staff replies from `student_contact_requests`.

Supabase notes that an already-issued access JWT can remain cryptographically
valid until its expiry. Global sign-out prevents refresh, while deleting the
profile makes this app's profile-based authorization and RLS checks fail during
that remaining window; keep production JWT lifetimes short and verify this in
the deployment project.

Institution-admin teacher removal and super-admin administrator removal use the
same erasure routine before deleting the target Auth identity.

Migrations `migration-30-account-data-deletion.sql` and
`migration-59-personal-data-minimization.sql` are required before the endpoint
is deployed. The operator reported migration 59 applied on 2026-09-24; verify
that record in Supabase before relying on it in another environment. Generated institution teaching content remains usable,
but the original uploaded object is removed, and its random dead storage path,
filename, hash and uploader association are anonymized in the database.

## Fixes made in this audit

- Replaced raw URL logging with route templates and disabled Uvicorn access logs
  in production/local Docker commands.
- Removed storage object paths and upstream provider response bodies/model output
  from logs and exception messages.
- Removed document/user/job UUIDs, source topic names/ranges, filenames and raw
  exception messages from application and QA-script output.
- Stopped persisting AI prompts/responses, removed the raw-payload admin viewer,
  and added migration 59 to physically drop previously stored payload columns.
- Removed names, emails, filenames, chapter/topic text, and question/answer
  drafts from browser recovery storage; `localStorage` remains theme-only.
- Changed temporary-password reset so the browser supplies the generated value
  and the API returns only `{ "changed": true }`.
- Minimized `/api/v1/me`, `/api/v1/me/profile`, and question mutation responses.
- Removed redundant emails, tenant/owner fields and action-target UUIDs from
  teacher/admin provisioning, academic creation and quiz-publish responses.
- Limited Auth metadata updates to application-owned fields instead of
  retransmitting arbitrary legacy metadata.
- Added self-service account deletion, global session revocation and database
  deletion/anonymization migration.
- Added regression tests for log boundaries, browser storage, password response
  filtering, account deletion ordering, response-field filtering and migration
  coverage.

## External verification still required

- Verify migrations 30 and the reported migration-59 application in Supabase,
  then test deletion against a disposable account in the production project.
- Confirm Supabase Auth password policy/hash configuration and session/JWT
  lifetimes in the dashboard.
- Review retention and data-processing terms for Supabase, Google OAuth/Gemini,
  DeepSeek, Vercel, Railway and WhatsApp.
- Configure provider-side log retention so request bodies, uploaded files and
  Auth credentials are not retained longer than the documented purpose.
