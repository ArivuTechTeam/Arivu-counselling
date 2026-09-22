# College onboarding checklist

Use this checklist for the single-college launch. Complete the steps in order.

Google sign-in requires the additional provider and redirect configuration in
[`docs/google-oauth-setup.md`](google-oauth-setup.md).

## 1. Preflight

- [ ] Confirm `migration-11-auth-hardening.sql` is applied in the production
  Supabase project. It forces public signups to be students and derives their
  tenant from the selected course. Migration 47 upgrades that validation to a
  Course + Level pair.
- [ ] Confirm `migration-12-teacher-subjects.sql` is applied. It supports the
  institution admin's teacher subject assignments.
- [ ] Confirm `migration-45-global-course-catalog.sql`,
  `migration-46-seed-global-course-catalog.sql`, and
  `migration-47-student-level-enrollment.sql` are applied in order. They add
  the global catalogue, provision tenant offerings, materialize the operational
  Course → Level → Subject hierarchy, and require Course + Level for new
  student signups. Repository files do not prove that production has applied
  them; verify the target Supabase project directly.
- [ ] Before enabling Google sign-in, confirm
  `migration-14-google-oauth-onboarding.sql` is applied and complete the Google
  provider setup in `docs/google-oauth-setup.md`.
- [ ] Confirm the production frontend and backend are healthy and the
  super-admin account can sign in.
- [ ] Decide the institution name, a unique lowercase subdomain slug, plan,
  first administrator's email, temporary password, and any catalogue courses,
  levels, and subjects the institution should receive at launch.
- [ ] Prepare an optional institution logo as PNG or JPEG, no larger than 1 MB.
- [ ] In Supabase **Authentication → Providers → Email**, confirm whether email
  confirmation is enabled. If enabled, verify that confirmation emails are
  delivered before inviting students. The signup screen requires students to
  confirm their email when Supabase does not return a session immediately.

## 2. Create the tenant and first institution admin

1. Sign in to the deployed application as `super_admin`.
2. Open **Institutions** in the sidebar, or go to
   `/dashboard/super-admin/institutions`.
3. In **Onboard an institution**, enter:
   - **Institution name** — the college's display name.
   - **Subdomain** — a unique slug containing only letters, numbers, and
     hyphens. The current application stores this identifier but does not use
     it as a live custom domain yet.
   - **Plan** — `Free`, `Starter`, `Growth`, or `Enterprise`.
   - **Institution logo** — optional PNG or JPEG up to 1 MB. This is stored
     privately and displayed only through a time-limited URL.
   - **Courses, levels and subjects offered** — optional catalogue selections.
     Selecting any subjects provisions their parent levels and courses for the
     institution. One or several catalogue courses may be selected.
   - **First institution admin** — enter full name, email, and temporary
     password. All three fields must be supplied together.
4. Select **Onboard institution** once. Wait for the green success message and
   confirm the college appears under **All institutions**.
5. Record the new tenant UUID. The current table does not display it, so open
   the Supabase SQL Editor and run this with the exact subdomain used above:

   ```sql
   select id, name, subdomain, is_active
   from public.tenants
   where subdomain = 'replace-with-the-college-subdomain';
   ```

   Confirm exactly one active row is returned and save its `id` for the Vercel
   step below. Do not copy the earlier local-development tenant ID.
6. Copy the generated `/login/{subdomain}` URL from the success panel (or use
   **Login page** in the institution table). Give the institution admin that
   URL, email, and temporary password over a secure channel. The page displays
   the institution's logo above the neutral login form. On first login, the
   application requires the admin to set a new password before using other
   backend features. The login page's student-account link preserves the tenant
   as `/signup?institution={subdomain}`.

If administrator creation fails, the backend removes the newly created tenant
instead of leaving a tenant without its first admin. Correct the reported error
and submit the form again.

## 3. Review courses, levels, subjects, and create teachers

1. Sign in as the new `institution_admin` and complete the forced password
   change.
2. Open **Courses & subjects**. Confirm any catalogue offerings selected by the
   super admin appear as Course → Level → Subject. If the institution needs
   a local offering that is not in the catalogue, use **Add course manually**,
   then create its level and subjects. Institution admins cannot provision from
   the global catalogue.
3. Open **Teachers**. For each teacher, enter the full name, email, temporary
   password, then select Course → Level → one or more Subjects before
   creating the account.
4. Review the resulting subject assignments. Those assignments are the
   teacher's authorization scope and determine which subjects appear in their
   dashboard and content workflows.
5. Give each teacher their temporary credentials securely. Teachers must set a
   new password on first login.

Create at least one complete Course → Level → Subject path before opening
student signup. With no active course and level in the tenant, the signup form
has nothing valid for a student to select.

## 4. Configure the generic signup fallback (optional)

Tenant-specific `/signup?institution={subdomain}` links do not require this
step. Do it only if bare `/signup` should register students into this college,
and only after Step 2 has produced the real tenant UUID.

1. Open the frontend project in Vercel.
2. Go to **Settings → Environment Variables**.
3. Edit `NEXT_PUBLIC_DEFAULT_TENANT_ID`.
4. Replace its value with the real tenant UUID recorded in Step 2 and scope the
   value to **Production**. Save it.
5. Trigger a new production deployment: open **Deployments**, use the menu on
   the latest production deployment, and select **Redeploy**. A new commit to
   the production branch also triggers a new build.
6. Wait for the new production deployment to finish before testing signup.

`NEXT_PUBLIC_DEFAULT_TENANT_ID` is only the fallback used by generic `/signup`
when no `institution` query parameter is present. Institution-specific signup
links resolve the tenant from its public branding endpoint instead. The fallback
is embedded into the browser bundle during the Next.js build, so editing it in
Vercel requires a full production redeploy. This matches Vercel's documented
environment-variable deployment behavior:
https://vercel.com/docs/environment-variables/managing-environment-variables

## 5. Verify student self-signup before sharing the link

1. Open `/login/{subdomain}` in a private/incognito window and follow **Create a
   student account**. Confirm the destination is
   `/signup?institution={subdomain}` and shows the institution name/logo when a
   logo exists.
2. Confirm the course dropdown contains only the new college's courses. Select a
   course and confirm its level dropdown contains only that course's levels.
3. Register one temporary test student using a Course + Level from the new
   college.
4. If prompted, complete email confirmation, then sign in.
5. In the Supabase SQL Editor, verify the account was created as a student in
   the expected tenant and enrolled in the selected course:

   ```sql
   select
     u.email,
     p.tenant_id,
     p.role,
     c.id as course_id,
     c.name as course_name,
     l.id as course_level_id,
     l.name as course_level_name
   from auth.users u
   join public.profiles p on p.id = u.id
   left join public.enrollments e on e.profile_id = p.id
   left join public.courses c on c.id = e.course_id
   left join public.course_levels l on l.id = e.course_level_id
   where u.email = 'replace-with-test-student-email';
   ```

6. Confirm `role` is `student`, `tenant_id` exactly matches the new tenant UUID,
   and both course and level match the signup selections.
7. Sign in as the institution admin, open **Students**, confirm the student's name
   and email appear, then remove the temporary account if it is no longer
   needed.

After these checks pass, the production signup link is ready to share with the
college's students.
