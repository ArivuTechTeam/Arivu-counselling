from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.lib.config import Settings, _positive_int
from app.services.rate_limit import enforce_ai_rate_limit


def profile() -> CurrentProfile:
    return CurrentProfile(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        role="teacher",
    )


class _RPCRequest:
    def __init__(self, data) -> None:
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _RPCService:
    def __init__(self, data) -> None:
        self.data = data
        self.call = None

    def rpc(self, function_name: str, params: dict) -> _RPCRequest:
        self.call = (function_name, params)
        return _RPCRequest(self.data)


class RateLimitServiceTests(unittest.TestCase):
    def test_allowed_request_uses_verified_profile_scope(self) -> None:
        service = _RPCService(
            [{"allowed": True, "retry_after_seconds": 0, "remaining": 9}]
        )
        with patch(
            "app.services.rate_limit.get_service_client", return_value=service
        ):
            enforce_ai_rate_limit(
                profile=profile(),
                endpoint="quiz_generation",
                hourly_limit=10,
                action_label="quiz generation",
            )

        self.assertEqual(service.call[0], "consume_ai_rate_limit")
        self.assertEqual(service.call[1]["p_user_id"], profile().user_id)
        self.assertEqual(service.call[1]["p_tenant_id"], profile().tenant_id)
        self.assertEqual(service.call[1]["p_limit"], 10)

    def test_blocked_request_returns_friendly_429_and_retry_header(self) -> None:
        service = _RPCService(
            [{"allowed": False, "retry_after_seconds": 61, "remaining": 0}]
        )
        with patch(
            "app.services.rate_limit.get_service_client", return_value=service
        ):
            with self.assertRaises(HTTPException) as caught:
                enforce_ai_rate_limit(
                    profile=profile(),
                    endpoint="question_explain",
                    hourly_limit=10,
                    action_label="question explanations",
                )

        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers, {"Retry-After": "61"})
        self.assertEqual(
            caught.exception.detail,
            "You've reached the hourly limit for question explanations. "
            "Please try again in 2 minutes.",
        )

    def test_database_failure_fails_closed_without_leaking_raw_error(self) -> None:
        service = _RPCService([])
        with patch(
            "app.services.rate_limit.get_service_client", return_value=service
        ):
            with self.assertRaises(HTTPException) as caught:
                enforce_ai_rate_limit(
                    profile=profile(),
                    endpoint="topic_extraction",
                    hourly_limit=10,
                    action_label="topic extraction",
                )

        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("Supabase", caught.exception.detail)

    def test_malformed_response_is_not_written_to_logs(self) -> None:
        sentinel = "server-only-secret-must-not-be-logged"
        service = _RPCService({"credential": sentinel})
        with patch(
            "app.services.rate_limit.get_service_client", return_value=service
        ), self.assertLogs("app.services.rate_limit", level="ERROR") as captured:
            with self.assertRaises(HTTPException):
                enforce_ai_rate_limit(
                    profile=profile(),
                    endpoint="topic_extraction",
                    hourly_limit=10,
                    action_label="topic extraction",
                )

        self.assertNotIn(sentinel, "\n".join(captured.output))


class RateLimitConfigurationTests(unittest.TestCase):
    def test_default_and_environment_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_positive_int("EXAMPLE_RATE_LIMIT", 10), 10)
        with patch.dict(os.environ, {"EXAMPLE_RATE_LIMIT": "27"}, clear=True):
            self.assertEqual(_positive_int("EXAMPLE_RATE_LIMIT", 10), 27)

    def test_invalid_limit_fails_at_startup(self) -> None:
        for value in ("0", "-1", "ten"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ, {"EXAMPLE_RATE_LIMIT": value}, clear=True
                ):
                    with self.assertRaisesRegex(RuntimeError, "positive integer"):
                        _positive_int("EXAMPLE_RATE_LIMIT", 10)

    def test_all_six_settings_are_independently_configurable(self) -> None:
        environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": uuid4().hex,
            "SUPABASE_SERVICE_ROLE_KEY": uuid4().hex,
            "SUPABASE_JWT_SECRET": uuid4().hex,
            "FRONTEND_ORIGIN": "https://app.example.com",
            "GEMINI_API_KEY": uuid4().hex,
            "RATE_LIMIT_QUIZ_GENERATION_PER_HOUR": "11",
            "RATE_LIMIT_BLUEPRINT_PER_HOUR": "12",
            "RATE_LIMIT_TOPIC_EXTRACTION_PER_HOUR": "13",
            "RATE_LIMIT_QUESTION_REGENERATE_PER_HOUR": "14",
            "RATE_LIMIT_QUESTION_EXPLAIN_PER_HOUR": "15",
            "RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR": "16",
            "STUDENT_QUIZ_ATTEMPT_LIMIT": "7",
            "CHALLENGE_EXPIRY_DAYS": "45",
            "DEEPSEEK_MAX_OUTPUT_TOKENS": "8192",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings()

        self.assertEqual(settings.rate_limit_quiz_generation_per_hour, 11)
        self.assertEqual(settings.rate_limit_blueprint_per_hour, 12)
        self.assertEqual(settings.rate_limit_topic_extraction_per_hour, 13)
        self.assertEqual(settings.rate_limit_question_regenerate_per_hour, 14)
        self.assertEqual(settings.rate_limit_question_explain_per_hour, 15)
        self.assertEqual(settings.rate_limit_quiz_extraction_per_hour, 16)
        self.assertEqual(settings.student_quiz_attempt_limit, 7)
        self.assertEqual(settings.challenge_expiry_days, 45)
        self.assertEqual(settings.deepseek_max_output_tokens, 65536)
        self.assertEqual(settings.generation_large_request_timeout_seconds, 600)
        self.assertEqual(settings.generation_chunk_stuck_seconds, 900)
        self.assertEqual(settings.gemini_fallback_model, "gemini-3.5-flash")


class RateLimitMigrationTests(unittest.TestCase):
    def test_migration_is_atomic_tenant_scoped_and_service_role_only(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (root / "migrations/migration-13-ai-rate-limits.sql").read_text().lower()

        self.assertIn("primary key (tenant_id, user_id, endpoint)", sql)
        self.assertIn("foreign key (user_id, tenant_id)", sql)
        self.assertIn("on conflict (tenant_id, user_id, endpoint) do update", sql)
        self.assertIn("or limits.request_count < p_limit", sql)
        self.assertIn("alter table public.ai_rate_limits enable row level security", sql)
        self.assertIn("security invoker", sql)
        self.assertIn("set search_path = ''", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)


if __name__ == "__main__":
    unittest.main()
