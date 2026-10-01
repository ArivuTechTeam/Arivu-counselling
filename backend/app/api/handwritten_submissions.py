"""Student upload and submission endpoints for handwritten evaluation."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError as PostgrestAPIError
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.storage import (
    EVALUATION_PAPERS_BUCKET,
    EVALUATION_SUBMISSIONS_BUCKET,
    delete_bytes,
    download_bytes,
    signed_url,
    signed_upload,
)
from app.lib.supabase import get_service_client
from app.services.evaluation_access import (
    require_evaluation_enabled,
    require_teacher_evaluation_paper_access,
    student_can_access_paper,
)
from app.services.evaluation_files import (
    ALLOWED_EVALUATION_TYPES,
    MAX_EVALUATION_FILE_BYTES,
    safe_filename,
    validate_file_bytes,
)


router = APIRouter(prefix="/api/v1/handwritten-evaluations", tags=["handwritten-evaluations"])


class EvaluationPaperSummary(BaseModel):
    id: UUID
    title: str
    course_level_id: UUID
    subject_id: UUID
    total_marks: float
    mcq_marks: float | None = None
    question_paper_url: str
    subject_name: str | None = None
    course_name: str | None = None
    level_name: str | None = None
    paper_type: str = "mock_test"
    created_at: str | None = None
    completed_attempts: int
    attempt_limit: int
    remaining_attempts: int
    quota_active: bool


class EvaluationPaperSummaryList(BaseModel):
    papers: list[EvaluationPaperSummary]


class UploadIntentRequest(BaseModel):
    paper_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=MAX_EVALUATION_FILE_BYTES)


class UploadIntentResponse(BaseModel):
    id: UUID
    paper_id: UUID | None
    upload_url: str
    upload_token: str
    storage_path: str
    expires_at: str


class FinalizedIntentResponse(BaseModel):
    id: UUID
    status: str
    verified_at: str


class CreateSubmissionRequest(BaseModel):
    upload_intent_id: UUID


class SubmissionResponse(BaseModel):
    id: UUID
    paper_id: UUID | None
    upload_intent_id: UUID | None
    status: str
    submitted_at: str
    job_id: UUID | None = None
    job_status: str | None = None
    report_available: bool = False
    paper_title: str | None = None
    subject_name: str | None = None
    marks_obtained: float | None = None
    marks_possible: float | None = None
    percentage: float | None = None
    evaluation_date: str | None = None
    error_message: str | None = None
    retrigger_count: int = 0
    regraded_from: UUID | None = None


class SubmissionResponseList(BaseModel):
    submissions: list[SubmissionResponse]


class FacultySubmissionResponse(SubmissionResponse):
    student_id: UUID
    student_name: str | None = None
    student_email: str | None = None


class FacultySubmissionResponseList(BaseModel):
    submissions: list[FacultySubmissionResponse]


class AnswerScriptUrlResponse(BaseModel):
    url: str


class EvaluationReportPaper(BaseModel):
    id: UUID | None
    title: str
    subject: str | None = None
    total_marks: float


class EvaluationReportStudent(BaseModel):
    name: str | None = None
    email: str | None = None


class EvaluationQuestionReport(BaseModel):
    question_ref: str
    question_text: str
    marks_obtained: float
    marks_possible: float
    not_attempted: bool
    not_evaluated: bool
    not_counted: bool
    mapping_status: str
    feedback: str
    student_guidance: dict[str, Any]
    student_answer_excerpt: str
    handwriting_legibility: str
    grading_confidence: float
    criteria_breakdown: list[dict[str, Any]]


class EvaluationReportResponse(BaseModel):
    submission_id: UUID
    status: str
    submission_date: str
    evaluation_date: str
    paper: EvaluationReportPaper
    student: EvaluationReportStudent
    total_score: float
    total_marks: float
    percentage: float
    overall_feedback: str
    strengths: list[str]
    areas_to_improve: list[str]
    requires_review: bool
    answer_script_url: str | None = None
    questions: list[EvaluationQuestionReport]


class AdditionalPagesRequest(BaseModel):
    upload_intent_id: UUID


class SubmissionQuotaResponse(BaseModel):
    paper_id: UUID
    completed_attempts: int
    attempt_limit: int
    remaining_attempts: int
    active: bool


class MarkFailedRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class Stage2ArtifactResponse(BaseModel):
    id: UUID
    evaluation_id: UUID
    sequence: int
    route: str
    model: str
    prompt_revision: str
    raw_content: str
    content_bytes: int
    content_sha256: str
    content_omitted: bool
    created_at: str


class Stage2ArtifactListResponse(BaseModel):
    artifacts: list[Stage2ArtifactResponse]


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student access required")


async def _load_paper(profile: CurrentProfile, paper_id: UUID) -> dict[str, Any]:
    result = (
        get_service_client()
        .table("evaluation_papers")
        .select("*")
        .eq("id", str(paper_id))
        .eq("tenant_id", profile.tenant_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Evaluation paper not found")
    paper = result.data[0]
    if not student_can_access_paper(get_service_client(), profile, paper):
        raise HTTPException(status_code=403, detail="You are not enrolled for this paper")
    return paper


async def _require_student_feature(profile: CurrentProfile) -> None:
    _require_student(profile)
    require_evaluation_enabled(get_service_client(), profile)


def _first(client, table: str, columns: str, **filters: object) -> dict[str, Any] | None:
    query = client.table(table).select(columns)
    for key, value in filters.items():
        query = query.eq(key, value)
    result = query.limit(1).execute()
    if not result.data:
        return None
    return result.data[0]


def _paper_metadata(client, paper: dict[str, Any], tenant_id: str) -> dict[str, str | None]:
    subject = _first(
        client,
        "subjects",
        "id,name,course_id,course_level_id",
        id=paper.get("subject_id"),
        tenant_id=tenant_id,
    )
    level = _first(
        client,
        "course_levels",
        "id,name,course_id",
        id=paper.get("course_level_id"),
        tenant_id=tenant_id,
    )
    course_id = (subject or {}).get("course_id") or (level or {}).get("course_id")
    course = (
        _first(client, "courses", "id,name", id=course_id, tenant_id=tenant_id)
        if course_id
        else None
    )
    return {
        "subject_name": (subject or {}).get("name"),
        "level_name": (level or {}).get("name"),
        "course_name": (course or {}).get("name"),
    }


def _submission_quotas_by_paper(
    client,
    *,
    tenant_id: str,
    student_id: str,
    paper_ids: list[str],
    attempt_limit: int,
) -> dict[str, dict[str, int | bool]]:
    """Load attempt usage for one or more papers with three bounded queries."""
    quotas = {
        paper_id: {
            "completed_attempts": 0,
            "attempt_limit": attempt_limit,
            "remaining_attempts": attempt_limit,
            "quota_active": False,
        }
        for paper_id in paper_ids
    }
    if not paper_ids:
        return quotas

    submissions = (
        client.table("handwritten_submissions")
        .select("id,evaluation_paper_id")
        .eq("tenant_id", tenant_id)
        .eq("student_id", student_id)
        .in_("evaluation_paper_id", paper_ids)
        .execute()
        .data
        or []
    )
    submission_ids = [str(row["id"]) for row in submissions]
    if not submission_ids:
        return quotas

    completed_ids = {
        str(row["submission_id"])
        for row in (
            client.table("handwritten_evaluations")
            .select("submission_id")
            .eq("tenant_id", tenant_id)
            .in_("submission_id", submission_ids)
            .execute()
            .data
            or []
        )
    }
    active_ids = {
        str(row["submission_id"])
        for row in (
            client.table("evaluation_jobs")
            .select("submission_id,status")
            .eq("tenant_id", tenant_id)
            .in_("submission_id", submission_ids)
            .execute()
            .data
            or []
        )
        if row.get("status") in {"queued", "claimed", "processing"}
        and str(row["submission_id"]) not in completed_ids
    }

    for submission in submissions:
        paper_id = str(submission["evaluation_paper_id"])
        submission_id = str(submission["id"])
        quota = quotas[paper_id]
        if submission_id in completed_ids:
            quota["completed_attempts"] = int(quota["completed_attempts"]) + 1
        if submission_id in active_ids:
            quota["quota_active"] = True
    for quota in quotas.values():
        quota["remaining_attempts"] = max(
            attempt_limit - int(quota["completed_attempts"]), 0
        )
    return quotas


@router.get("/papers", response_model=EvaluationPaperSummaryList)
async def list_available_papers(
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationPaperSummaryList:
    await _require_student_feature(profile)
    result = (
        get_service_client()
        .table("evaluation_papers")
        .select(
            "id,title,course_level_id,subject_id,total_marks,"
            "mcq_marks,question_paper_storage_path,created_at"
        )
        .eq("tenant_id", profile.tenant_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    client = get_service_client()
    accessible_rows = [
        paper for paper in (result.data or [])
        if student_can_access_paper(client, profile, paper)
    ]
    settings = get_settings()
    quotas = _submission_quotas_by_paper(
        client,
        tenant_id=profile.tenant_id,
        student_id=profile.user_id,
        paper_ids=[str(paper["id"]) for paper in accessible_rows],
        attempt_limit=settings.handwritten_evaluation_attempts_per_paper,
    )
    accessible: list[EvaluationPaperSummary] = []
    for paper in accessible_rows:
        paper["question_paper_url"] = signed_url(
            paper["question_paper_storage_path"],
            300,
            bucket=EVALUATION_PAPERS_BUCKET,
        )
        paper.update(_paper_metadata(client, paper, profile.tenant_id))
        paper.update(quotas[str(paper["id"])])
        accessible.append(EvaluationPaperSummary.model_validate(paper))
    return EvaluationPaperSummaryList(papers=accessible)


@router.post("/upload-intents", response_model=UploadIntentResponse, status_code=201)
async def create_upload_intent(
    body: UploadIntentRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> UploadIntentResponse:
    await _require_student_feature(profile)
    await _load_paper(profile, body.paper_id)
    try:
        extension = "." + ALLOWED_EVALUATION_TYPES[body.content_type.lower()]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Only PDF, PNG and JPEG files are supported.") from exc
    intent_id = uuid4()
    path = f"{profile.tenant_id}/{profile.user_id}/{intent_id}{extension}"
    client = get_service_client()
    inserted = (
        client.table("evaluation_upload_intents")
        .insert(
            {
                "id": str(intent_id),
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "evaluation_paper_id": str(body.paper_id),
                "storage_path": path,
                "original_filename": safe_filename(body.filename),
                "content_type": body.content_type.lower(),
                "expected_size": body.size_bytes,
                "purpose": "primary",
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Could not create upload intent")
    try:
        signed = signed_upload(path, bucket=EVALUATION_SUBMISSIONS_BUCKET)
    except Exception as exc:
        client.table("evaluation_upload_intents").update({"status": "failed"}).eq(
            "id", str(intent_id)
        ).execute()
        raise HTTPException(status_code=503, detail="Could not create upload URL") from exc
    row = inserted.data[0]
    return UploadIntentResponse(
        id=intent_id,
        paper_id=body.paper_id,
        upload_url=signed["signed_url"],
        upload_token=signed.get("token"),
        storage_path=path,
        expires_at=row["expires_at"],
    )


@router.post("/upload-intents/{intent_id}/finalize", response_model=FinalizedIntentResponse)
async def finalize_upload_intent(
    intent_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> FinalizedIntentResponse:
    await _require_student_feature(profile)
    client = get_service_client()
    result = (
        client.table("evaluation_upload_intents")
        .select("*")
        .eq("id", str(intent_id))
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Upload intent not found")
    intent = result.data[0]
    if intent["status"] == "verified":
        return FinalizedIntentResponse(
            id=intent_id, status="verified", verified_at=intent["verified_at"]
        )
    if intent["status"] != "pending":
        raise HTTPException(status_code=409, detail="Upload intent cannot be finalized")
    expires_at = datetime.fromisoformat(intent["expires_at"].replace("Z", "+00:00"))
    if expires_at <= datetime.now(UTC):
        client.table("evaluation_upload_intents").update({"status": "failed"}).eq(
            "id", str(intent_id)
        ).execute()
        raise HTTPException(status_code=410, detail="Upload intent expired")

    mismatch = False
    try:
        data = download_bytes(intent["storage_path"], bucket=EVALUATION_SUBMISSIONS_BUCKET)
        if len(data) != intent["expected_size"]:
            mismatch = True
        else:
            validate_file_bytes(data, intent["content_type"])
    except Exception:
        mismatch = True
    if mismatch:
        try:
            delete_bytes(intent["storage_path"], bucket=EVALUATION_SUBMISSIONS_BUCKET)
        finally:
            client.table("evaluation_upload_intents").update({"status": "failed"}).eq(
                "id", str(intent_id)
            ).execute()
        raise HTTPException(status_code=400, detail="Uploaded file did not match the intent")

    verified_at = datetime.now(UTC).isoformat()
    updated = (
        client.table("evaluation_upload_intents")
        .update({"status": "verified", "verified_at": verified_at})
        .eq("id", str(intent_id))
        .eq("status", "pending")
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=409, detail="Upload intent changed while finalizing")
    return FinalizedIntentResponse(id=intent_id, status="verified", verified_at=verified_at)


@router.post("/submissions", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    body: CreateSubmissionRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionResponse:
    await _require_student_feature(profile)
    settings = get_settings()
    if not settings.evaluation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Evaluation processing is currently disabled")
    try:
        result = get_service_client().rpc(
            "create_limited_handwritten_submission_job",
            {
                "p_tenant": profile.tenant_id,
                "p_student": profile.user_id,
                "p_intent": str(body.upload_intent_id),
                "p_limit": settings.handwritten_evaluation_attempts_per_paper,
            },
        ).execute()
    except PostgrestAPIError as exc:
        if exc.message == "evaluation_attempt_limit_reached":
            raise HTTPException(
                status_code=409,
                detail=(
                    "You have already used all "
                    f"{settings.handwritten_evaluation_attempts_per_paper} "
                    "completed attempts for this paper."
                ),
            ) from exc
        raise
    if not result.data:
        raise HTTPException(status_code=409, detail="Could not create submission")
    payload = result.data[0] if isinstance(result.data, list) else result.data
    submission = payload["submission"]
    job = payload.get("job") or {}
    return SubmissionResponse(
        id=submission["id"],
        paper_id=submission["evaluation_paper_id"],
        upload_intent_id=submission["upload_intent_id"],
        status=submission["status"],
        submitted_at=submission["created_at"],
        job_id=job.get("id"),
        job_status=job.get("status"),
        report_available=False,
    )


def _submission_response(client, row: dict[str, Any]) -> SubmissionResponse:
    job = (
        client.table("evaluation_jobs")
        .select("id,status")
        .eq("submission_id", row["id"])
        .limit(1)
        .execute()
    )
    evaluation = (
        client.table("handwritten_evaluations")
        .select(
            "id,total_marks_obtained,total_marks_possible,percentage,created_at"
        )
        .eq("submission_id", row["id"])
        .limit(1)
        .execute()
    )
    paper = _first(
        client,
        "evaluation_papers",
        "id,title,subject_id,course_level_id",
        id=row.get("evaluation_paper_id"),
        tenant_id=row["tenant_id"],
    ) if row.get("evaluation_paper_id") else None
    metadata = _paper_metadata(client, paper, row["tenant_id"]) if paper else {}
    evaluation_row = evaluation.data[0] if evaluation.data else None
    return SubmissionResponse(
        id=row["id"],
        paper_id=row.get("evaluation_paper_id"),
        upload_intent_id=row.get("upload_intent_id"),
        status=row["status"],
        submitted_at=row["created_at"],
        job_id=job.data[0]["id"] if job.data else None,
        job_status=job.data[0]["status"] if job.data else None,
        report_available=bool(evaluation.data),
        paper_title=(paper or {}).get("title") or row.get("paper_title_snapshot"),
        subject_name=metadata.get("subject_name") or row.get("subject_name_snapshot"),
        marks_obtained=(
            float(evaluation_row["total_marks_obtained"])
            if evaluation_row and evaluation_row.get("total_marks_obtained") is not None
            else None
        ),
        marks_possible=(
            float(evaluation_row["total_marks_possible"])
            if evaluation_row and evaluation_row.get("total_marks_possible") is not None
            else None
        ),
        percentage=(
            float(evaluation_row["percentage"])
            if evaluation_row and evaluation_row.get("percentage") is not None
            else None
        ),
        evaluation_date=(evaluation_row or {}).get("created_at"),
        error_message=row.get("error_message"),
        retrigger_count=int(row.get("retrigger_count") or 0),
        regraded_from=row.get("regraded_from"),
    )


def _student_identity(
    client, *, student_id: str, tenant_id: str
) -> tuple[str | None, str | None]:
    student_profile = _first(
        client,
        "profiles",
        "id,full_name",
        id=student_id,
        tenant_id=tenant_id,
    )
    student_email: str | None = None
    try:
        auth_response = client.auth.admin.get_user_by_id(student_id)
        auth_user = getattr(auth_response, "user", auth_response)
        student_email = getattr(auth_user, "email", None)
    except Exception:
        # A temporary Auth directory problem must not hide the submission list.
        pass
    return (student_profile or {}).get("full_name"), student_email


def _faculty_submission_response(client, row: dict[str, Any]) -> FacultySubmissionResponse:
    submission = _submission_response(client, row)
    student_name, student_email = _student_identity(
        client,
        student_id=str(row["student_id"]),
        tenant_id=str(row["tenant_id"]),
    )
    return FacultySubmissionResponse(
        **submission.model_dump(),
        student_id=row["student_id"],
        student_name=student_name,
        student_email=student_email,
    )


@router.get("/submissions", response_model=SubmissionResponseList)
async def list_submissions(
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionResponseList:
    await _require_student_feature(profile)
    client = get_service_client()
    result = (
        client.table("handwritten_submissions")
        .select(
            "id,tenant_id,evaluation_paper_id,upload_intent_id,status,"
            "error_message,retrigger_count,regraded_from,paper_title_snapshot,"
            "subject_name_snapshot,created_at"
        )
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return SubmissionResponseList(
        submissions=[_submission_response(client, row) for row in result.data or []]
    )


@router.get(
    "/papers/{paper_id}/submissions",
    response_model=FacultySubmissionResponseList,
)
async def list_paper_submissions(
    paper_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> FacultySubmissionResponseList:
    """List one paper's submissions for assigned faculty or tenant admins."""
    require_evaluation_enabled(get_service_client(), profile)
    if profile.role not in {"teacher", "institution_admin"}:
        raise HTTPException(status_code=403, detail="Faculty access required")
    client = get_service_client()
    if profile.role == "teacher":
        require_teacher_evaluation_paper_access(
            client,
            profile,
            paper_id=str(paper_id),
        )
    else:
        paper = _first(
            client,
            "evaluation_papers",
            "id",
            id=str(paper_id),
            tenant_id=profile.tenant_id,
        )
        if not paper:
            raise HTTPException(status_code=404, detail="Evaluation paper not found")

    result = (
        client.table("handwritten_submissions")
        .select(
            "id,tenant_id,student_id,evaluation_paper_id,upload_intent_id,status,"
            "error_message,retrigger_count,regraded_from,paper_title_snapshot,"
            "subject_name_snapshot,created_at"
        )
        .eq("tenant_id", profile.tenant_id)
        .eq("evaluation_paper_id", str(paper_id))
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return FacultySubmissionResponseList(
        submissions=[
            _faculty_submission_response(client, row) for row in result.data or []
        ]
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionResponse:
    require_evaluation_enabled(get_service_client(), profile)
    client = get_service_client()
    query = (
        client.table("handwritten_submissions")
        .select(
            "id,tenant_id,evaluation_paper_id,upload_intent_id,status,"
            "error_message,retrigger_count,regraded_from,paper_title_snapshot,"
            "subject_name_snapshot,created_at"
        )
        .eq("id", str(submission_id))
    )
    if profile.role == "student":
        query = query.eq("tenant_id", profile.tenant_id).eq("student_id", profile.user_id)
    elif profile.role in {"teacher", "institution_admin"}:
        query = query.eq("tenant_id", profile.tenant_id)
    else:
        raise HTTPException(status_code=403, detail="Submission access denied")
    result = query.limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    if profile.role == "teacher":
        if result.data[0].get("evaluation_paper_id") is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        require_teacher_evaluation_paper_access(
            client,
            profile,
            paper_id=str(result.data[0]["evaluation_paper_id"]),
        )
    return _submission_response(client, result.data[0])


@router.get(
    "/submissions/{submission_id}/answer-script-url",
    response_model=AnswerScriptUrlResponse,
)
async def get_answer_script_url(
    submission_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> AnswerScriptUrlResponse:
    """Issue a short-lived answer-sheet URL after faculty authorization."""
    require_evaluation_enabled(get_service_client(), profile)
    if profile.role not in {"teacher", "institution_admin"}:
        raise HTTPException(status_code=403, detail="Faculty access required")
    client = get_service_client()
    result = (
        client.table("handwritten_submissions")
        .select("id,tenant_id,evaluation_paper_id,answer_script_path")
        .eq("id", str(submission_id))
        .eq("tenant_id", profile.tenant_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission = result.data[0]
    if profile.role == "teacher":
        if submission.get("evaluation_paper_id") is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        require_teacher_evaluation_paper_access(
            client,
            profile,
            paper_id=str(submission["evaluation_paper_id"]),
        )
    if not submission.get("answer_script_path"):
        raise HTTPException(status_code=404, detail="Answer script not found")
    return AnswerScriptUrlResponse(
        url=signed_url(
            submission["answer_script_path"],
            300,
            bucket=EVALUATION_SUBMISSIONS_BUCKET,
        )
    )


@router.get(
    "/submissions/{submission_id}/report",
    response_model=EvaluationReportResponse,
)
async def get_evaluation_report(
    submission_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> EvaluationReportResponse:
    """Return the persisted student report; never rebuild or regrade on read."""
    require_evaluation_enabled(get_service_client(), profile)
    client = get_service_client()
    query = (
        client.table("handwritten_submissions")
        .select(
            "id,tenant_id,student_id,evaluation_paper_id,answer_script_path,"
            "status,paper_title_snapshot,subject_name_snapshot,created_at"
        )
        .eq("id", str(submission_id))
    )
    if profile.role == "student":
        query = query.eq("tenant_id", profile.tenant_id).eq(
            "student_id", profile.user_id
        )
    elif profile.role in {"teacher", "institution_admin"}:
        query = query.eq("tenant_id", profile.tenant_id)
    else:
        raise HTTPException(status_code=403, detail="Submission access denied")
    submission_result = query.limit(1).execute()
    if not submission_result.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission = submission_result.data[0]
    if profile.role == "teacher":
        if submission.get("evaluation_paper_id") is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        require_teacher_evaluation_paper_access(
            client,
            profile,
            paper_id=str(submission["evaluation_paper_id"]),
        )

    evaluation_result = (
        client.table("handwritten_evaluations")
        .select(
            "id,status,total_marks_obtained,total_marks_possible,percentage,"
            "overall_feedback,strengths,areas_to_improve,created_at"
        )
        .eq("submission_id", str(submission_id))
        .eq("tenant_id", submission["tenant_id"])
        .limit(1)
        .execute()
    )
    if not evaluation_result.data:
        raise HTTPException(
            status_code=202,
            detail="Evaluation report is not available yet.",
        )
    evaluation = evaluation_result.data[0]
    paper_result = None
    if submission.get("evaluation_paper_id"):
        paper_result = (
            client.table("evaluation_papers")
            .select("id,title,subject_id,total_marks")
            .eq("id", submission["evaluation_paper_id"])
            .eq("tenant_id", submission["tenant_id"])
            .limit(1)
            .execute()
        )
    paper = paper_result.data[0] if paper_result and paper_result.data else None
    subject_name: str | None = None
    if paper and paper.get("subject_id"):
        subject = (
            client.table("subjects")
            .select("name")
            .eq("id", paper["subject_id"])
            .eq("tenant_id", submission["tenant_id"])
            .limit(1)
            .execute()
        )
        if subject.data:
            subject_name = subject.data[0].get("name")

    student_profile = _first(
        client,
        "profiles",
        "id,full_name",
        id=submission["student_id"],
        tenant_id=submission["tenant_id"],
    )
    if not student_profile:
        raise HTTPException(status_code=404, detail="Student profile not found")
    student_email: str | None = None
    try:
        auth_response = client.auth.admin.get_user_by_id(str(submission["student_id"]))
        auth_user = getattr(auth_response, "user", auth_response)
        student_email = getattr(auth_user, "email", None)
    except Exception:
        # The report remains usable if the Auth directory is temporarily
        # unavailable, but it must never fall back to the requester's identity.
        pass

    question_result = (
        client.table("handwritten_question_evaluations")
        .select(
            "question_ref,question_text,marks_obtained,marks_possible,"
            "not_attempted,not_evaluated,not_counted,mapping_status,feedback,"
            "student_guidance,student_answer_excerpt,handwriting_legibility,"
            "grading_confidence,criteria_breakdown,created_at"
        )
        .eq("evaluation_id", evaluation["id"])
        .eq("tenant_id", submission["tenant_id"])
        .order("created_at")
        .execute()
    )
    answer_script_url = None
    if submission.get("answer_script_path"):
        answer_script_url = signed_url(
            submission["answer_script_path"],
            300,
            bucket=EVALUATION_SUBMISSIONS_BUCKET,
        )
    return EvaluationReportResponse(
        submission_id=submission["id"],
        status=evaluation["status"],
        submission_date=submission["created_at"],
        evaluation_date=evaluation["created_at"],
        paper=EvaluationReportPaper(
            id=(paper or {}).get("id"),
            title=(paper or {}).get("title") or submission["paper_title_snapshot"],
            subject=subject_name or submission["subject_name_snapshot"],
            total_marks=float(evaluation["total_marks_possible"]),
        ),
        student=EvaluationReportStudent(
            name=student_profile.get("full_name"),
            email=student_email,
        ),
        total_score=float(evaluation["total_marks_obtained"]),
        total_marks=float(evaluation["total_marks_possible"]),
        percentage=float(evaluation["percentage"]),
        overall_feedback=evaluation.get("overall_feedback") or "",
        strengths=[str(value) for value in evaluation.get("strengths") or []],
        areas_to_improve=[
            str(value) for value in evaluation.get("areas_to_improve") or []
        ],
        requires_review=submission["status"] == "review",
        answer_script_url=answer_script_url,
        questions=[EvaluationQuestionReport.model_validate(row) for row in question_result.data or []],
    )


def _student_submission(client, profile: CurrentProfile, submission_id: UUID) -> dict[str, Any]:
    result = (
        client.table("handwritten_submissions").select("*")
        .eq("id", str(submission_id)).eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id).limit(1).execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    return result.data[0]


@router.post(
    "/submissions/{submission_id}/additional-pages/upload-intents",
    response_model=UploadIntentResponse,
    status_code=201,
)
async def create_additional_pages_upload_intent(
    submission_id: UUID,
    body: UploadIntentRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> UploadIntentResponse:
    await _require_student_feature(profile)
    client = get_service_client()
    submission = _student_submission(client, profile, submission_id)
    if submission.get("evaluation_paper_id") != str(body.paper_id):
        raise HTTPException(status_code=409, detail="Submission and paper do not match")
    if submission["status"] in {"evaluated", "review"}:
        raise HTTPException(status_code=409, detail="A completed submission is immutable")
    try:
        extension = "." + ALLOWED_EVALUATION_TYPES[body.content_type.lower()]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Only PDF, PNG and JPEG files are supported.") from exc
    intent_id = uuid4()
    path = f"{profile.tenant_id}/{profile.user_id}/{intent_id}-additional{extension}"
    inserted = client.table("evaluation_upload_intents").insert({
        "id": str(intent_id), "tenant_id": profile.tenant_id,
        "student_id": profile.user_id, "evaluation_paper_id": str(body.paper_id),
        "submission_id": str(submission_id), "purpose": "additional_pages",
        "storage_path": path, "original_filename": safe_filename(body.filename),
        "content_type": body.content_type.lower(), "expected_size": body.size_bytes,
    }).execute()
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Could not create upload intent")
    try:
        signed = signed_upload(path, bucket=EVALUATION_SUBMISSIONS_BUCKET)
    except Exception as exc:
        client.table("evaluation_upload_intents").update({"status": "failed"}).eq(
            "id", str(intent_id)
        ).execute()
        raise HTTPException(status_code=503, detail="Could not create upload URL") from exc
    return UploadIntentResponse(
        id=intent_id, paper_id=body.paper_id, upload_url=signed["signed_url"],
        upload_token=signed["token"], storage_path=path,
        expires_at=inserted.data[0]["expires_at"],
    )


@router.post(
    "/submissions/{submission_id}/additional-pages",
    response_model=SubmissionResponse,
)
async def attach_additional_pages(
    submission_id: UUID,
    body: AdditionalPagesRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionResponse:
    await _require_student_feature(profile)
    if not get_settings().evaluation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Evaluation processing is currently disabled")
    client = get_service_client()
    result = client.rpc("attach_handwritten_additional_pages", {
        "p_tenant": profile.tenant_id, "p_student": profile.user_id,
        "p_submission": str(submission_id), "p_intent": str(body.upload_intent_id),
    }).execute().data
    if not result:
        raise HTTPException(status_code=409, detail="Could not attach additional pages")
    payload = result[0] if isinstance(result, list) else result
    return _submission_response(client, payload["submission"])


@router.post("/submissions/{submission_id}/retrigger", response_model=SubmissionResponse)
async def retrigger_submission(
    submission_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionResponse:
    await _require_student_feature(profile)
    settings = get_settings()
    if not settings.evaluation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Evaluation processing is currently disabled")
    client = get_service_client()
    try:
        result = client.rpc("retrigger_handwritten_submission", {
            "p_tenant": profile.tenant_id, "p_student": profile.user_id,
            "p_submission": str(submission_id),
            "p_limit": settings.handwritten_evaluation_attempts_per_paper,
        }).execute().data
    except Exception as exc:
        raise HTTPException(status_code=409, detail="This submission cannot be evaluated again") from exc
    payload = result[0] if isinstance(result, list) else result
    if not payload:
        raise HTTPException(status_code=409, detail="This submission cannot be evaluated again")
    return _submission_response(client, payload["submission"])


@router.get("/papers/{paper_id}/quota", response_model=SubmissionQuotaResponse)
async def get_submission_quota(
    paper_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> SubmissionQuotaResponse:
    await _require_student_feature(profile)
    await _load_paper(profile, paper_id)
    client = get_service_client()
    limit = get_settings().handwritten_evaluation_attempts_per_paper
    quota = _submission_quotas_by_paper(
        client,
        tenant_id=profile.tenant_id,
        student_id=profile.user_id,
        paper_ids=[str(paper_id)],
        attempt_limit=limit,
    )[str(paper_id)]
    return SubmissionQuotaResponse(
        paper_id=paper_id,
        completed_attempts=int(quota["completed_attempts"]),
        attempt_limit=limit,
        remaining_attempts=int(quota["remaining_attempts"]),
        active=bool(quota["quota_active"]),
    )


@router.post("/submissions/{submission_id}/mark-failed")
async def mark_submission_failed(
    submission_id: UUID,
    body: MarkFailedRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict[str, bool]:
    if profile.role != "institution_admin":
        raise HTTPException(status_code=403, detail="Institution-admin access required")
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    changed = client.rpc("mark_handwritten_submission_failed", {
        "p_tenant": profile.tenant_id, "p_submission": str(submission_id),
        "p_reason": body.reason.strip(),
    }).execute().data
    if not changed:
        raise HTTPException(status_code=404, detail="Active submission not found")
    return {"changed": True}


@router.get(
    "/evaluations/{evaluation_id}/stage2-artifacts",
    response_model=Stage2ArtifactListResponse,
)
async def get_stage2_artifacts(
    evaluation_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> Stage2ArtifactListResponse:
    if profile.role != "institution_admin":
        raise HTTPException(status_code=403, detail="Institution-admin access required")
    client = get_service_client()
    require_evaluation_enabled(client, profile)
    evaluation = client.table("handwritten_evaluations").select("id").eq(
        "id", str(evaluation_id)
    ).eq("tenant_id", profile.tenant_id).limit(1).execute().data
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    rows = client.table("handwritten_stage2_artifacts").select("*").eq(
        "evaluation_id", str(evaluation_id)
    ).eq("tenant_id", profile.tenant_id).order("sequence").execute().data or []
    return Stage2ArtifactListResponse(
        artifacts=[Stage2ArtifactResponse.model_validate(row) for row in rows]
    )
