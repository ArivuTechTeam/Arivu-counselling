"""
Central configuration for the backend.

Every environment variable the app needs is read HERE, in one place, at
startup. If a required secret is missing we fail immediately with a clear
message — much easier to debug than a mysterious error deep inside a
request handler later.

Values come from `backend/.env` in local dev (loaded by python-dotenv) or
from real environment variables in production (Vercel). We never hardcode
secrets in code.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Load key=value pairs from backend/.env into the process environment.
# In production there is no .env file — the platform injects real env
# vars — and load_dotenv() simply does nothing, which is exactly what we want.
load_dotenv()


class Settings:
    """Typed, validated view of our environment variables."""

    def __init__(self) -> None:
        # --- Supabase connection ---
        self.supabase_url: str = _require("SUPABASE_URL")
        # anon key: safe-ish, RLS-limited. The backend uses it when it wants
        # to act "as the logged-in user" (respecting their tenant + role).
        self.supabase_anon_key: str = _require("SUPABASE_ANON_KEY")
        # service_role key: bypasses RLS. Backend-only. Never sent to a browser.
        self.supabase_service_role_key: str = _require("SUPABASE_SERVICE_ROLE_KEY")
        # The secret Supabase signs its JWTs with. We use it to verify tokens
        # locally (HS256) instead of calling Supabase on every request.
        self.supabase_jwt_secret: str = _require("SUPABASE_JWT_SECRET")

        # --- Local dev / CORS ---
        # Which frontend origin is allowed to call this API from the browser.
        self.frontend_origin: str = os.getenv(
            "FRONTEND_ORIGIN", "http://localhost:3000"
        )

        # --- AI / LLM (Slice 3) ---
        # Optional: the app boots without these, but quiz generation fails with
        # a clear error until DEEPSEEK_API_KEY is set. Model + URL have sane
        # defaults so you normally only need to supply the key.
        self.deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url: str = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        self.deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # Gemini (Google). If a key is set, it becomes the PRIMARY model and
        # DeepSeek (if configured) is the fallback.
        self.gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
        self.gemini_base_url: str = os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # The blueprint quiz feature (topic extraction + blueprint generation)
        # runs on the cheapest tier by default — Flash-Lite. Swappable to a
        # stronger Flash model via env if quality needs a bump, no code change.
        # NOTE: gemini-2.5-flash-lite is restricted for new API projects, so we
        # default to the current cheapest tier, gemini-3.5-flash-lite.
        self.gemini_blueprint_model: str = os.getenv(
            "GEMINI_BLUEPRINT_MODEL", "gemini-3.5-flash-lite"
        )

        # How much document text to feed the model per generation. Larger =
        # broader coverage (esp. with big-context models like Gemini) but more
        # tokens/cost. Tunable without a code change.
        self.generation_max_text_chars: int = int(
            os.getenv("GENERATION_MAX_TEXT_CHARS", "60000")
        )


def _require(name: str) -> str:
    """Read a required env var, or raise a clear error if it's missing."""
    value = os.getenv(name)
    if not value:
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
