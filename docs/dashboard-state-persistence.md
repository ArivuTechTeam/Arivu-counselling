# Dashboard refresh persistence

**Verified against code:** 28 September 2026

Non-sensitive UI preferences and drafts use per-tab `sessionStorage`, primarily
through `frontend/lib/use-session-storage-state.ts`. A refresh in the same tab
restores them; closing the tab ends their intended lifetime. Invalid or
unavailable browser storage falls back safely to page defaults.

The dashboard no longer reads or writes a cached role. It restores the local
Supabase session, then waits for the authenticated `/api/v1/me/profile`
response before showing role-specific pages. If that request fails, it shows
a retryable error instead of rendering an outdated role. Sign-out still removes
any legacy `dashboard-bootstrap-v1` entry left by earlier versions.

Currently covered:

- Super admin: API-log filters/grouping/INR display rate and institution
  onboarding non-secret text/select fields. Catalogue-offering selections are
  not currently restored after refresh.
- Institution admin: analytics sorting/toggles, user search/page, teacher form
  name/email/course/level/subject selections, admin/course/level/subject
  management drafts.
- Student: challenge setup, leaderboard course, revision tab, smart-quiz setup,
  and subject/tab selection.
- Student quiz-taking scratch notes, drawing strokes, and calculator input are
  intentionally component-memory only: they disappear on refresh and are never
  written to browser storage or sent to an API.
- Teacher Generate Quiz: uploaded document selection, subject/chapter, analysis
  job and checkpoint UI, extracted topics, topic counts, and final generation
  job reconnection.

Never persist passwords, temporary passwords, access tokens, uploaded `File`
objects, destructive confirmation state, or other credentials in this helper.
Password fields intentionally reset on refresh. Backend/Supabase records remain
the source of truth for business data; this browser state only restores the UI.
