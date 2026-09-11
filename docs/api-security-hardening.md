# API and browser-data security

The browser is expected to see the Supabase project URL, anon key, and its own
short-lived access token. Security comes from restricting what the anon and
authenticated database roles can do and from enforcing role and tenant checks
inside FastAPI.

## Required production rollout

1. Merge and deploy the backend changes.
2. In the Supabase SQL Editor, run
   `migrations/migration-22-browser-data-api-hardening.sql` once.
3. Confirm Railway's `FRONTEND_ORIGIN` is the exact Vercel production origin,
   including `https://` and without a path or trailing slash. Set
   `APP_DEBUG=false`; production startup rejects debug mode for non-local origins.
4. Remove `NEXT_PUBLIC_DEV_ACCOUNTS_JSON` from every Vercel environment if it
   was ever added. Do not add `NEXT_PUBLIC_DEV_ACCOUNT_EMAILS_JSON` in
   production; the development switcher is local-only.
5. Redeploy Vercel after changing any `NEXT_PUBLIC_*` variable because Next.js
   embeds those values at build time.
6. If development accounts use the production Supabase project, rotate their
   passwords in Supabase Authentication > Users. Prefer a separate Supabase
   project for local development.

## Verify migration 22

Run this in the Supabase SQL Editor. Every answer-bearing table or analytics
view should return `false`; the profile table should return `true` because RLS
restricts it to the signed-in user's own row.

```sql
select
  has_table_privilege('authenticated', 'public.questions', 'select')
    as can_read_questions,
  has_table_privilege('authenticated', 'public.quiz_variant_questions', 'select')
    as can_read_quiz_question_map,
  has_table_privilege('authenticated', 'public.ai_explanations', 'select')
    as can_read_ai_explanations,
  has_table_privilege('authenticated', 'public.v_student_topic_accuracy', 'select')
    as can_read_student_accuracy_view,
  has_table_privilege('authenticated', 'public.v_quiz_question_analysis', 'select')
    as can_read_question_analysis_view,
  has_table_privilege('authenticated', 'public.profiles', 'select')
    as can_read_own_profile;
```

Expected result:

| can_read_questions | can_read_quiz_question_map | can_read_ai_explanations | can_read_student_accuracy_view | can_read_question_analysis_view | can_read_own_profile |
|---|---|---|---|---|---|
| false | false | false | false | false | true |

After applying the migration, sign in as each role and verify dashboard routing,
Google signup completion, quiz taking/submission, teacher review, and admin
analytics. These flows use FastAPI and should continue working.

## Network-tab expectations

- The Supabase anon key is public by design. Never substitute a service-role or
  secret key in a `NEXT_PUBLIC_*` variable.
- A user's bearer access token is visible to that user in their own browser.
  It must only be sent in the `Authorization` header over HTTPS.
- Login and one-time temporary-password requests are visible to the person
  performing the action. API responses use `Cache-Control: no-store` so they
  are not retained by browser or proxy caches.
- Internal database, model-provider, and exception messages must remain in the
  backend. Client responses use stable, friendly messages without raw errors.
