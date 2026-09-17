"""Challenge a Friend: one immutable, timed quiz shared with classmates."""

from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field, model_validator

from app.api.practice import _in_progress_payload, _load_questions, _load_session
from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.attempt_timing import effective_time_limit_minutes
from app.services.selector import (
    SELECTABLE_QUESTION_TYPES,
    select_question_ids,
    select_question_ids_by_type,
)

router = APIRouter(prefix="/api/v1", tags=["challenge"])


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can challenge friends.",
        )


def _display_name(service, user_id: str, tenant_id: str) -> str:
    row = (
        service.table("profiles")
        .select("full_name")
        .eq("id", user_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    name = (row.data or {}).get("full_name") if row and row.data else None
    return name or "A student"


def _load_challenge(service, token: str, profile: CurrentProfile) -> dict:
    ch = (
        service.table("challenges")
        .select("*")
        .eq("share_token", token)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if ch is None or not ch.data or ch.data["tenant_id"] != profile.tenant_id:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    return ch.data


def _is_expired(challenge: dict, now: datetime | None = None) -> bool:
    raw = challenge.get("expires_at")
    if not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= expires_at


def _student_course_ids(service, profile: CurrentProfile) -> set[str]:
    rows = (
        service.table("enrollments")
        .select("course_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("profile_id", profile.user_id)
        .execute()
        .data
        or []
    )
    return {str(row["course_id"]) for row in rows if row.get("course_id")}


def _require_course_access(service, challenge: dict, profile: CurrentProfile) -> None:
    required = {str(value) for value in (challenge.get("course_ids") or [])}
    # Legacy challenges predate course metadata and retain tenant-only access.
    if required and not required.issubset(_student_course_ids(service, profile)):
        raise HTTPException(
            status_code=403,
            detail="This challenge is for students enrolled in the same course.",
        )


def _snapshot_and_courses(
    service, ids: list[str], tenant_id: str
) -> tuple[list[dict], list[str]]:
    questions = _load_questions(service, ids, tenant_id)
    if len(questions) != len(ids):
        raise HTTPException(
            status_code=400,
            detail="Some selected questions are no longer available. Please try again.",
        )
    chapter_ids = list({q.get("chapter_id") for q in questions if q.get("chapter_id")})
    if not chapter_ids or any(not q.get("chapter_id") for q in questions):
        raise HTTPException(
            status_code=400,
            detail="Every selected question must be linked to a chapter.",
        )
    chapters = (
        service.table("chapters")
        .select("id, subject_id")
        .in_("id", chapter_ids)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    if len(chapters) != len(chapter_ids):
        raise HTTPException(
            status_code=400,
            detail="Some selected question chapters are no longer available.",
        )
    subject_ids = list({row["subject_id"] for row in chapters if row.get("subject_id")})
    subjects = (
        service.table("subjects")
        .select("id, course_id")
        .in_("id", subject_ids)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    if len(subjects) != len(subject_ids):
        raise HTTPException(
            status_code=400,
            detail="Some selected question subjects are no longer available.",
        )
    course_ids = sorted(
        {str(row["course_id"]) for row in subjects if row.get("course_id")}
    )
    if not course_ids:
        raise HTTPException(
            status_code=400,
            detail="The selected questions are not linked to an available course.",
        )
    return questions, course_ids


def _challenge_questions(service, challenge: dict, tenant_id: str) -> list[dict]:
    snapshot = challenge.get("question_snapshot")
    if isinstance(snapshot, list) and snapshot:
        return snapshot
    return _load_questions(service, challenge.get("question_ids") or [], tenant_id)


def _subject_name(service, challenge: dict, tenant_id: str) -> str | None:
    subject_id = challenge.get("subject_id")
    if not subject_id:
        return None
    row = (
        service.table("subjects")
        .select("name")
        .eq("id", subject_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    return (row.data or {}).get("name") if row and row.data else None


class CreateChallenge(BaseModel):
    subject_id: str | None = None
    # Kept for compatibility with an older browser bundle during rollout.
    count: int | None = Field(default=10, ge=1, le=100)
    type_counts: dict[str, int] | None = None

    @model_validator(mode="after")
    def validate_mix(self) -> "CreateChallenge":
        if self.type_counts is None:
            return self
        unknown = set(self.type_counts) - set(SELECTABLE_QUESTION_TYPES)
        if unknown:
            raise ValueError(f"Unsupported question types: {', '.join(sorted(unknown))}")
        if any(
            isinstance(value, bool) or value < 0 or value > 100
            for value in self.type_counts.values()
        ):
            raise ValueError("Each question-type count must be between 0 and 100.")
        total = sum(self.type_counts.values())
        if total < 1 or total > 100:
            raise ValueError("A challenge must contain between 1 and 100 questions.")
        return self


def _type_counts(questions: list[dict]) -> dict[str, int]:
    counts = Counter(str(question.get("type") or "") for question in questions)
    return {
        question_type: counts.get(question_type, 0)
        for question_type in SELECTABLE_QUESTION_TYPES
        if counts.get(question_type, 0)
    }


@router.get("/challenges/mine")
def my_challenges(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """List challenges created by this student, including recoverable sessions."""
    _require_student(profile)
    service = get_service_client()
    challenges = (
        service.table("challenges")
        .select(
            "id, share_token, subject_id, question_ids, duration_minutes, "
            "created_at, expires_at, is_active"
        )
        .eq("tenant_id", profile.tenant_id)
        .eq("creator_id", profile.user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
        or []
    )
    if not challenges:
        return []
    challenge_ids = [row["id"] for row in challenges]
    sessions = (
        service.table("practice_sessions")
        .select(
            "id, challenge_id, student_id, status, total_score, max_score, "
            "started_at, submitted_at"
        )
        .in_("challenge_id", challenge_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    subject_ids = list(
        {row.get("subject_id") for row in challenges if row.get("subject_id")}
    )
    subjects = (
        service.table("subjects")
        .select("id, name")
        .in_("id", subject_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
        if subject_ids
        else []
    )
    names = {row["id"]: row.get("name") for row in subjects}
    result = []
    for challenge in challenges:
        related = [s for s in sessions if s.get("challenge_id") == challenge["id"]]
        mine = next(
            (s for s in related if s.get("student_id") == profile.user_id), None
        )
        result.append(
            {
                "token": challenge["share_token"],
                "subject_name": names.get(challenge.get("subject_id")),
                "questions": len(challenge.get("question_ids") or []),
                "duration_minutes": challenge.get("duration_minutes"),
                "created_at": challenge.get("created_at"),
                "expires_at": challenge.get("expires_at"),
                "is_active": bool(challenge.get("is_active", True)),
                "is_expired": _is_expired(challenge),
                "players": sum(1 for s in related if s.get("status") == "graded"),
                "my_status": (
                    "done"
                    if mine and mine.get("status") == "graded"
                    else "in_progress"
                    if mine
                    else "not_taken"
                ),
                "my_session_id": mine.get("id") if mine else None,
            }
        )
    return result


@router.post("/challenges")
def create_challenge(
    body: CreateChallenge, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Freeze a game and return its share link without consuming an attempt."""
    _require_student(profile)
    service = get_service_client()
    requested_counts = body.type_counts
    if requested_counts is not None:
        requested_counts = {
            question_type: requested_counts.get(question_type, 0)
            for question_type in SELECTABLE_QUESTION_TYPES
        }
        ids, availability = select_question_ids_by_type(
            service,
            profile,
            subject_id=body.subject_id,
            type_counts=requested_counts,
        )
        shortages = [
            f"{question_type.replace('_', ' ')}: "
            f"{availability.get(question_type, 0)} available"
            for question_type, requested in requested_counts.items()
            if requested > availability.get(question_type, 0)
        ]
        expected_count = sum(requested_counts.values())
        if shortages:
            raise HTTPException(
                status_code=400,
                detail="Not enough approved questions for this mix ("
                + "; ".join(shortages)
                + "). Reduce those counts or choose another subject.",
            )
    else:
        expected_count = body.count or 10
        ids = select_question_ids(
            service,
            profile,
            mode="challenge",
            subject_id=body.subject_id,
            count=expected_count,
        )
    if len(ids) != expected_count:
        raise HTTPException(
            status_code=400,
            detail=f"This challenge needs {expected_count} approved questions, but only "
            f"{len(ids)} are available. Choose fewer questions or another subject.",
        )
    questions, course_ids = _snapshot_and_courses(service, ids, profile.tenant_id)
    duration_minutes = int(effective_time_limit_minutes(questions))
    now = datetime.now(timezone.utc)
    created = None
    for attempt in range(2):
        try:
            result = (
                service.table("challenges")
                .insert(
                    {
                        "tenant_id": profile.tenant_id,
                        "creator_id": profile.user_id,
                        "creator_name": _display_name(
                            service, profile.user_id, profile.tenant_id
                        ),
                        "subject_id": body.subject_id,
                        "course_ids": course_ids,
                        "question_ids": ids,
                        "question_snapshot": questions,
                        "duration_minutes": duration_minutes,
                        "share_token": secrets.token_urlsafe(18),
                        "expires_at": (
                            now
                            + timedelta(days=get_settings().challenge_expiry_days)
                        ).isoformat(),
                        "is_active": True,
                    }
                )
                .execute()
            )
            created = (result.data or [None])[0]
            if created:
                break
        except APIError as exc:
            if exc.code != "23505" or attempt == 1:
                raise
    if not created:
        raise HTTPException(status_code=500, detail="Could not create the challenge.")
    return {
        "token": created["share_token"],
        "questions": len(ids),
        "duration_minutes": duration_minutes,
        "type_counts": _type_counts(questions),
    }


def _challenge_sessions(service, challenge_id: str, tenant_id: str) -> list[dict]:
    return (
        service.table("practice_sessions")
        .select(
            "id, student_id, status, total_score, max_score, started_at, submitted_at"
        )
        .eq("challenge_id", challenge_id)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )


def _participant_session(
    service, challenge_id: str, profile: CurrentProfile
) -> dict | None:
    row = (
        service.table("practice_sessions")
        .select("id, student_id, status")
        .eq("challenge_id", challenge_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .maybe_single()
        .execute()
    )
    return row.data if row and row.data else None


@router.get("/challenges/{token}")
def get_challenge(
    token: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Challenge hub: eligibility, caller status, and stable leaderboard."""
    _require_student(profile)
    service = get_service_client()
    ch = _load_challenge(service, token, profile)
    sessions = _challenge_sessions(service, ch["id"], profile.tenant_id)
    mine = next((s for s in sessions if s["student_id"] == profile.user_id), None)
    if ch["creator_id"] != profile.user_id and mine is None:
        _require_course_access(service, ch, profile)

    student_ids = list({s["student_id"] for s in sessions})
    names: dict[str, str] = {}
    if student_ids:
        rows = (
            service.table("profiles")
            .select("id, full_name")
            .in_("id", student_ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        )
        names = {row["id"]: row.get("full_name") or "Student" for row in rows}

    leaderboard = []
    for session in sessions:
        if session["status"] != "graded":
            continue
        max_score = float(session.get("max_score") or 0)
        pct = (
            round(float(session.get("total_score") or 0) / max_score * 100)
            if max_score
            else 0
        )
        try:
            started = datetime.fromisoformat(
                str(session.get("started_at")).replace("Z", "+00:00")
            )
            submitted = datetime.fromisoformat(
                str(session.get("submitted_at")).replace("Z", "+00:00")
            )
            elapsed_seconds = max(0, round((submitted - started).total_seconds()))
        except (TypeError, ValueError):
            elapsed_seconds = None
        leaderboard.append(
            {
                "student_id": session["student_id"],
                "name": names.get(session["student_id"], "Student"),
                "pct": pct,
                "elapsed_seconds": elapsed_seconds,
                "submitted_at": session.get("submitted_at") or "",
                "is_creator": session["student_id"] == ch["creator_id"],
                "is_you": session["student_id"] == profile.user_id,
            }
        )
    leaderboard.sort(
        key=lambda row: (
            -row["pct"],
            row["elapsed_seconds"]
            if row["elapsed_seconds"] is not None
            else float("inf"),
            row["submitted_at"],
            row["student_id"],
        )
    )
    for index, row in enumerate(leaderboard, start=1):
        row["rank"] = index
        row.pop("student_id", None)
        row.pop("submitted_at", None)

    my_status = (
        "done"
        if mine and mine["status"] == "graded"
        else "in_progress"
        if mine
        else "not_taken"
    )
    my_pct = next((row["pct"] for row in leaderboard if row["is_you"]), None)
    return {
        "token": token,
        "creator_name": ch["creator_name"],
        "subject_name": _subject_name(service, ch, profile.tenant_id),
        "questions": len(ch.get("question_ids") or []),
        "type_counts": _type_counts(
            _challenge_questions(service, ch, profile.tenant_id)
        ),
        "duration_minutes": ch.get("duration_minutes"),
        "expires_at": ch.get("expires_at"),
        "is_active": bool(ch.get("is_active", True)),
        "accepting_closed": not bool(ch.get("is_active", True)) or _is_expired(ch),
        "is_creator": ch["creator_id"] == profile.user_id,
        "my_status": my_status,
        "my_session_id": mine.get("id") if mine else None,
        "my_pct": my_pct,
        "leaderboard": leaderboard,
    }


@router.post("/challenges/{token}/accept")
def accept_challenge(
    token: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Start or resume the caller's single attempt on the frozen challenge."""
    _require_student(profile)
    service = get_service_client()
    ch = _load_challenge(service, token, profile)
    mine = _participant_session(service, ch["id"], profile)
    if mine and mine["status"] == "in_progress":
        return _in_progress_payload(
            service, _load_session(service, mine["id"], profile), profile
        )
    if mine:
        raise HTTPException(status_code=400, detail="You've already taken this challenge.")
    is_creator = ch["creator_id"] == profile.user_id
    if not is_creator and not ch.get("is_active", True):
        raise HTTPException(status_code=410, detail="This challenge was closed by its creator.")
    if not is_creator and _is_expired(ch):
        raise HTTPException(status_code=410, detail="This challenge has expired.")
    _require_course_access(service, ch, profile)
    questions = _challenge_questions(service, ch, profile.tenant_id)
    if len(questions) != len(ch.get("question_ids") or []):
        raise HTTPException(status_code=409, detail="This challenge is no longer available.")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        session = (
            service.table("practice_sessions")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "student_id": profile.user_id,
                    "mode": "challenge",
                    "subject_id": ch.get("subject_id"),
                    "config": {
                        "count": len(questions),
                        "duration_minutes": ch.get("duration_minutes")
                        or int(effective_time_limit_minutes(questions)),
                    },
                    "question_ids": ch["question_ids"],
                    "question_snapshot": questions,
                    "status": "in_progress",
                    "challenge_id": ch["id"],
                    "started_at": started_at,
                }
            )
            .execute()
            .data[0]
        )
    except APIError as exc:
        if exc.code != "23505":
            raise
        mine = _participant_session(service, ch["id"], profile)
        if mine and mine["status"] == "in_progress":
            return _in_progress_payload(
                service, _load_session(service, mine["id"], profile), profile
            )
        raise HTTPException(
            status_code=400, detail="You've already taken this challenge."
        ) from exc
    return _in_progress_payload(service, session, profile, questions)


@router.delete("/challenges/{token}")
def close_challenge(
    token: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Stop new participants without deleting completed scores."""
    _require_student(profile)
    service = get_service_client()
    ch = _load_challenge(service, token, profile)
    if ch["creator_id"] != profile.user_id:
        raise HTTPException(status_code=403, detail="Only the creator can close this challenge.")
    updated = (
        service.table("challenges")
        .update({"is_active": False})
        .eq("id", ch["id"])
        .eq("tenant_id", profile.tenant_id)
        .eq("creator_id", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    return {"closed": token}
