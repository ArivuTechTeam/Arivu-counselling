"""
Seed ArivuPro's course + subjects and enroll the test student.
Run AFTER migration-01-enrollments.sql has been applied in Supabase. Idempotent.
Deleted after it succeeds.

Run from backend/ (not from inside scripts/) so the `app` package resolves:
    python -m scripts._seed_courses
"""

from app.lib.supabase import get_service_client

COURSE_NAME = "CA Foundation"
SUBJECTS = ["Accounting", "Business Mathematics", "Business Economics"]
STUDENT_EMAIL = "student.test@arivupro.com"

service = get_service_client()

tenant_id = (
    service.table("tenants").select("id").eq("subdomain", "arivupro").single().execute()
).data["id"]

# 1) Course (idempotent by name within tenant)
existing = (
    service.table("courses")
    .select("id")
    .eq("tenant_id", tenant_id)
    .eq("name", COURSE_NAME)
    .execute()
).data
if existing:
    course_id = existing[0]["id"]
    print(f"course exists: {COURSE_NAME} = {course_id}")
else:
    course_id = (
        service.table("courses")
        .insert({"tenant_id": tenant_id, "name": COURSE_NAME})
        .execute()
    ).data[0]["id"]
    print(f"created course: {COURSE_NAME} = {course_id}")

# 2) Subjects under the course (idempotent by name)
for name in SUBJECTS:
    found = (
        service.table("subjects")
        .select("id")
        .eq("course_id", course_id)
        .eq("name", name)
        .execute()
    ).data
    if found:
        print(f"  subject exists: {name}")
    else:
        service.table("subjects").insert(
            {"tenant_id": tenant_id, "course_id": course_id, "name": name}
        ).execute()
        print(f"  created subject: {name}")

# 3) Find the test student's user id (via their profile / auth)
users = service.auth.admin.list_users()
users = getattr(users, "users", users)
student = next((u for u in users if getattr(u, "email", None) == STUDENT_EMAIL), None)
if not student:
    raise SystemExit(f"{STUDENT_EMAIL} not found — create the student first.")
student_id = student.id

# 4) Enroll the student in the course (idempotent via unique constraint)
already = (
    service.table("enrollments")
    .select("id")
    .eq("profile_id", student_id)
    .eq("course_id", course_id)
    .execute()
).data
if already:
    print(f"already enrolled: {STUDENT_EMAIL} in {COURSE_NAME}")
else:
    service.table("enrollments").insert(
        {"tenant_id": tenant_id, "profile_id": student_id, "course_id": course_id}
    ).execute()
    print(f"enrolled {STUDENT_EMAIL} in {COURSE_NAME}")

print(f"\nDONE. course_id={course_id}")
