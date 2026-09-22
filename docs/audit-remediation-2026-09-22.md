# Performance and UX audit remediation — 22 Sep 2026

Branch: `fix/complete-ux-performance`

## Completed

- Kept the dashboard shell visible while the authoritative profile resolves, with an in-shell loading state instead of replacing the whole application frame.
- Reduced authenticated authorization context from separate profile and tenant reads to one Supabase embedded-relation read. Tenant activity and temporary-password checks remain authoritative on every request; no authorization cache was introduced.
- Added institution setup ordering and a prerequisite checklist so courses and subjects are created before teachers.
- Added a dedicated institution Students destination with course roster selection.
- Added productive Smart Quiz and subject-practice actions to the student zero state and made Take Quiz naming consistent.
- Clarified teacher source/import flows and added guidance when no subjects are assigned.
- Separated institution management from institution-admin management on the super-admin pages.
- Added a skip link and accessible mobile navigation dialog behavior: Escape close, focus trap, focus restoration, dialog semantics, and labelled controls.

## Verification

- `frontend`: `pnpm lint` and `pnpm build`
- `backend`: 495 tests passed in the sandbox; the one socket-based concurrency test passed separately with local socket permission.
- No database migration or environment-variable change is required.
