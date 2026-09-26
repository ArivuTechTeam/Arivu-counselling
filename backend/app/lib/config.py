"""
Central configuration for the backend.

Every environment variable the app needs is read HERE, in one place, at
startup. If a required secret is missing we fail immediately with a clear
message — much easier to debug than a mysterious error deep inside a
request handler later.

Values come from `backend/.env` in local dev (loaded by python-dotenv) or
from real environment variables in production (Railway). We never hardcode
secrets in code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# Load key=value pairs from backend/.env into the process environment.
# In production there is no .env file — the platform injects real env
# vars — and load_dotenv() simply does nothing, which is exactly what we want.
load_dotenv()


def _positive_int(name: str, default: int) -> int:
    """Read a positive integer setting and fail fast on invalid values."""
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


def _positive_float(name: str, default: float) -> float:
    """Read a positive floating-point setting and fail fast if invalid."""
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    """Read a boolean setting without treating arbitrary text as truthy."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


def _provider_name(name: str, default: str) -> str:
    """Read a supported AI provider name and reject silent misrouting."""
    value = os.getenv(name, default).strip().lower()
    if value not in {"deepseek", "gemini"}:
        raise RuntimeError(f"{name} must be deepseek or gemini.")
    return value


def _validated_url(name: str, *, allow_local_http: bool = False) -> str:
    """Require an absolute HTTPS URL (or explicit local HTTP URL)."""
    value = _require(name).rstrip("/")
    parsed = urlparse(value)
    local_host = parsed.hostname in {"localhost", "127.0.0.1"}
    valid_scheme = parsed.scheme == "https" or (
        allow_local_http and local_host and parsed.scheme == "http"
    )
    if not valid_scheme or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(
            f"{name} must be an absolute HTTPS origin without credentials. "
            "HTTP is allowed only for localhost development."
        )
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must be an origin only, without a path or query.")
    return value


def _optional_secret(name: str) -> str | None:
    """Read an optional secret, rejecting template placeholders."""
    value = os.getenv(name)
    if not value:
        return None
    normalized = value.strip()
    if normalized.lower().startswith(("replace_with_", "your-", "your_")):
        raise RuntimeError(f"{name} must be replaced with a real credential.")
    return normalized


