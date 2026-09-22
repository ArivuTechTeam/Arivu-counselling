# Dashboard refresh persistence

**Verified against code:** 22 September 2026

Non-sensitive UI preferences and drafts use per-tab `sessionStorage`, primarily
through `frontend/lib/use-session-storage-state.ts`. A refresh in the same tab
restores them; closing the tab ends their intended lifetime. Invalid or
unavailable browser storage falls back safely to page defaults.

The dashboard shell also keeps a versioned `dashboard-bootstrap-v1` entry via
`frontend/lib/dashboard-bootstrap.ts`. It contains only the current user ID,
role, and forced-password-change flag so the role shell can render from the
local Supabase session without repeating the old remote auth/profile waterfall.
The authenticated `/api/v1/me/profile` response still refreshes the
authoritative role, password state, and institution identity on every dashboard
mount; the cached bootstrap is a UI fast path, not an authorization boundary.

Currently covered:

- Super admin: API-log filters/grouping/INR display rate and institution
  onboarding non-secret text/select fields. Catalogue-offering selections are
  not currently restored after refresh.
- Institution admin: analytics sorting/toggles, user search/page, teacher form
  name/email/course/level/subject selections, admin/course/level/subject
  management drafts.
- Student: challenge setup, leaderboard course, revision tab, smart-quiz setup,
  and subject/tab selection.
- Teacher Generate Quiz: uploaded document selection, subject/chapter, analysis
  job and checkpoint UI, extracted topics, topic counts, and final generation
  job reconnection.

Never persist passwords, temporary passwords, access tokens, uploaded `File`
objects, destructive confirmation state, or other credentials in this helper.
Password fields intentionally reset on refresh. Backend/Supabase records remain
the source of truth for business data; this browser state only restores the UI.
