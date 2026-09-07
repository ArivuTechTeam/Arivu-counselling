# Google sign-in setup and user journey

## Local Docker behavior

The local Compose stack mounts `frontend/` and `backend/` into the running
containers and starts development servers. After the one-time recreation that
introduced this configuration, stopping and starting the existing containers
in Docker Desktop loads current application source and `.env` values. Package
changes are installed during container startup.

Docker cannot apply SQL to the hosted Supabase database with the public/service
API keys. Database migrations still need a PostgreSQL database connection or a
one-time run in the Supabase SQL Editor. For Google OAuth, migration 14 must be
applied before testing a brand-new Google account. Restarting Docker does not
replace this database operation.

## Required one-time configuration

1. Apply `migrations/migration-14-google-oauth-onboarding.sql` to the Supabase
   project before releasing the frontend.
2. In Google Cloud, create a **Web application** OAuth client.
3. Add these **Authorized JavaScript origins** in Google Cloud:
   - `https://quiz-generator-drab-nine.vercel.app`
   - `http://localhost:3001` for local testing
4. Add this **Authorized redirect URI** in Google Cloud:
   - `https://pnnkhjlfbkogdukpfreo.supabase.co/auth/v1/callback`
5. In Supabase Dashboard → Authentication → Providers → Google, enable Google
   and enter the Google Client ID and Client Secret.
6. In Supabase Dashboard → Authentication → URL Configuration:
   - Set **Site URL** to `https://quiz-generator-drab-nine.vercel.app`.
   - Add `https://quiz-generator-drab-nine.vercel.app/auth/callback` to
     **Redirect URLs**.
   - Add `http://localhost:3001/auth/callback` while testing locally.

Both login and signup call `signInWithOAuth({ provider: "google", options:
{ redirectTo } })`. The application calculates `redirectTo` from the current
origin and always uses `/auth/callback`.

## New student from the signup page

1. The student opens `/signup` and selects a course.
2. The student clicks **Sign in with Google** and completes Google's consent
   screen.
3. Supabase creates the Google Auth identity. The Auth trigger recognizes a
   brand-new Google user without course metadata and intentionally leaves the
   user without a profile, so the account has no application access yet.
4. Supabase redirects to `/auth/callback`. The callback exchanges the PKCE code
   for a session and reads the pending course selection.
5. The callback calls `complete_google_signup(course_id)`. The database validates
   that the course exists under an active tenant, derives `tenant_id` from that
   course, creates a `student` profile, and creates the enrollment atomically.
6. The student is sent to `/dashboard`, which routes them to the student
   dashboard.

The browser never chooses a role or authoritative tenant. A changed or stale
course ID is rejected by the database.

## New student from the login page

1. The student clicks **Sign in with Google** and completes consent.
2. The callback finds that the new Auth user has no profile.
3. Because no course was chosen before login, the callback displays the active
   course list and requires a selection.
4. The same `complete_google_signup` database function derives the tenant and
   creates the student profile and enrollment.
5. The student is sent to the student dashboard.

If the user closes the callback before selecting a course, the Auth identity
remains unable to access application data. Signing in with Google again returns
them to course selection.

## Existing email/password user

Supabase automatically links a Google identity whose verified email matches an
existing Auth user. The callback finds the existing profile and sends that same
user to the dashboard without changing their tenant, role, or enrollments.
No second application profile is created.