class Settings:
    """Typed, validated view of our environment variables."""

    def __init__(self) -> None:
        # Enable only after the additive faculty-job migration and worker are ready.
        self.faculty_jobs_enabled = _boolean("FACULTY_JOBS_ENABLED", False)
        self.quiz_reuse_enabled = _boolean("QUIZ_REUSE_ENABLED", False)
        # Batch-scoped delivery (Phase 6.1). This is an emergency platform
        # switch; production enables it for every commerce institution.
        self.batches_enabled = _boolean("BATCHES_ENABLED", False)
        # Per-question scoring policies (Phase 6.2). This can be disabled
        # platform-wide during an incident without changing stored policies.
        self.scoring_policies_enabled = _boolean("SCORING_POLICIES_ENABLED", False)
        # Commerce Vertical Pack (Phase 6.3). Production enables this for the
        # commerce-only product; the switch remains as an operational kill path.
        self.commerce_pack_enabled = _boolean("COMMERCE_PACK_ENABLED", False)
        self.faculty_jobs_poll_seconds = _positive_int("FACULTY_JOBS_POLL_SECONDS", 3)
        # A queued job should be claimed within seconds. If work waits longer than
        # this with no live worker lease, the worker is treated as stalled/absent
        # (surfaced by the deployment preflight and super-admin worker-health).
        self.faculty_worker_stale_seconds = _positive_int("FACULTY_WORKER_STALE_SECONDS", 120)
        # Document-figure support (Phase 1: extract captioned figures during
        # analysis). Production enables it after the private bucket is ready;
        # the switch remains a platform-wide emergency control.
        self.figure_attach_enabled = _boolean("FIGURE_ATTACH_ENABLED", False)
        self.figure_max_per_document = _positive_int("FIGURE_MAX_PER_DOCUMENT", 50)
        # Paper knowledge base - PYQ / MTP / RTP (KB). Off by default: extraction,
        # storage, review, publish, and the student dashboard are byte-identical.
        # When on (and the teacher opts in per upload), extraction classifies the
        # paper, published questions are snapshotted into the paper_questions bank,
        # and students get the "Mock Test & PYQ" surface. Requires migrations 63-65.
        # PYQ_ENABLED is accepted as a legacy alias during the transition.
        self.paper_bank_enabled = _boolean("PAPER_BANK_ENABLED", False) or _boolean(
            "PYQ_ENABLED", False
        )
        # Extended objective question types (Phase 6.4): assertion_reason, mrm,
        # matching. Off by default: teachers cannot request them and generation is
        # byte-identical. Validation/grading always understand them so any stored
        # data is safe; they are only ever produced when this is on. Descriptive
        # (manual grading) is intentionally NOT part of this - it belongs to the
        # future Mock Test Paper feature.
        self.extended_question_types_enabled = _boolean(
            "EXTENDED_QUESTION_TYPES_ENABLED", False
        )
        # Regenerate an entire draft quiz in one action (reuses per-question
        # regeneration, same shape). Off by default. Bounded set size + worker
        # concurrency keep the synchronous request within time limits.
        self.regenerate_set_enabled = _boolean("REGENERATE_SET_ENABLED", False)
        self.regenerate_set_max_questions = _positive_int("REGENERATE_SET_MAX_QUESTIONS", 40)
        self.regenerate_set_concurrency = _positive_int("REGENERATE_SET_CONCURRENCY", 5)
        # Extraction blueprint. Off by default: publishing is unchanged and the
        # blueprint panel is hidden. When on, after extraction the teacher can
        # select a subset (positional range + per-type PYQ/MTP/RTP caps) to
        # publish; the unselected questions are LEFT UNTOUCHED in the database
        # (never rejected, never deleted) so they can be published later.
        self.extraction_blueprint_enabled = _boolean("EXTRACTION_BLUEPRINT_ENABLED", False)
        # Purge rejected questions at publish. Off by default: rejecting a
        # question only soft-flags it (review_status='rejected'), exactly as
        # today. When on, questions the teacher marked rejected are permanently
        # deleted when the quiz is published (after a confirm), so they never
        # linger in the bank and never reach Smart Quiz. A rejected question that
        # was ever answered by a student is never deleted (history is protected).
        self.rejected_purge_enabled = _boolean("REJECTED_PURGE_ENABLED", False)
        self.app_env: str = os.getenv("APP_ENV", "production").strip().lower()
        if self.app_env not in {"production", "development", "test"}:
            raise RuntimeError("APP_ENV must be production, development, or test.")
        allow_local_http = self.app_env != "production"

        # Debug behavior is always opt-in. Production deployments should leave
        # this false; local developers may set APP_DEBUG=true to expose API docs.
        self.debug: bool = _boolean("APP_DEBUG", False)

        # --- Supabase connection ---
        self.supabase_url: str = _validated_url(
            "SUPABASE_URL", allow_local_http=allow_local_http
        )
        # anon key: safe-ish, RLS-limited. The backend uses it when it wants
        # to act "as the logged-in user" (respecting their tenant + role).
        self.supabase_anon_key: str = _require("SUPABASE_ANON_KEY")
        # service_role key: bypasses RLS. Backend-only. Never sent to a browser.
        self.supabase_service_role_key: str = _require("SUPABASE_SERVICE_ROLE_KEY")
        # The secret Supabase signs its JWTs with. We use it to verify tokens
        # locally (HS256) instead of calling Supabase on every request.
        self.supabase_jwt_secret: str = _require("SUPABASE_JWT_SECRET")
        # Keep each Data API read attempt well below the browser's ordinary
        # 20-second request deadline. The transport can then retry a stalled
        # idempotent read instead of the browser timing out before recovery.
        self.supabase_read_timeout_seconds: float = _positive_float(
            "SUPABASE_READ_TIMEOUT_SECONDS", 5
        )

        # --- Local dev / CORS ---
        # Which frontend origin is allowed to call this API from the browser.
        self.frontend_origin: str = _validated_url(
            "FRONTEND_ORIGIN", allow_local_http=allow_local_http
        )
        frontend_host = urlparse(self.frontend_origin).hostname
        self.is_local_development: bool = frontend_host in {
            "localhost",
            "127.0.0.1",
        }
        if self.debug and (
            self.app_env == "production" or not self.is_local_development
        ):
            raise RuntimeError(
                "APP_DEBUG may only be enabled for localhost development or tests."
            )

        # --- AI / LLM (Slice 3) ---
        # At least one provider credential is mandatory because quiz generation
        # is a core feature. Provider model/URL settings retain safe defaults.
        self.deepseek_api_key: str | None = _optional_secret("DEEPSEEK_API_KEY")
        self.deepseek_base_url: str = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        self.deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        # Extraction and generation are structured transformation tasks. Keep
        # thinking disabled by default so hidden reasoning does not add latency
        # or output-token cost; it remains an explicit environment override.
        self.deepseek_thinking_enabled: bool = _boolean(
            "DEEPSEEK_THINKING_ENABLED", False
        )
        # Display-only cost conversion for super-admin AI API observability.
        self.usd_to_inr_rate: float = _positive_float("USD_TO_INR_RATE", 83.0)
        # DeepSeek defaults non-thinking responses to 8K output tokens, but its
        # current API accepts a much larger explicit limit. The REDUCE response
        # contains retained source material, so reserve Gemini-equivalent room.
        self.deepseek_max_output_tokens: int = max(
            65536,
            _positive_int("DEEPSEEK_MAX_OUTPUT_TOKENS", 65536),
        )
        self.deepseek_structured_max_output_tokens: int = _positive_int(
            "DEEPSEEK_STRUCTURED_MAX_OUTPUT_TOKENS", 16384
        )
        self.deepseek_request_timeout_seconds: float = _positive_float(
            "DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 240.0
        )

        # Gemini (Google) remains the vision provider and default text fallback.
        self.gemini_api_key: str | None = _optional_secret("GEMINI_API_KEY")
        self.gemini_base_url: str = os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        # A stale/retired model can remain visible in models.list while its
        # generateContent route returns 404. Retry that one condition with this
        # current model before moving to the cross-provider fallback.
        self.gemini_fallback_model: str = os.getenv(
            "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash"
        )

        if not self.deepseek_api_key and not self.gemini_api_key:
            raise RuntimeError(
                "At least one AI provider key is required: set GEMINI_API_KEY "
                "or DEEPSEEK_API_KEY."
            )

        # Stage-aware routing keeps cheap text work on DeepSeek while retaining
        # Gemini for scanned/image vision and as a controlled fallback. A missing
        # primary credential is handled by the router, which safely uses the
        # configured fallback instead of failing at startup.
        self.ai_fallback_provider: str = _provider_name(
            "AI_FALLBACK_PROVIDER", "gemini"
        )
        self.topic_analysis_provider: str = _provider_name(
            "TOPIC_ANALYSIS_PROVIDER", "deepseek"
        )
        self.quiz_generation_provider: str = _provider_name(
            "QUIZ_GENERATION_PROVIDER", "deepseek"
        )
        self.typed_quiz_extraction_provider: str = _provider_name(
            "TYPED_QUIZ_EXTRACTION_PROVIDER", "deepseek"
        )
        self.question_verification_provider: str = _provider_name(
            "QUESTION_VERIFICATION_PROVIDER", "deepseek"
        )
        self.question_regeneration_provider: str = _provider_name(
            "QUESTION_REGENERATION_PROVIDER", "deepseek"
        )
        self.vision_extraction_provider: str = _provider_name(
            "VISION_EXTRACTION_PROVIDER", "gemini"
        )
        if self.vision_extraction_provider != "gemini":
            raise RuntimeError(
                "VISION_EXTRACTION_PROVIDER must remain gemini until the "
                "DeepSeek multimodal adapter is enabled."
            )

        # Retained for direct Gemini schema-constrained calls and compatibility.
        # Stage-aware text workflows use their configured provider/model instead.
        self.gemini_blueprint_model: str = os.getenv(
            "GEMINI_BLUEPRINT_MODEL", "gemini-3.5-flash-lite"
        )

        # Quiz EXTRACTION via Gemini vision (scanned PDFs / images only — typed
        # docs go the cheap text path). These are the two levers behind the
        # "read operation timed out" failures, both tunable from Railway with no
        # code change:
        #   * timeout — how long we wait for the vision response. Keep it BELOW
        #     the frontend's own extraction timeout so the server fails first.
        #   * max output tokens — headroom so a long paper isn't truncated. We
        #     also disable "thinking" for extraction (pure parsing needs none),
        #     which cuts latency and frees the whole budget for questions.
        self.gemini_vision_timeout_seconds: float = _positive_float(
            "GEMINI_VISION_TIMEOUT_SECONDS", 240
        )
        self.gemini_extraction_max_output_tokens: int = _positive_int(
            "GEMINI_EXTRACTION_MAX_OUTPUT_TOKENS", 65536
        )

        # Large typed documents (120-150+ pages) are split into text chunks so
        # each model call has a small, bounded output — the real cause of the
        # "timed out" failures. Chunks run with limited concurrency and the
        # questions are merged + de-duplicated. Both tunable from Railway.
        #   * chunk size — chars per chunk (smaller = faster/safer per call)
        #   * concurrency — how many chunks are extracted at once
        self.extraction_text_chunk_chars: int = _positive_int(
            "EXTRACTION_TEXT_CHUNK_CHARS", 18000
        )
        self.extraction_chunk_concurrency: int = _positive_int(
            "EXTRACTION_CHUNK_CONCURRENCY", 4
        )

        # How much document text the SINGLE-CALL generation path feeds the model.
        # Set to match the chunking trigger below so documents up to ~40 pages are
        # fully covered by one call and only larger ones take the chunked path
        # (no silent truncation in the 24–40 page band). ~100,000 chars ≈ 40 pages;
        # ~25k tokens — comfortably within Gemini (1M) and the DeepSeek (160k)
        # fallback. Tunable without a code change.
        self.generation_max_text_chars: int = _positive_int(
            "GENERATION_MAX_TEXT_CHARS", 100000
        )

        # --- Large-document ("chunked") quiz generation ---
        # Only documents whose extracted text exceeds the trigger take the
        # chunked, resumable background path; smaller ones use the single-call
        # flow unchanged. All tunable from Railway with no code change.
        #   trigger  ~100,000 chars ≈ 40 pages
        #   chunk    target/overlap/min size for the structure-aware splitter
        #   concurrency — how many chunks generate in parallel
        self.chunking_trigger_chars: int = _positive_int(
            "CHUNKING_TRIGGER_CHARS", 100000
        )
        self.generation_chunk_chars: int = _positive_int(
            "GENERATION_CHUNK_CHARS", 60000
        )
        self.generation_chunk_overlap_chars: int = _positive_int(
            "GENERATION_CHUNK_OVERLAP_CHARS", 5000
        )
        self.generation_chunk_min_chars: int = _positive_int(
            "GENERATION_CHUNK_MIN_CHARS", 8000
        )
        self.generation_chunk_concurrency: int = _positive_int(
            "GENERATION_CHUNK_CONCURRENCY", 4
        )
        # Output-token headroom for the MAP (per-chunk extraction) and REDUCE
        # (blueprint synthesis) calls. Their JSON is large and verbatim, so the
        # cap must be high or the response truncates mid-JSON. Gemini 2.5 Flash
        # supports up to 65536; "thinking" is disabled on these calls so the
        # whole budget goes to output. Tunable from Railway.
        self.generation_map_max_output_tokens: int = _positive_int(
            "GENERATION_MAP_MAX_OUTPUT_TOKENS", 65536
        )
        # A 300-page REDUCE request can legitimately carry 200k+ characters and
        # return tens of thousands of JSON tokens. It runs in a background job,
        # so give the provider enough time instead of applying the shorter
        # interactive-call timeout.
        self.generation_large_request_timeout_seconds: float = _positive_float(
            "GENERATION_LARGE_REQUEST_TIMEOUT_SECONDS", 600
        )
        # How much text the "understand the document first" profiling call reads.
        # Big enough to cover most documents whole; bounded for cost/latency and to
        # stay within the fallback model's context. Tunable from Railway.
        self.generation_profile_max_chars: int = _positive_int(
            "GENERATION_PROFILE_MAX_CHARS", 200000
        )
        # A chunk left "running" longer than this is considered stuck and is
        # re-queued by the sweeper / on retry (resumability).
        self.generation_chunk_stuck_seconds: int = _positive_int(
            "GENERATION_CHUNK_STUCK_SECONDS", 900
        )

        # --- Per-user AI request limits (rolling one-hour windows) ---
        # Read once at process startup so changing a Railway variable and
        # restarting the service applies the new limit without a code change.
        self.rate_limit_quiz_generation_per_hour = _positive_int(
            "RATE_LIMIT_QUIZ_GENERATION_PER_HOUR", 10
        )
        self.rate_limit_blueprint_per_hour = _positive_int(
            "RATE_LIMIT_BLUEPRINT_PER_HOUR", 10
        )
        self.rate_limit_topic_extraction_per_hour = _positive_int(
            "RATE_LIMIT_TOPIC_EXTRACTION_PER_HOUR", 30
        )
        self.rate_limit_question_regenerate_per_hour = _positive_int(
            "RATE_LIMIT_QUESTION_REGENERATE_PER_HOUR", 10
        )
        self.rate_limit_question_explain_per_hour = _positive_int(
            "RATE_LIMIT_QUESTION_EXPLAIN_PER_HOUR", 10
        )
        self.rate_limit_quiz_extraction_per_hour = _positive_int(
            "RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR", 10
        )
        self.rate_limit_challenge_join_per_hour = _positive_int(
            "RATE_LIMIT_CHALLENGE_JOIN_PER_HOUR", 30
        )
        self.rate_limit_paper_grading_per_hour = _positive_int(
            "RATE_LIMIT_PAPER_GRADING_PER_HOUR", 10
        )

        # Maximum starts per student for the same published quiz variant.
        # Started and abandoned attempts both count toward this limit.
        self.student_quiz_attempt_limit = _positive_int(
            "STUDENT_QUIZ_ATTEMPT_LIMIT", 2
        )

        # New friend challenges accept participants for this many days. Existing
        # in-progress sessions can still be resumed after the sharing window.
        self.challenge_expiry_days = _positive_int("CHALLENGE_EXPIRY_DAYS", 30)

        # Calendar boundary used for one-per-day challenges and streaks.
        self.daily_challenge_timezone = os.getenv(
            "DAILY_CHALLENGE_TIMEZONE", "Asia/Kolkata"
        )
        try:
            ZoneInfo(self.daily_challenge_timezone)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                "DAILY_CHALLENGE_TIMEZONE must be a valid IANA timezone."
            ) from exc


def _require(name: str) -> str:
    """Read a required env var, or raise a clear error if it's missing."""
    value = os.getenv(name)
    if not value or value.strip().lower().startswith(
        ("replace_with_", "your-", "your_")
    ):
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


@lru_cache
def get_settings() -> Settings:
    """
    Return a single, cached Settings instance.

    @lru_cache means Settings() is built once on first call and reused after
    that — we don't re-read the environment on every request.
    """
    return Settings()
