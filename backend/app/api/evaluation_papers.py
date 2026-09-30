"""Teacher endpoints for standalone handwritten-evaluation papers."""

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_teacher
from app.lib.storage import (
    EVALUATION_PAPERS_BUCKET,
    delete_bytes,
    signed_url,
    upload_bytes,
)
from app.lib.supabase import get_service_client
from app.services.evaluation_access import (
    assigned_evaluation_subject_ids,
    require_evaluation_enabled,
    require_teacher_paper_scope,
)
from app.services.evaluation_files import (
    ALLOWED_EVALUATION_TYPES,
    validate_file_bytes,
)


router = APIRouter(prefix="/api/v1/evaluation-papers", tags=["evaluation-papers"])


class EvaluationPaperResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    course_level_id: UUID
    subject_id: UUID
    title: str
    total_marks: float
    mcq_marks: float | None = None
    rubric_status: str
    is_active: bool
    generated_paper_id: UUID | None = None
    created_by: UUID
    created_at: str
    question_paper_url: str | None = None
    suggested_answer_url: str | None = None
    has_suggested_answer: bool = False
    question_paper_text: str | None = None
    suggested_answer_text: str | None = None
    structured_qa: list[dict[str, Any]] = Field(default_factory=list)
    rubric_source: str | None = None
    rubric_error: str = ""
    subject_name: str | None = None
    course_name: str | None = None
    level_name: str | None = None
    submission_count: int = 0


class EvaluationPaperListResponse(BaseModel):
    papers: list[EvaluationPaperResponse]


def _as_response(row: dict[str, Any], include_urls: bool = False) -> EvaluationPaperResponse:
    values = dict(row)
    if not isinstance(values.get("structured_qa"), list):
        values["structured_qa"] = []
    values["has_suggested_answer"] = bool(values.get("suggested_answer_storage_path"))
    values["question_paper_url"] = None
    values["suggested_answer_url"] = None
    if include_urls:
        values["question_paper_url"] = signed_url(
            values["question_paper_storage_path"], 300, bucket=EVALUATION_PAPERS_BUCKET
        )
        if values.get("suggested_answer_storage_path"):
            values["suggested_answer_url"] = signed_url(
                values["suggested_answer_storage_path"], 300, bucket=EVALUATION_PAPERS_BUCKET
            )
    return EvaluationPaperResponse.model_validate(values)


def _first(client, table: str, columns: str, **filters: object) -> dict[str, Any] | None:
    query = client.table(table).select(columns)
    for key, value in filters.items():
        query = query.eq(key, value)
    result = query.limit(1).execute()
    return result.data[0] if result.data else None


