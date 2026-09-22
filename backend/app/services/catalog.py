"""Global academic catalogue reads and tenant provisioning helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.lib.supabase_queries import select_all

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProvisionedCatalogSubject:
    course_id: str
    subject_id: str
    course_name_collision: bool
    subject_name_collision: bool


def catalog_tree(service, tenant_id: str | None = None) -> list[dict]:
    """Return active catalogue rows nested course → level → subject."""
    courses = (
        service.table("catalog_courses")
        .select("id, code, name, display_order")
        .eq("is_active", True)
        .order("display_order")
        .order("name")
        .execute()
        .data
        or []
    )
    levels = (
        service.table("catalog_course_levels")
        .select("id, catalog_course_id, name, display_order")
        .eq("is_active", True)
        .order("display_order")
        .order("name")
        .execute()
        .data
        or []
    )
    subjects = (
        service.table("catalog_course_subjects")
        .select("id, catalog_level_id, name")
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    offered_ids: set[str] = set()
    if tenant_id:
        offerings = select_all(
            service,
            "institution_offerings",
            "catalog_subject_id",
            configure=lambda query: query.eq("tenant_id", tenant_id),
            order_column="catalog_subject_id",
        )
        offered_ids = {str(row["catalog_subject_id"]) for row in offerings}

    subjects_by_level: dict[str, list[dict]] = {}
    for subject in subjects:
        subject_id = str(subject["id"])
        subjects_by_level.setdefault(str(subject["catalog_level_id"]), []).append(
            {
                "id": subject_id,
                "name": subject["name"],
                "offered": subject_id in offered_ids,
            }
        )

    levels_by_course: dict[str, list[dict]] = {}
    for level in levels:
        level_id = str(level["id"])
        level_subjects = subjects_by_level.get(level_id, [])
        if not level_subjects:
            continue
        levels_by_course.setdefault(str(level["catalog_course_id"]), []).append(
            {"id": level_id, "name": level["name"], "subjects": level_subjects}
        )

    return [
        {
            "id": str(course["id"]),
            "code": course["code"],
            "name": course["name"],
            "levels": levels_by_course.get(str(course["id"]), []),
        }
        for course in courses
        if levels_by_course.get(str(course["id"]))
    ]


def active_catalog_subject_ids(service, subject_ids: list[str]) -> set[str]:
    if not subject_ids:
        return set()
    rows = (
        service.table("catalog_course_subjects")
        .select("id, catalog_course_levels!inner(is_active, catalog_courses!inner(is_active))")
        .in_("id", subject_ids)
        .eq("is_active", True)
        .eq("catalog_course_levels.is_active", True)
        .eq("catalog_course_levels.catalog_courses.is_active", True)
        .execute()
        .data
        or []
    )
    return {str(row["id"]) for row in rows}


def provision_catalog_subject(
    service, *, tenant_id: str, catalog_subject_id: str
) -> ProvisionedCatalogSubject:
    """Invoke the atomic service-role-only provisioning RPC."""
    rows = (
        service.rpc(
            "provision_catalog_subject",
            {
                "p_tenant_id": tenant_id,
                "p_catalog_subject_id": catalog_subject_id,
            },
        )
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("Catalog provisioning returned no result.")
    row = rows[0]
    result = ProvisionedCatalogSubject(
        course_id=str(row["course_id"]),
        subject_id=str(row["subject_id"]),
        course_name_collision=bool(row.get("course_name_collision")),
        subject_name_collision=bool(row.get("subject_name_collision")),
    )
    if result.course_name_collision or result.subject_name_collision:
        logger.warning(
            "Catalog provisioning preserved same-name free-form rows",
            extra={
                "tenant_id": tenant_id,
                "catalog_subject_id": catalog_subject_id,
                "course_name_collision": result.course_name_collision,
                "subject_name_collision": result.subject_name_collision,
            },
        )
    return result
