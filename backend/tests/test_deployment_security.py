from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.lib.config import Settings
from app.main import app, settings


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": uuid4().hex,
        "SUPABASE_SERVICE_ROLE_KEY": uuid4().hex,
        "SUPABASE_JWT_SECRET": uuid4().hex,
        "FRONTEND_ORIGIN": "https://app.example.com",
        "GEMINI_API_KEY": uuid4().hex,
    }


class StartupConfigurationTests(unittest.TestCase):
    def test_critical_variables_fail_fast_when_missing(self) -> None:
        for name in (
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_JWT_SECRET",
            "FRONTEND_ORIGIN",
        ):
            environment = valid_environment()
            environment.pop(name)
            with self.subTest(name=name), patch.dict(
                os.environ, environment, clear=True
            ), self.assertRaisesRegex(RuntimeError, name):
                Settings()

    def test_at_least_one_ai_provider_key_is_required(self) -> None:
        environment = valid_environment()
        environment.pop("GEMINI_API_KEY")
        with patch.dict(
            os.environ, environment, clear=True
        ), self.assertRaisesRegex(RuntimeError, "AI provider key"):
            Settings()

    def test_template_placeholders_are_rejected(self) -> None:
        environment = {
            **valid_environment(),
            "SUPABASE_SERVICE_ROLE_KEY": "replace_with_your_service_key",
        }
        with patch.dict(
            os.environ, environment, clear=True
        ), self.assertRaisesRegex(RuntimeError, "SUPABASE_SERVICE_ROLE_KEY"):
            Settings()

    def test_debug_defaults_off_and_cannot_be_enabled_for_production_origin(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertFalse(Settings().debug)

        environment = {**valid_environment(), "APP_DEBUG": "true"}
        with patch.dict(
            os.environ, environment, clear=True
        ), self.assertRaisesRegex(RuntimeError, "APP_DEBUG"):
            Settings()

    def test_production_origins_require_https(self) -> None:
        environment = {**valid_environment(), "FRONTEND_ORIGIN": "http://app.example.com"}
        with patch.dict(
            os.environ, environment, clear=True
        ), self.assertRaisesRegex(RuntimeError, "HTTPS"):
            Settings()

    def test_local_http_requires_an_explicit_non_production_environment(self) -> None:
        environment = {
            **valid_environment(),
            "SUPABASE_URL": "http://localhost:54321",
            "FRONTEND_ORIGIN": "http://localhost:3000",
        }
        with patch.dict(
            os.environ, environment, clear=True
        ), self.assertRaisesRegex(RuntimeError, "HTTPS"):
            Settings()

        environment["APP_ENV"] = "development"
        with patch.dict(os.environ, environment, clear=True):
            self.assertFalse(Settings().debug)


class ResponseSecurityTests(unittest.TestCase):
    client = TestClient(app, raise_server_exceptions=False)

    def test_debug_routes_are_disabled_by_default(self) -> None:
        self.assertFalse(settings.debug)
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.openapi_url)

    def test_security_headers_are_added_to_success_and_error_responses(self) -> None:
        responses = (
            self.client.get("/health"),
            self.client.get("/route-that-does-not-exist"),
            self.client.options(
                "/health",
                headers={
                    "Origin": settings.frontend_origin,
                    "Access-Control-Request-Method": "GET",
                },
            ),
        )
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertIn("max-age=31536000", response.headers["Strict-Transport-Security"])
                self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_http_and_validation_errors_include_a_correlation_id(self) -> None:
        not_found = self.client.get("/route-that-does-not-exist")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(
            not_found.json()["request_id"], not_found.headers["X-Request-ID"]
        )

        invalid = self.client.get("/api/v1/public/courses")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["request_id"], invalid.headers["X-Request-ID"])
        self.assertNotIn("input", invalid.json())

        malformed_tenant = self.client.get(
            "/api/v1/public/courses?tenant_id=not-a-uuid"
        )
        self.assertEqual(malformed_tenant.status_code, 422)

    def test_cors_allows_only_the_configured_or_local_development_origin(self) -> None:
        allowed_origin = settings.frontend_origin
        allowed = self.client.options(
            "/health",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), allowed_origin)

        denied = self.client.options(
            "/health",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotEqual(
            denied.headers.get("Access-Control-Allow-Origin"), "https://attacker.example"
        )


if __name__ == "__main__":
    unittest.main()
