"""Student upload and submission endpoints for handwritten evaluation."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.evaluation_access import require_evaluation_enabled, student_can_access_paper
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
    question_paper_url: str
    subject_name: str | None = None
    course_name: str | None = None
    level_name: str | None = None
    paper_type: str = "mock_test"
    created_at: str | None = None


class EvaluationPaperSummaryList(BaseModel):
    papers: list[EvaluationPaperSummary]


class UploadIntentRequest(BaseModel):
    paper_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=MAX_EVALUATION_FILE_BYTES)


class UploadIntentResponse(BaseModel):
    id: UUID
    paper_id: UUID
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
    paper_id: UUID
    upload_intent_id: UUID
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


class SubmissionResponseList(BaseModel):
    submissions: list[SubmissionResponse]


class EvaluationReportPaper(BaseModel):
    id: UUID
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
            "question_paper_storage_path,created_at"
        )
        .eq("tenant_id", profile.tenant_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    client = get_service_client()
    accessible: list[EvaluationPaperSummary] = []
    for paper in result.data or []:
        if student_can_access_paper(client, profile, paper):
            paper["question_paper_url"] = signed_url(
                paper["question_paper_storage_path"],
                300,
                bucket=EVALUATION_PAPERS_BUCKET,
            )
            paper.update(_paper_metadata(client, paper, profile.tenant_id))
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
    if not get_settings().evaluation_jobs_enabled:
        raise HTTPException(status_code=503, detail="Evaluation processing is currently disabled")
    result = get_service_client().rpc(
        "create_handwritten_submission_job",
        {
            "p_tenant": profile.tenant_id,
            "p_student": profile.user_id,
            "p_intent": str(body.upload_intent_id),
        },
    ).execute()
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
        id=row["evaluation_paper_id"],
        tenant_id=row["tenant_id"],
    )
    metadata = _paper_metadata(client, paper, row["tenant_id"]) if paper else {}
    evaluation_row = evaluation.data[0] if evaluation.data else None
    return SubmissionResponse(
        id=row["id"],
        paper_id=row["evaluation_paper_id"],
        upload_intent_id=row["upload_intent_id"],
        status=row["status"],
        submitted_at=row["created_at"],
        job_id=job.data[0]["id"] if job.data else None,
        job_status=job.data[0]["status"] if job.data else None,
        report_available=bool(evaluation.data),
        paper_title=(paper or {}).get("title"),
        subject_name=metadata.get("subject_name"),
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
            "error_message,created_at"
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
            "error_message,created_at"
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
    return _submission_response(client, result.data[0])


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
            "status,created_at"
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
    paper_result = (
        client.table("evaluation_papers")
        .select("id,title,subject_id,total_marks")
        .eq("id", submission["evaluation_paper_id"])
        .eq("tenant_id", submission["tenant_id"])
        .limit(1)
        .execute()
    )
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="Evaluation paper not found")
    paper = paper_result.data[0]
    subject_name: str | None = None
    if paper.get("subject_id"):
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
            id=paper["id"],
            title=paper["title"],
            subject=subject_name,
            total_marks=float(paper["total_marks"]),
        ),
        student=EvaluationReportStudent(name=profile.full_name, email=profile.email),
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
