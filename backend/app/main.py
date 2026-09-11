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

import logging
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    academics,
    auth_account,
    challenge,
    documents,
    extraction,
    practice,
    questions,
    quiz,
    student,
    super_admin,
    teacher,
    topics,
    institution_admin,
)
from app.lib.auth import (
    CurrentProfile,
    CurrentUser,
    get_current_profile,
    get_current_user,
)
from app.lib.config import get_settings
from app.lib.request_trace import request_id_for_header
from app.lib.supabase import SupabaseUnavailableError

logger = logging.getLogger(__name__)

settings = get_settings()
app = FastAPI(
    title="quiz-generator-v1 API",
    version="0.1.0",
    docs_url="/docs" if settings.is_local_development else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.is_local_development else None,
)

# --- CORS ---------------------------------------------------------------
# Browsers block a page on http://localhost:3000 from calling an API on a
# different origin (http://localhost:8000) unless the API explicitly says
# "I allow that origin". This middleware adds those permission headers.
# In production we'll list the real Vercel domain instead of localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    # Dev convenience: the Next dev server hops to :3001, :3002 … when a port is
    # already taken. Allow any localhost / 127.0.0.1 port so the browser isn't
    # blocked by CORS. In production, FRONTEND_ORIGIN pins the real domain.
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1):\d+"
        if settings.is_local_development
        else None
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.middleware("http")
async def trace_and_protect_api_responses(request: Request, call_next):
    """Correlate browser errors with logs and prevent API response caching."""
    request_id = request_id_for_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled request failure request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        raise

    response.headers["X-Request-ID"] = request_id
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    logger.info(
        "Request completed request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation_error(
    _request: Request, exception: RequestValidationError
) -> JSONResponse:
    """Return useful field errors without echoing submitted passwords or text."""
    errors = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid value."),
            "type": error.get("type", "value_error"),
        }
        for error in exception.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Please check the submitted fields and try again.",
            "errors": errors,
        },
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


@app.exception_handler(SupabaseUnavailableError)
async def temporary_supabase_failure(
    request: Request, _exception: SupabaseUnavailableError
) -> JSONResponse:
    """Expose exhausted Data API retries as a temporary, retryable failure."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The data service is temporarily unavailable. Please try again.",
            "request_id": getattr(request.state, "request_id", None),
        },
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "Retry-After": "2",
            "X-Request-ID": getattr(request.state, "request_id", uuid4().hex),
        },
    )


@app.exception_handler(Exception)
async def safe_unhandled_error(request: Request, _exception: Exception) -> JSONResponse:
    """Return a traceable message without leaking internals to the browser."""
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred. Please try again.",
            "request_id": request_id,
        },
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Request-ID": request_id,
        },
    )

# --- Routers ------------------------------------------------------------
app.include_router(academics.router)
app.include_router(auth_account.router)
app.include_router(institution_admin.router)
app.include_router(super_admin.router)
app.include_router(challenge.router)
app.include_router(documents.router)
app.include_router(extraction.router)
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