def _decorate_paper(client, row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Add the display metadata used by the teacher paper-management view."""
    values = dict(row)
    subject = _first(
        client,
        "subjects",
        "id,name,course_id,course_level_id",
        id=values.get("subject_id"),
        tenant_id=tenant_id,
    )
    level = _first(
        client,
        "course_levels",
        "id,name,course_id",
        id=values.get("course_level_id"),
        tenant_id=tenant_id,
    )
    course_id = (subject or {}).get("course_id") or (level or {}).get("course_id")
    course = (
        _first(client, "courses", "id,name", id=course_id, tenant_id=tenant_id)
        if course_id
        else None
    )
    submissions = (
        client.table("handwritten_submissions")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("evaluation_paper_id", str(values["id"]))
        .execute()
        .data
        or []
    )
    values.update(
        subject_name=(subject or {}).get("name"),
        level_name=(level or {}).get("name"),
        course_name=(course or {}).get("name"),
        submission_count=len(submissions),
    )
    return values


def _manager_paper(client, profile: CurrentProfile, paper_id: UUID) -> dict[str, Any]:
    if profile.role not in {"teacher", "institution_admin"}:
        raise HTTPException(status_code=403, detail="Evaluation-paper management denied")
    result = (
        client.table("evaluation_papers").select("*")
        .eq("id", str(paper_id)).eq("tenant_id", profile.tenant_id)
        .limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Evaluation paper not found")
    row = result.data[0]
    if profile.role == "teacher":
        require_teacher_paper_scope(
            client,
            profile,
            course_level_id=str(row["course_level_id"]),
            subject_id=str(row["subject_id"]),
        )
    return row


def _require_target_paper_scope(
    client,
    profile: CurrentProfile,
    *,
    course_level_id: str,
    subject_id: str,
) -> None:
    """Validate an edited paper's target classification inside the tenant."""
    if profile.role == "teacher":
        require_teacher_paper_scope(
            client,
            profile,
            course_level_id=course_level_id,
            subject_id=subject_id,
        )
        return
    subject = (
        client.table("subjects")
        .select("id")
        .eq("tenant_id", profile.tenant_id)
        .eq("id", subject_id)
        .eq("course_level_id", course_level_id)
        .maybe_single()
        .execute()
    )
    if not subject or not subject.data:
        raise HTTPException(404, "Subject and course level not found.")


async def _read_upload(upload: UploadFile) -> tuple[bytes, str, str]:
    try:
        data = await upload.read(30 * 1024 * 1024 + 1)
        content_type = (upload.content_type or "").lower()
        validate_file_bytes(data, content_type)
        return data, content_type, "." + ALLOWED_EVALUATION_TYPES[content_type]
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await upload.close()


@router.post("", response_model=EvaluationPaperResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation_paper(
    course_level_id: UUID = Form(...),
    subject_id: UUID = Form(...),
    title: str = Form(..., min_length=1, max_length=200),
    total_marks: float = Form(..., gt=0),
    mcq_marks: float | None = Form(None, ge=0),
    generated_paper_id: UUID | None = Form(None),
    question_paper: UploadFile = File(...),
    suggested_answer: UploadFile | None = File(None),
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationPaperResponse:
    require_teacher(profile, action="create evaluation papers")
    # Direct unit calls do not pass through FastAPI's Form parser, so optional
    # defaults remain Form metadata rather than a runtime value.
    if not isinstance(mcq_marks, (int, float)):
        mcq_marks = None
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    require_teacher_paper_scope(
        client,
        profile,
        course_level_id=str(course_level_id),
        subject_id=str(subject_id),
    )
    if mcq_marks is not None and mcq_marks > total_marks:
        raise HTTPException(status_code=400, detail="MCQ marks cannot exceed total marks")

    if generated_paper_id is not None:
        generated = (
            client.table("generated_papers")
            .select("id")
            .eq("id", str(generated_paper_id))
            .eq("tenant_id", profile.tenant_id)
            .limit(1)
            .execute()
        )
        if not generated.data:
            raise HTTPException(status_code=400, detail="Generated-paper provenance is invalid")

    question_bytes, question_type, question_ext = await _read_upload(question_paper)
    answer_payload: tuple[bytes, str, str] | None = None
    if suggested_answer is not None:
        answer_payload = await _read_upload(suggested_answer)

    paper_id = uuid4()
    base_path = f"{profile.tenant_id}/{paper_id}"
    question_path = f"{base_path}/question-paper{question_ext}"
    answer_path = f"{base_path}/suggested-answer{answer_payload[2]}" if answer_payload else None
    uploaded_paths: list[str] = []
    try:
        upload_bytes(
            question_path,
            question_bytes,
            question_type,
            bucket=EVALUATION_PAPERS_BUCKET,
        )
        uploaded_paths.append(question_path)
        if answer_payload and answer_path:
            upload_bytes(
                answer_path,
                answer_payload[0],
                answer_payload[1],
                bucket=EVALUATION_PAPERS_BUCKET,
            )
            uploaded_paths.append(answer_path)

        inserted = (
            client.table("evaluation_papers")
            .insert(
                {
                    "id": str(paper_id),
                    "tenant_id": profile.tenant_id,
                    "course_level_id": str(course_level_id),
                    "subject_id": str(subject_id),
                    "title": title.strip(),
                    "question_paper_storage_path": question_path,
                    "suggested_answer_storage_path": answer_path,
                    "total_marks": total_marks,
                    "mcq_marks": mcq_marks,
                    "generated_paper_id": str(generated_paper_id) if generated_paper_id else None,
                    "created_by": profile.user_id,
                }
            )
            .execute()
        )
        if not inserted.data:
            raise RuntimeError("Evaluation paper insert returned no row")
        return _as_response(
            _decorate_paper(client, inserted.data[0], profile.tenant_id),
            include_urls=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        for path in uploaded_paths:
            try:
                delete_bytes(path, bucket=EVALUATION_PAPERS_BUCKET)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Could not create evaluation paper") from exc


@router.get("", response_model=EvaluationPaperListResponse)
async def list_evaluation_papers(
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationPaperListResponse:
    if profile.role not in {"teacher", "institution_admin"}:
        raise HTTPException(status_code=403, detail="Evaluation-paper access denied")
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    query = client.table("evaluation_papers").select(
        "id,tenant_id,course_level_id,subject_id,title,total_marks,mcq_marks,"
        "rubric_status,is_active,generated_paper_id,created_by,created_at,"
        "suggested_answer_storage_path"
    ).eq("tenant_id", profile.tenant_id)
    if profile.role == "teacher":
        subject_ids = assigned_evaluation_subject_ids(client, profile)
        if not subject_ids:
            return EvaluationPaperListResponse(papers=[])
        query = query.in_("subject_id", sorted(subject_ids))
    result = query.order("created_at", desc=True).execute()
    return EvaluationPaperListResponse(
        papers=[
            _as_response(_decorate_paper(client, row, profile.tenant_id))
            for row in (result.data or [])
        ]
    )


@router.get("/{paper_id}", response_model=EvaluationPaperResponse)
async def get_evaluation_paper(
    paper_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationPaperResponse:
    if profile.role not in {"teacher", "institution_admin"}:
        raise HTTPException(status_code=403, detail="Evaluation-paper access denied")
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    row = _manager_paper(client, profile, paper_id)
    try:
        return _as_response(
            _decorate_paper(client, row, profile.tenant_id),
            include_urls=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not create download URLs") from exc


@router.patch("/{paper_id}", response_model=EvaluationPaperResponse)
async def update_evaluation_paper(
    paper_id: UUID,
    course_level_id: UUID | None = Form(None),
    subject_id: UUID | None = Form(None),
    title: str | None = Form(None, min_length=1, max_length=200),
    total_marks: float | None = Form(None, gt=0),
    mcq_marks: float | None = Form(None, ge=0),
    clear_mcq_marks: bool = Form(False),
    is_active: bool | None = Form(None),
    question_paper: UploadFile | None = File(None),
    suggested_answer: UploadFile | None = File(None),
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationPaperResponse:
    client = get_service_client()
    if not isinstance(course_level_id, UUID):
        course_level_id = None
    if not isinstance(subject_id, UUID):
        subject_id = None
    if not isinstance(mcq_marks, (int, float)):
        mcq_marks = None
    if not isinstance(total_marks, (int, float)):
        total_marks = None
    if not isinstance(title, str):
        title = None
    if not isinstance(is_active, bool):
        is_active = None
    if not isinstance(clear_mcq_marks, bool):
        clear_mcq_marks = False
    if not isinstance(question_paper, UploadFile):
        question_paper = None
    if not isinstance(suggested_answer, UploadFile):
        suggested_answer = None
    require_evaluation_enabled(client, profile)
    current = _manager_paper(client, profile, paper_id)
    effective_level_id = str(course_level_id or current["course_level_id"])
    effective_subject_id = str(subject_id or current["subject_id"])
    if course_level_id is not None or subject_id is not None:
        _require_target_paper_scope(
            client,
            profile,
            course_level_id=effective_level_id,
            subject_id=effective_subject_id,
        )
    effective_total = total_marks if total_marks is not None else float(current["total_marks"])
    effective_mcq = (
        None if clear_mcq_marks
        else mcq_marks if mcq_marks is not None
        else current.get("mcq_marks")
    )
    if effective_mcq is not None and float(effective_mcq) > effective_total:
        raise HTTPException(status_code=400, detail="MCQ marks cannot exceed total marks")

    changes: dict[str, Any] = {}
    if course_level_id is not None:
        changes["course_level_id"] = str(course_level_id)
    if subject_id is not None:
        changes["subject_id"] = str(subject_id)
    if title is not None:
        changes["title"] = title.strip()
    if total_marks is not None:
        changes["total_marks"] = total_marks
    if clear_mcq_marks:
        changes["mcq_marks"] = None
    elif mcq_marks is not None:
        changes["mcq_marks"] = mcq_marks
    if is_active is not None:
        changes["is_active"] = is_active
    old_paths: list[str] = []
    uploaded_paths: list[str] = []
    rubric_changed = total_marks is not None or mcq_marks is not None or clear_mcq_marks
    try:
        if question_paper is not None:
            data, content_type, extension = await _read_upload(question_paper)
            path = f"{profile.tenant_id}/{paper_id}/question-paper-{uuid4()}{extension}"
            upload_bytes(path, data, content_type, bucket=EVALUATION_PAPERS_BUCKET)
            uploaded_paths.append(path)
            old_paths.append(current["question_paper_storage_path"])
            changes["question_paper_storage_path"] = path
            rubric_changed = True
        if suggested_answer is not None:
            data, content_type, extension = await _read_upload(suggested_answer)
            path = f"{profile.tenant_id}/{paper_id}/suggested-answer-{uuid4()}{extension}"
            upload_bytes(path, data, content_type, bucket=EVALUATION_PAPERS_BUCKET)
            uploaded_paths.append(path)
            if current.get("suggested_answer_storage_path"):
                old_paths.append(current["suggested_answer_storage_path"])
            changes["suggested_answer_storage_path"] = path
            rubric_changed = True
        if changes:
            updated = (
                client.table("evaluation_papers").update(changes)
                .eq("id", str(paper_id)).eq("tenant_id", profile.tenant_id).execute()
            )
            if not updated.data:
                raise RuntimeError("Evaluation paper update returned no row")
        if rubric_changed and not client.rpc(
            "reset_evaluation_rubric",
            {"p_tenant": profile.tenant_id, "p_paper": str(paper_id)},
        ).execute().data:
            raise RuntimeError("Could not requeue the paper rubric")
        for path in old_paths:
            try:
                delete_bytes(path, bucket=EVALUATION_PAPERS_BUCKET)
            except Exception:
                pass
        refreshed = _manager_paper(client, profile, paper_id)
        return _as_response(
            _decorate_paper(client, refreshed, profile.tenant_id),
            include_urls=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        for path in uploaded_paths:
            try:
                delete_bytes(path, bucket=EVALUATION_PAPERS_BUCKET)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Could not update evaluation paper") from exc


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evaluation_paper(
    paper_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> None:
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    current = _manager_paper(client, profile, paper_id)
    client.table("evaluation_papers").delete().eq("id", str(paper_id)).eq(
        "tenant_id", profile.tenant_id
    ).execute()
    paths = [
        path
        for path in (
            current.get("question_paper_storage_path"),
            current.get("suggested_answer_storage_path"),
        )
        if path
    ]
    if paths:
        try:
            delete_bytes(paths, bucket=EVALUATION_PAPERS_BUCKET)
        except Exception:
            pass
