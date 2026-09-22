"""Build tenant-scoped operational course -> level -> subject trees."""

from __future__ import annotations

from app.lib.supabase_queries import select_all


def institution_offerings_by_tenant(
    service, tenant_ids: list[str] | set[str]
) -> dict[str, list[dict]]:
    """Return complete operational academic trees for the requested tenants.

    These rows come from ``courses``, ``course_levels`` and ``subjects`` rather
    than the global catalogue. The result therefore includes both catalogue
    offerings provisioned by a super admin and courses an institution admin
    created manually.
    """
    requested = sorted({str(tenant_id) for tenant_id in tenant_ids if tenant_id})
    if not requested:
        return {}

    courses = select_all(
        service,
        "courses",
        "id, tenant_id, name",
        configure=lambda query: query.in_("tenant_id", requested),
    )
    levels = select_all(
        service,
        "course_levels",
        "id, tenant_id, course_id, name",
        configure=lambda query: query.in_("tenant_id", requested),
    )
    subjects = select_all(
        service,
        "subjects",
        "id, tenant_id, course_id, course_level_id, name",
        configure=lambda query: query.in_("tenant_id", requested),
    )

    subjects_by_level: dict[str, list[dict]] = {}
    for subject in subjects:
        level_id = str(subject.get("course_level_id") or "")
        if not level_id:
            continue
        subjects_by_level.setdefault(level_id, []).append(
            {"id": str(subject["id"]), "name": subject["name"]}
        )
    for rows in subjects_by_level.values():
        rows.sort(key=lambda row: (row["name"] or "").casefold())

    levels_by_course: dict[str, list[dict]] = {}
    for level in levels:
        course_id = str(level["course_id"])
        levels_by_course.setdefault(course_id, []).append(
            {
                "id": str(level["id"]),
                "name": level["name"],
                "subjects": subjects_by_level.get(str(level["id"]), []),
            }
        )
    for rows in levels_by_course.values():
        rows.sort(key=lambda row: (row["name"] or "").casefold())

    result = {tenant_id: [] for tenant_id in requested}
    for course in courses:
        tenant_id = str(course["tenant_id"])
        result.setdefault(tenant_id, []).append(
            {
                "id": str(course["id"]),
                "name": course["name"],
                "levels": levels_by_course.get(str(course["id"]), []),
            }
        )
    for rows in result.values():
        rows.sort(key=lambda row: (row["name"] or "").casefold())
    return result


def offering_counts(courses: list[dict]) -> dict[str, int]:
    """Return compact counts for an institution directory row."""
    levels = [level for course in courses for level in course["levels"]]
    subjects = [subject for level in levels for subject in level["subjects"]]
    return {
        "course_count": len(courses),
        "level_count": len(levels),
        "subject_count": len(subjects),
    }
