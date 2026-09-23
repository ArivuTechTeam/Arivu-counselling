"""Authenticated figure image proxy (student figure delivery).

Serves an extracted document figure's PNG to any authenticated user in the
figure's OWN tenant, streamed from the private `question-figures` bucket via the
service-role client.

This is how STUDENTS see question figures while taking a quiz / practice /
challenge: the frontend fetches this endpoint with its normal bearer token and
renders the bytes as a `blob:` URL. Compared with handing a student a Supabase
signed URL, this gives (a) no signed-URL expiry mid-exam, (b) per-user
authorization, and (c) no cross-origin/CSP dependency.

Additive and isolated: teacher review keeps using signed URLs (unchanged).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.storage import FIGURES_BUCKET, download_bytes
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in
from app.services.selector import accessible_practice_question_ids, enrolled_subject_ids
from app.services.student_access import student_has_graded_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/figures", tags=["figures"])


def _student_can_view_figure(service, profile: CurrentProfile, figure_id: str) -> bool:
    """Require a graded question or a currently accessible practice question.

    Academic course/level scope alone is insufficient for batch-targeted quizzes:
    a student in another batch of the same level must not be able to fetch that
    quiz's figure directly. Completed attempts remain viewable even if a quiz is
    later archived.
    """
    questions = (
        service.table("questions").select("id, chapter_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("figure_id", figure_id)
        .eq("review_status", "approved")
        .execute().data or []
    )
    if not questions:
        return False
    question_ids = [str(row["id"]) for row in questions]
    if any(
        student_has_graded_question(service, question_id, profile)
        for question_id in question_ids
    ):
        return True

    allowed_subjects = enrolled_subject_ids(service, profile)
    if not allowed_subjects:
        return False

    chapter_ids = [row["chapter_id"] for row in questions if row.get("chapter_id")]
    academically_allowed: set[str] = set()
    if chapter_ids:
        chapters = select_all_in(
            service,
            "chapters",
            "id, subject_id",
            in_column="id",
            values=chapter_ids,
            configure=lambda q: q.eq("tenant_id", profile.tenant_id),
        )
        allowed_chapters = {
            str(row["id"])
            for row in chapters
            if row.get("subject_id") in allowed_subjects
        }
        academically_allowed.update(
            str(row["id"])
            for row in questions
            if row.get("chapter_id") in allowed_chapters
        )

    # A question may have no chapter but still belong to a subject through a
    # quiz set. Resolve that path without trusting a browser-supplied subject.
    links = select_all_in(
        service,
        "quiz_variant_questions",
        "question_id, variant_id",
        in_column="question_id",
        values=question_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    )
    variant_ids = [row["variant_id"] for row in links if row.get("variant_id")]
    variants = select_all_in(
        service,
        "quiz_variants",
        "id, quiz_set_id",
        in_column="id",
        values=variant_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    ) if variant_ids else []
    quiz_ids = [row["quiz_set_id"] for row in variants if row.get("quiz_set_id")]
    quizzes = select_all_in(
        service,
        "quiz_sets",
        "id, subject_id",
        in_column="id",
        values=quiz_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    ) if quiz_ids else []
    allowed_quiz_ids = {
        str(row["id"])
        for row in quizzes
        if row.get("subject_id") in allowed_subjects
    }
    allowed_variant_ids = {
        str(row["id"])
        for row in variants
        if row.get("quiz_set_id") in allowed_quiz_ids
    }
    academically_allowed.update(
        str(row["question_id"])
        for row in links
        if row.get("variant_id") in allowed_variant_ids
    )
    if not academically_allowed:
        return False
    return bool(
        accessible_practice_question_ids(
            service,
            sorted(academically_allowed),
            profile.tenant_id,
            profile,
        )
    )


@router.get("/{figure_id}")
def get_figure_image(
    figure_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> Response:
    """Stream a figure PNG if it belongs to the caller's tenant; 404 otherwise.

    Staff may view their tenant's figures. Students must additionally be enrolled
    in the subject of an approved linked question.
    """
    service = get_service_client()
    row = (
        service.table("document_figures")
        .select("storage_path, tenant_id")
        .eq("id", figure_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    data = row.data if row and row.data else None
    if not data or not data.get("storage_path"):
        raise HTTPException(status_code=404, detail="Figure not found.")
    if profile.role == "student" and not _student_can_view_figure(
        service, profile, figure_id
    ):
        raise HTTPException(status_code=404, detail="Figure not found.")
    if profile.role not in {"student", "teacher", "institution_admin", "super_admin"}:
        raise HTTPException(status_code=404, detail="Figure not found.")
    try:
        png = download_bytes(data["storage_path"], bucket=FIGURES_BUCKET)
    except Exception as exc:  # noqa: BLE001 - a storage miss is a 404 to the client
        logger.warning(
            "Figure image fetch failed for %s (%s)", figure_id, type(exc).__name__
        )
        raise HTTPException(status_code=404, detail="Figure image unavailable.") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
