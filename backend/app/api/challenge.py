"""
Challenge a Friend — a student freezes a random quiz and shares it (same
institution only). Everyone who takes it does so as a practice_session tagged
with challenge_id, so the leaderboard is simply those graded sessions.

Isolation: a challenge is only visible/takeable inside the creator's tenant.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.selector import select_question_ids

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
    # Same-institution only: outside the tenant it simply doesn't exist.
    if ch is None or not ch.data or ch.data["tenant_id"] != profile.tenant_id:
        raise HTTPException(status_code=404, detail="Challenge not found.")
    return ch.data


class CreateChallenge(BaseModel):
    subject_id: str | None = None
    count: int = 10


@router.post("/challenges")
def create_challenge(
    body: CreateChallenge, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Freeze a random quiz + start the creator's own attempt of it."""
    _require_student(profile)
    service = get_service_client()
    ids = select_question_ids(
        service, profile, mode="challenge", subject_id=body.subject_id, count=body.count
    )
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="Not enough questions to build a challenge yet.",
        )
    token = secrets.token_urlsafe(9)
    ch = (
        service.table("challenges")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "creator_id": profile.user_id,
                "creator_name": _display_name(
                    service, profile.user_id, profile.tenant_id
                ),
                "question_ids": ids,
                "share_token": token,
            }
        )
        .execute()
        .data[0]
    )
    sess = (
        service.table("practice_sessions")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "mode": "challenge",
                "subject_id": body.subject_id,
                "config": {"count": len(ids)},
                "question_ids": ids,
                "status": "in_progress",
                "challenge_id": ch["id"],
            }
        )
        .execute()
        .data[0]
    )
    return {"token": token, "session_id": sess["id"]}


@router.get("/challenges/{token}")
def get_challenge(
    token: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Challenge hub: my status + the leaderboard (all graded takers)."""
    _require_student(profile)
    service = get_service_client()
    ch = _load_challenge(service, token, profile)

    sessions = (
        service.table("practice_sessions")
        .select("id, student_id, status, total_score, max_score")
        .eq("challenge_id", ch["id"])
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    sids = list({s["student_id"] for s in sessions})
    names: dict = {}
    if sids:
        for p in (
            service.table("profiles")
            .select("id, full_name")
            .in_("id", sids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        ):
            names[p["id"]] = p.get("full_name") or "Student"

    my_status = "not_taken"
    my_session_id = None
    my_pct = None
    leaderboard = []
    for s in sessions:
        graded = s["status"] == "graded"
        pct = (
            round((s["total_score"] or 0) / s["max_score"] * 100)
            if graded and s.get("max_score")
            else None
        )
        if s["student_id"] == profile.user_id:
            if graded:
                my_status, my_pct = "done", pct
            else:
                my_status, my_session_id = "in_progress", s["id"]
        if graded:
            leaderboard.append(
                {
                    "name": names.get(s["student_id"], "Student"),
                    "pct": pct or 0,
                    "is_creator": s["student_id"] == ch["creator_id"],
                    "is_you": s["student_id"] == profile.user_id,
                }
            )
    leaderboard.sort(key=lambda x: -x["pct"])

    return {
        "token": token,
        "creator_name": ch["creator_name"],
        "questions": len(ch["question_ids"]),
        "is_creator": ch["creator_id"] == profile.user_id,
        "my_status": my_status,
        "my_session_id": my_session_id,
        "my_pct": my_pct,
        "leaderboard": leaderboard,
    }


@router.post("/challenges/{token}/accept")
def accept_challenge(
    token: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """A friend takes the challenge — same frozen questions, their own session."""
    _require_student(profile)
    service = get_service_client()
    ch = _load_challenge(service, token, profile)

    existing = (
        service.table("practice_sessions")
        .select("id, status")
        .eq("challenge_id", ch["id"])
        .eq("student_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    for e in existing:
        if e["status"] == "in_progress":
            return {"session_id": e["id"]}  # resume
    if existing:
        raise HTTPException(status_code=400, detail="You've already taken this challenge.")

    sess = (
        service.table("practice_sessions")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "mode": "challenge",
                "config": {"count": len(ch["question_ids"])},
                "question_ids": ch["question_ids"],
                "status": "in_progress",
                "challenge_id": ch["id"],
            }
        )
        .execute()
        .data[0]
    )
    return {"session_id": sess["id"]}
