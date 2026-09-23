"""
FastAPI application entry point for quiz-generator-v1.

Run locally (from the backend/ folder, with the venv active) via:
    uvicorn app.main:app

Slice 1 endpoints:
    GET  /health   -> unauthenticated health check (is the server alive?)
    GET  /api/v1/me         -> requires a valid JWT; returns token identity
    GET  /api/v1/me/profile -> requires a valid JWT; returns tenant + role
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    academics,
    admin,
    assignments,
    auth_account,
    branding,
    batches,
    challenge,
    documents,
    exam_standards,
    extraction,
    faculty_jobs,
    figures,
    paper_profiles,
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
from app.lib.api_errors import PublicAPIError
from app.lib.config import get_settings
from app.lib.request_trace import request_id_for_header
from app.lib.storage import signed_url
from app.lib.supabase import SupabaseUnavailableError

logger = logging.getLogger(__name__)


def _assert_admin_route_inventory_complete() -> None:
    """Fail startup if an admin handler is omitted from the public routers."""
    handler_paths = {route.path for route in admin.router.routes}
    mounted_paths = institution_admin._PATHS | super_admin._PATHS
    if handler_paths != mounted_paths:
        unmounted = sorted(handler_paths - mounted_paths)
        unknown = sorted(mounted_paths - handler_paths)
        raise RuntimeError(
            "Admin route inventory mismatch: "
            f"unmounted handlers={unmounted}; unknown inventory paths={unknown}."
        )


_assert_admin_route_inventory_complete()


def _safe_route_label(request: Request) -> str:
    """Return a route template, never a URL containing IDs or share tokens."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "[unmatched]"

settings = get_settings()
app = FastAPI(
    title="quiz-generator-v1 API",
    version="0.1.0",
    debug=settings.debug,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# --- CORS ---------------------------------------------------------------
# Browsers block a page on http://localhost:3000 from calling an API on a
# different origin (http://localhost:8000) unless the API explicitly says
# "I allow that origin". This middleware adds those permission headers.
# The allowed browser origin is the deployed Vercel frontend (or localhost in
# explicit development); the API itself runs on Railway.
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
    expose_headers=["X-Request-ID", "Retry-After", "Server-Timing"],
)

# Dashboard and quiz payloads are JSON-heavy. Compress responses over 1 KiB;
# tiny health/auth responses stay untouched to avoid unnecessary CPU work.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def trace_and_protect_api_responses(request: Request, call_next):
    """Correlate browser errors with logs and prevent API response caching."""
    request_id = request_id_for_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # Tracebacks and exception strings from SDKs may contain upstream
        # response bodies, URLs, or credentials. Keep only safe correlation
        # fields and the exception class in production logs.
        logger.error(
            "Unhandled request failure request_id=%s method=%s route=%s error_type=%s",
            request_id,
            request.method,
            _safe_route_label(request),
            type(exc).__name__,
        )
        raise

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
    logger.info(
        "Request completed request_id=%s method=%s route=%s status=%d duration_ms=%.1f",
        request_id,
        request.method,
        _safe_route_label(request),
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation_error(
    request: Request, exception: RequestValidationError
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
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Please check the submitted fields and try again.",
            "errors": errors,
            "request_id": request_id,
        },
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Request-ID": request_id,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def safe_http_error(
    request: Request, exception: StarletteHTTPException
) -> JSONResponse:
    """Return safe HTTP errors in one consistent, traceable envelope."""
    request_id = getattr(request.state, "request_id", uuid4().hex)
    if exception.status_code >= 500 and not isinstance(exception, PublicAPIError):
        detail = "The request could not be completed. Please try again."
    elif isinstance(exception.detail, str):
        detail = exception.detail
    else:
        detail = "The request could not be completed."
    headers = {
        **(exception.headers or {}),
        "Cache-Control": "no-store, private",
        "Pragma": "no-cache",
        "X-Request-ID": request_id,
    }
    return JSONResponse(
        status_code=exception.status_code,
        content={"detail": detail, "request_id": request_id},
        headers=headers,
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


from postgrest.exceptions import APIError as PostgrestAPIError
from app.services.quiz_reuse import MESSAGES as QUIZ_REUSE_MESSAGES


@app.exception_handler(PostgrestAPIError)
async def database_conflict(request: Request, exception: PostgrestAPIError) -> JSONResponse:
    message = QUIZ_REUSE_MESSAGES.get(exception.message)
    if message:
        return JSONResponse(status_code=409, content={"detail": message}, headers={"Cache-Control": "no-store"})
    if exception.code in {"40P01", "40001"}:
        return JSONResponse(status_code=409, content={"detail": "The quiz changed during this action. Refresh and retry."}, headers={"Cache-Control": "no-store"})
    return await safe_unhandled_error(request, exception)


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
app.include_router(assignments.router)
app.include_router(auth_account.router)
app.include_router(branding.router)
app.include_router(batches.router)
app.include_router(exam_standards.router)
app.include_router(paper_profiles.router)
app.include_router(institution_admin.router)
app.include_router(super_admin.router)
app.include_router(challenge.router)
app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(faculty_jobs.router)
app.include_router(figures.router)
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
class AuthenticatedIdentityOut(BaseModel):
    authenticated: bool


class InstitutionIdentityOut(BaseModel):
    name: str
    subdomain: str
    logo_url: str | None
    primary_color: str


class CurrentProfileOut(BaseModel):
    role: str
    must_change_password: bool
    institution: InstitutionIdentityOut | None = None


@app.get("/api/v1/me", tags=["auth"], response_model=AuthenticatedIdentityOut)
def read_me(_user: CurrentUser = Depends(get_current_user)) -> AuthenticatedIdentityOut:
    """
    Return the identity from the caller's verified JWT.

    The Depends(get_current_user) line is the gate: FastAPI runs the token
    verification first, and this function only executes if it passed.
    """
    return AuthenticatedIdentityOut(authenticated=True)


@app.get("/api/v1/me/profile", tags=["auth"], response_model=CurrentProfileOut)
def read_my_profile(
    profile: CurrentProfile = Depends(get_current_profile),
) -> CurrentProfileOut:
    """
    Return only the profile fields a browser may need. Internal user and tenant
    identifiers and the email claim stay inside the authorization layer.
    """
    institution: InstitutionIdentityOut | None = None
    if profile.role != "super_admin":
        if not profile.tenant_name or not profile.tenant_subdomain:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Institution identity is temporarily unavailable.",
            )
        logo_url: str | None = None
        if profile.tenant_logo_path:
            try:
                logo_url = signed_url(profile.tenant_logo_path, expires_in=3600)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Dashboard logo URL could not be created tenant=%s error_type=%s",
                    profile.tenant_id,
                    type(exc).__name__,
                )
        institution = InstitutionIdentityOut(
            name=profile.tenant_name,
            subdomain=profile.tenant_subdomain,
            logo_url=logo_url,
            primary_color=profile.tenant_primary_color or "#2E8857",
        )

    return CurrentProfileOut(
        role=profile.role,
        must_change_password=profile.must_change_password,
        institution=institution,
    )
