"""Read-only learning views derived from committed handwritten evaluations."""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all
from app.services.evaluation_access import require_evaluation_enabled
from app.services.evaluation_learning import current_mistakes

router = APIRouter(prefix="/api/v1/handwritten-learning", tags=["handwritten-learning"])


def _target_student(service, profile: CurrentProfile, requested: UUID | None) -> str:
    if profile.role == "student":
        if requested is not None and str(requested) != profile.user_id:
            raise HTTPException(status_code=403, detail="Students can view only their own learning data")
        return profile.user_id
    if profile.role != "teacher" or requested is None:
        raise HTTPException(status_code=403, detail="Student or teacher access required")
    row = (service.table("profiles").select("id")
           .eq("id", str(requested)).eq("tenant_id", profile.tenant_id)
           .eq("role", "student").maybe_single().execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    return str(requested)


def _scope(profile: CurrentProfile, student_id: UUID | None) -> tuple[object, str]:
    service = get_service_client()
    require_evaluation_enabled(service, profile)
    return service, _target_student(service, profile, student_id)


@router.get("/mistakes")
def mistake_library(
    student_id: UUID | None = None,
    subject_id: UUID | None = None,
    severity: str | None = Query(default=None, pattern="^(minor|moderate|major)$"),
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    service, student = _scope(profile, student_id)
    rows = current_mistakes(
        service, tenant_id=profile.tenant_id, student_id=student,
        subject_id=str(subject_id) if subject_id else None, severity=severity,
    )
    return {"mistakes": rows}


@router.get("/revision-items")
def revision_items(
    student_id: UUID | None = None,
    subject_id: UUID | None = None,
    resolved: bool | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    service, student = _scope(profile, student_id)

    def configure(query):
        query = query.eq("tenant_id", profile.tenant_id).eq("student_id", student)
        if subject_id:
            query = query.eq("subject_id", str(subject_id))
        if resolved is not None:
            query = query.eq("is_resolved", resolved)
        return query

    rows = select_all(
        service, "handwritten_revision_items",
        "id,subject_id,chapter,title,description,priority,is_resolved,occurrence_count,"
        "marks_at_risk,source_count,resolution_source,resolved_at,last_seen_at,created_at,updated_at",
        configure=configure,
        order_column="updated_at", order_desc=True,
    )
    return {"revision_items": rows}


@router.get("/analytics")
def analytics_summary(
    subject_id: UUID,
    student_id: UUID | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    service, student = _scope(profile, student_id)
    row = (service.table("handwritten_student_analytics")
           .select("id,subject_id,total_attempts,avg_percentage,best_percentage,"
                   "latest_percentage,score_history,current_level,improvement_rate,updated_at")
           .eq("tenant_id", profile.tenant_id).eq("student_id", student)
           .eq("subject_id", str(subject_id)).maybe_single().execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Analytics not found")
    return row


@router.get("/weak-areas")
def weak_areas(
    student_id: UUID | None = None,
    subject_id: UUID | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Compute Option-A weak areas live; no stale analytics JSON is stored."""
    service, student = _scope(profile, student_id)
    mistakes = current_mistakes(
        service, tenant_id=profile.tenant_id, student_id=student,
        subject_id=str(subject_id) if subject_id else None,
    )
    categories: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_marks_lost": 0.0})
    for row in mistakes:
        bucket = categories[str(row.get("category") or "conceptual")]
        bucket["count"] += 1
        bucket["total_marks_lost"] = round(
            bucket["total_marks_lost"] + float(row.get("marks_lost") or 0), 1
        )

    def configure(query):
        query = (query.eq("tenant_id", profile.tenant_id).eq("student_id", student)
                 .eq("is_resolved", False))
        return query.eq("subject_id", str(subject_id)) if subject_id else query

    revision = select_all(
        service, "handwritten_revision_items",
        "subject_id,chapter,title,marks_at_risk,source_count,priority,last_seen_at",
        configure=configure, order_column="marks_at_risk", order_desc=True,
    )
    patterns = [{"category": category, **values} for category, values in categories.items()]
    patterns.sort(key=lambda row: (-row["total_marks_lost"], row["category"]))
    return {"weak_chapters": revision, "mistake_patterns": patterns}
