"""
FastAPI application entry point for quiz-generator-v1.

Run locally (from the backend/ folder, with the venv active) via:
    uvicorn app.main:app --reload

Slice 1 endpoints:
    GET  /health   -> unauthenticated health check (is the server alive?)
    GET  /api/v1/me         -> requires a valid JWT; returns token identity
    GET  /api/v1/me/profile -> requires a valid JWT; returns tenant + role
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    academics,
    admin,
    challenge,
    documents,
    practice,
    questions,
    quiz,
    student,
    teacher,
    topics,
)
from app.lib.auth import (
    CurrentProfile,
    CurrentUser,
    get_current_profile,
    get_current_user,
)
from app.lib.config import get_settings

app = FastAPI(
    title="quiz-generator-v1 API",
    version="0.1.0",
)

# --- CORS ---------------------------------------------------------------
# Browsers block a page on http://localhost:3000 from calling an API on a
# different origin (http://localhost:8000) unless the API explicitly says
# "I allow that origin". This middleware adds those permission headers.
# In production we'll list the real Vercel domain instead of localhost.
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    # Dev convenience: the Next dev server hops to :3001, :3002 … when a port is
    # already taken. Allow any localhost / 127.0.0.1 port so the browser isn't
    # blocked by CORS. In production, FRONTEND_ORIGIN pins the real domain.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ------------------------------------------------------------
app.include_router(academics.router)
app.include_router(admin.router)
app.include_router(challenge.router)
app.include_router(documents.router)
app.include_router(practice.router)
app.include_router(quiz.router)
app.include_router(questions.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(topics.router)


# --- Health check -------------------------------------------------------
@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """
    Liveness probe. No auth required. Deployment platforms (and you) hit this
    to confirm the server is up before trusting anything else.
    """
    return {"status": "ok"}


# --- Authenticated identity --------------------------------------------
@app.get("/api/v1/me", tags=["auth"])
def read_me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    Return the identity from the caller's verified JWT.

    The Depends(get_current_user) line is the gate: FastAPI runs the token
    verification first, and this function only executes if it passed.
    """
    return user


@app.get("/api/v1/me/profile", tags=["auth"])
def read_my_profile(
    profile: CurrentProfile = Depends(get_current_profile),
) -> CurrentProfile:
    """
    Return the caller's authoritative tenant_id + role from the profiles
    table. This is the data later slices will use for permission checks.
    """
    return profile
