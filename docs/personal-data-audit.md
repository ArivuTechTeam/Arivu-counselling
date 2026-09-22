# Personal data flow and deletion audit

Last reviewed: 2026-09-22

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
| Quiz/practice activity | Answers, autosave state, scores, timestamps, bookmarks, revision topics | Browser → FastAPI → tenant- and user-scoped Supabase tables. Grading is local deterministic code, not AI. | `quiz_attempts`, `attempt_answers`, `practice_sessions`, `practice_answers`, `bookmarks`, and `revised_topics`. |
| Dashboard recovery state | Non-sensitive filters, selections, draft names/emails, topic setup, and durable job identifiers | Current browser tab only | Stored in `sessionStorage` to survive refresh. Passwords, temporary passwords, access tokens, uploaded `File` objects, and destructive confirmation state are excluded. Backend/Supabase records remain authoritative. |
| Challenges/leaderboards | Creator display name, opaque share token, participant identity, scores | Browser → FastAPI → Supabase. A same-course/institution audience receives display names and scores. | `challenges` and linked practice sessions. Account deletion replaces the creator name with `Deleted user` and removes the account pointer. |
| Operational product events | Actor UUID/role, event type, subject UUID, minimal event metadata, timestamp | FastAPI → Supabase `events`. | Used for internal product-quality analytics. Account deletion removes every event for that actor. Application logs never contain the event payload. |
| User-initiated WhatsApp share | Challenge URL/question count, or quiz title and score percentage | Browser opens `wa.me` only when the user chooses Share. | WhatsApp receives the pre-filled share text and URL. No email, token, internal account UUID, or answer detail is included. |
| Theme preference | `light`/`dark` | Browser only | The sole `localStorage` value. It is not personal data and is not sent to an API. |

## Data not collected by application code

There are no application fields or SDKs for phone/mobile number, postal address,
date of birth, card/payment data, advertising identifiers, device fingerprint,
or precise location. FastAPI does not read or store client IP or user-agent.
Supabase, Vercel, Railway, Google, Gemini, DeepSeek and WhatsApp may process IP,
device and request metadata as infrastructure providers; that processing is
outside this repository and requires a vendor retention/DPA review.

## Role-scoped API disclosure

- Students receive only their own attempts, answers, history, bookmarks and
  revision state. Challenge and course leaderboards deliberately expose display
  names and aggregate scores to the permitted cohort, not emails.
- Teachers receive names and performance for students in their assigned class
  scope. They do not receive passwords, Auth metadata or session tokens.
- Institution admins receive teacher/student names and emails needed for roster
  and account administration, restricted to their tenant.
- Super admins receive institution-admin names/emails, platform aggregates, and
  each institution's operational Course → Level → Subject offering tree/counts.
- Opaque record UUIDs remain in responses only where the client needs them for
  navigation, registration, updates, deletion or drill-down. The public
  institution-branding response includes a tenant UUID solely to scope its
  Course + Level signup choices. Other tenant IDs, ownership pointers, storage
  paths, content hashes, provider error bodies and Auth tokens are not returned
  unless an explicitly public workflow requires registration metadata or an
  opaque share token.

Identity diagnostic endpoints return only authentication status or role/password
change state. Question mutation endpoints use an explicit response model that
drops database ownership and tenant fields.

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
`DELETE` confirmation. It:

1. revokes all Supabase Auth sessions for the supplied access token;
2. deletes the account's original private Storage objects, whose bytes may
   themselves contain personal data;
3. calls the service-role-only `anonymize_account_data` database function,
   which deletes attempts/answers, practice activity, bookmarks, revision state,
   enrolments, assignments, rate-limit rows and actor event rows;
4. removes names, avatar, filenames and author/reviewer links from retained
   institution-owned teaching content;
5. anonymizes challenge authorship; and
6. hard-deletes the Supabase Auth identity, cascading the remaining profile.

Institution-admin teacher removal and super-admin administrator removal use the
same erasure routine before deleting the target Auth identity.

Migration `migration-30-account-data-deletion.sql` must be applied before the
endpoint is deployed. Generated institution teaching content remains usable,
but the original uploaded object is removed, and its random dead storage path,
filename, hash and uploader association are anonymized in the database.

## Fixes made in this audit

- Replaced raw URL logging with route templates and disabled Uvicorn access logs
  in production/local Docker commands.
- Removed storage object paths and upstream provider response bodies/model output
  from logs and exception messages.
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

- Apply migration 30 and test deletion against a disposable account in the
  production Supabase project.
- Confirm Supabase Auth password policy/hash configuration and session/JWT
  lifetimes in the dashboard.
- Review retention and data-processing terms for Supabase, Google OAuth/Gemini,
  DeepSeek, Vercel, Railway and WhatsApp.
- Configure provider-side log retention so request bodies, uploaded files and
  Auth credentials are not retained longer than the documented purpose.
