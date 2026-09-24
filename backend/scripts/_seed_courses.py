"""
Seed ArivuPro's course + subjects and enroll an explicitly configured student.
Run AFTER migrations/migration-01-enrollments.sql has been applied in Supabase. Idempotent.
Deleted after it succeeds.

Run from backend/ (not from inside scripts/) so the `app` package resolves:
    python -m scripts._seed_courses
"""

import os

from app.lib.supabase import get_service_client

COURSE_NAME = "CA Foundation"
LEVEL_NAME = "Foundation"
SUBJECTS = ["Accounting", "Business Mathematics", "Business Economics"]
STUDENT_EMAIL = os.getenv("SEED_STUDENT_EMAIL", "").strip()
if not STUDENT_EMAIL:
    raise SystemExit("SEED_STUDENT_EMAIL is required for this development script.")

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
    print("Configured course already exists")
else:
    course_id = (
        service.table("courses")
        .insert({"tenant_id": tenant_id, "name": COURSE_NAME})
        .execute()
    ).data[0]["id"]
    print("Configured course created")

# 2) Operational level (idempotent by name within the course)
existing_level = (
    service.table("course_levels")
    .select("id")
    .eq("tenant_id", tenant_id)
    .eq("course_id", course_id)
    .ilike("name", LEVEL_NAME)
    .execute()
).data
if existing_level:
    level_id = existing_level[0]["id"]
else:
    level_id = (
        service.table("course_levels")
        .insert({"tenant_id": tenant_id, "course_id": course_id, "name": LEVEL_NAME})
        .execute()
    ).data[0]["id"]

# 3) Subjects under the level (idempotent by name)
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
            {
                "tenant_id": tenant_id,
                "course_id": course_id,
                "course_level_id": level_id,
                "name": name,
            }
        ).execute()
        print(f"  created subject: {name}")

# 4) Find the test student's user id (via their profile / auth)
users = service.auth.admin.list_users()
users = getattr(users, "users", users)
student = next((u for u in users if getattr(u, "email", None) == STUDENT_EMAIL), None)
if not student:
    raise SystemExit("Configured seed student was not found; create it first.")
student_id = student.id

# 5) Enroll the student in the course + level (idempotent via unique constraint)
already = (
    service.table("enrollments")
    .select("id")
    .eq("profile_id", student_id)
    .eq("course_id", course_id)
    .execute()
).data
if already:
    service.table("enrollments").update({"course_level_id": level_id}).eq(
        "id", already[0]["id"]
    ).execute()
    print(f"student already enrolled in {COURSE_NAME}")
else:
    service.table("enrollments").insert(
        {
            "tenant_id": tenant_id,
            "profile_id": student_id,
            "course_id": course_id,
            "course_level_id": level_id,
        }
    ).execute()
    print(f"student enrolled in {COURSE_NAME}")

print("Seed completed")
