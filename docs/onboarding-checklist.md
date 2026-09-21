# College onboarding checklist

Use this checklist for the single-college launch. Complete the steps in order.

Google sign-in requires the additional provider and redirect configuration in
[`docs/google-oauth-setup.md`](google-oauth-setup.md).

## 1. Preflight

- [ ] Confirm `migration-11-auth-hardening.sql` is applied in the production
  Supabase project. It forces public signups to be students and derives their
  tenant from the selected course.
- [ ] Confirm `migration-12-teacher-subjects.sql` is applied. It supports the
  institution admin's teacher subject assignments.
- [ ] Before enabling Google sign-in, confirm
  `migration-14-google-oauth-onboarding.sql` is applied and complete the Google
  provider setup in `docs/google-oauth-setup.md`.
- [ ] Confirm the production frontend and backend are healthy and the
  super-admin account can sign in.
- [ ] Decide the institution name, a unique lowercase subdomain slug, plan,
  first administrator's email, and a temporary password.
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
   backend features.

If administrator creation fails, the backend removes the newly created tenant
instead of leaving a tenant without its first admin. Correct the reported error
and submit the form again.

## 3. Create courses, subjects, and teachers

1. Sign in as the new `institution_admin` and complete the forced password
   change.
2. Open **Courses & subjects** and create every course students may select at
   signup. Open each course and add its subjects.
3. Open **Users**. For each teacher, enter the full name, email, temporary
   password, choose **Teacher**, choose the appropriate course, and select
   **Add user**.
4. The teacher is initially assigned to all subjects currently in the selected
   course. Use **Subjects** beside the teacher to review or narrow those
   assignments.
5. Give each teacher their temporary credentials securely. Teachers must set a
   new password on first login.

Create the courses before opening student signup. With no courses in the new
tenant, the signup form has nothing valid for a student to select.

## 4. Point production signup at the new tenant

Do this only after Step 2 has produced the real college tenant UUID.

1. Open the frontend project in Vercel.
2. Go to **Settings → Environment Variables**.
3. Edit `NEXT_PUBLIC_DEFAULT_TENANT_ID`.
4. Replace its value with the real tenant UUID recorded in Step 2 and scope the
   value to **Production**. Save it.
5. Trigger a new production deployment: open **Deployments**, use the menu on
   the latest production deployment, and select **Redeploy**. A new commit to
   the production branch also triggers a new build.
6. Wait for the new production deployment to finish before testing signup.

`NEXT_PUBLIC_DEFAULT_TENANT_ID` is embedded into the browser bundle during the
Next.js build. Editing it in Vercel does not change an already built deployment;
a full production redeploy is required before the new value takes effect. This
matches Vercel's documented environment-variable deployment behavior:
https://vercel.com/docs/environment-variables/managing-environment-variables

## 5. Verify student self-signup before sharing the link

1. Open the newly deployed `/signup` page in a private/incognito window.
2. Confirm the course dropdown contains the new college's courses and does not
   show courses from the local-development tenant.
3. Register one temporary test student using a course from the new college.
4. If prompted, complete email confirmation, then sign in.
5. In the Supabase SQL Editor, verify the account was created as a student in
   the expected tenant and enrolled in the selected course:

   ```sql
   select
     u.email,
     p.tenant_id,
     p.role,
     c.id as course_id,
     c.name as course_name
   from auth.users u
   join public.profiles p on p.id = u.id
   left join public.enrollments e on e.profile_id = p.id
   left join public.courses c on c.id = e.course_id
   where u.email = 'replace-with-test-student-email';
   ```

6. Confirm `role` is `student`, `tenant_id` exactly matches the new tenant UUID,
   and the course is the one selected during signup.
7. Sign in as the institution admin, open **Users**, confirm the student's name
   and email appear, then remove the temporary account if it is no longer
   needed.

After these checks pass, the production signup link is ready to share with the
college's students.
