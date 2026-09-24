from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import api_logs
from app.lib.auth import CurrentProfile, get_current_profile
from app.services import ai_call_logging as logs


class PricingTests(unittest.TestCase):
    def test_gemini_cost_replaces_cached_input_and_does_not_double_charge_thinking(self) -> None:
        usd, inr = logs.calculate_costs(
            model="gemini-3.5-flash",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cached_tokens=200_000,
            thinking_tokens=300_000,
            usd_to_inr_rate=83,
        )
        # 800k normal input * $1.50 + 200k cached * $0.15 + 1m output * $9.
        self.assertEqual(str(usd), "10.23000000")
        self.assertEqual(str(inr), "849.09000000")

    def test_unknown_model_does_not_invent_a_cost(self) -> None:
        self.assertEqual(
            logs.calculate_costs(
                model="future-provider-model", input_tokens=1, output_tokens=1,
                cached_tokens=None, thinking_tokens=None, usd_to_inr_rate=83,
            ),
            (None, None),
        )


class LoggingPayloadTests(unittest.TestCase):
    def test_test_environment_does_not_write_provider_logs(self) -> None:
        with patch.object(
            logs, "get_settings", return_value=SimpleNamespace(app_env="test")
        ), patch.object(logs.threading, "Thread") as thread:
            logs.log_ai_call(
                provider="gemini", model="gemini-3.5-flash", request={}, response={},
                was_fallback=False, started_at=0,
            )
        thread.assert_not_called()

    def test_gemini_usage_mapping_and_best_effort_row(self) -> None:
        written: list[dict] = []
        with patch.object(logs, "get_settings", return_value=SimpleNamespace(app_env="production", usd_to_inr_rate=83)), patch.object(logs, "_write", side_effect=written.append), patch.object(
            logs.threading, "Thread", side_effect=lambda target, args, daemon: type(
                "Immediate", (), {"start": lambda self: target(*args)}
            )()
        ):
            with logs.ai_call_context("topic_extraction_map", tenant_id="t1", document_id="d1"):
                logs.log_ai_call(
                    provider="gemini", model="gemini-3.5-flash", request={"contents": []},
                    response={"usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5,
                                                  "cachedContentTokenCount": 2, "thoughtsTokenCount": 3}},
                    was_fallback=False, started_at=0,
                )
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["input_tokens"], 12)
        self.assertEqual(written[0]["cached_tokens"], 2)
        self.assertEqual(written[0]["thinking_tokens"], 3)
        self.assertEqual(written[0]["document_id"], "d1")
        self.assertNotIn("raw_request", written[0])
        self.assertNotIn("raw_response", written[0])

    def test_deepseek_usage_mapping(self) -> None:
        self.assertEqual(
            logs._usage("deepseek", {"usage": {"prompt_tokens": 9, "completion_tokens": 4,
                                              "prompt_cache_hit_tokens": 2,
                                              "completion_tokens_details": {
                                                  "reasoning_tokens": 3
                                              }}}),
            (9, 4, 2, 3),
        )

    def test_deepseek_flash_uses_conservative_peak_pricing(self) -> None:
        usd, _inr = logs.calculate_costs(
            model="deepseek-flash",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cached_tokens=0,
            thinking_tokens=0,
            usd_to_inr_rate=83,
        )
        self.assertEqual(str(usd), "1.50000000")


class _LogsQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows, self.filters, self.single = rows, [], False

    def select(self, *_args, **_kwargs): return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def gte(self, *_args): return self
    def lte(self, *_args): return self
    def order(self, *_args, **_kwargs): return self
    def range(self, *_args): return self
    def maybe_single(self): self.single = True; return self
    def execute(self):
        rows = [row for row in self.rows if all(row.get(k) == v for k, v in self.filters)]
        return type("Response", (), {"data": rows[0] if self.single and rows else (None if self.single else rows), "count": len(rows)})()


class ApiLogsEndpointTests(unittest.TestCase):
    def _client(self, role: str) -> TestClient:
        app = FastAPI()
        app.include_router(api_logs.router)
        app.dependency_overrides[get_current_profile] = lambda: CurrentProfile(
            user_id="u1", tenant_id="t1", role=role
        )
        return TestClient(app)

    def test_non_super_admin_is_rejected_before_any_log_read(self) -> None:
        self.assertEqual(self._client("teacher").get("/api/v1/platform/api-logs").status_code, 403)

    def test_super_admin_list_paginates_and_filters(self) -> None:
        rows = [{"id": "l1", "tenant_id": "t1", "document_id": "d1", "job_id": None,
                 "call_type": "quiz_generation", "provider": "gemini", "model": "gemini-3.5-flash",
                 "was_fallback": False, "input_tokens": 1, "output_tokens": 2, "cached_tokens": 0,
                 "thinking_tokens": None, "cost_usd": "0.1", "cost_inr": "8.3", "latency_ms": 10,
                 "status": "success", "error_message": None, "created_at": "2026-09-19T00:00:00Z",
                 "raw_request": {"contents": []}, "raw_response": {"ok": True},
                 "documents": {"original_filename": "paper.pdf"}}]
        service = type("Service", (), {"table": lambda _self, _name: _LogsQuery(rows)})()
        with patch.object(api_logs, "get_service_client", return_value=service):
            body = self._client("super_admin").get(
                "/api/v1/platform/api-logs?provider=gemini&page=1&page_size=50"
            ).json()
        self.assertEqual(body["total"], 1)
        exposed = body["items"][0]
        self.assertEqual(exposed["provider"], "gemini")
        for forbidden in (
            "id", "tenant_id", "document_id", "document_name", "job_id",
            "raw_request", "raw_response",
        ):
            self.assertNotIn(forbidden, exposed)
