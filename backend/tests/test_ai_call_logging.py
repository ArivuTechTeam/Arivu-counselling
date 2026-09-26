from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import api_logs
from app.lib.auth import CurrentProfile, get_current_profile
from app.services import ai_call_logging as logs


class PricingTests(unittest.TestCase):
    def test_missing_usage_is_not_misrepresented_as_free(self) -> None:
        self.assertEqual(logs.calculate_costs(
            model="gemini-3.5-flash", input_tokens=None, output_tokens=None,
            cached_tokens=None, thinking_tokens=None, usd_to_inr_rate=83,
        ), (None, None))
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
    def test_parallel_extraction_keeps_cost_workflow(self) -> None:
        from app.services.quiz_extraction import _text_extract
        observed = []
        token = logs._context.set({**logs._context.get(), "workflow_id": "run"})
        def extract_chunk(*args, **kwargs):
            with logs.ai_call_context("quiz_extraction", tenant_id="t", document_id="d"):
                observed.append(logs._context.get().get("workflow_id"))
            return {"questions": []}, "deepseek"
        try:
            with patch("app.services.quiz_extraction.get_settings", return_value=SimpleNamespace(extraction_text_chunk_chars=2, extraction_chunk_concurrency=2)), patch("app.services.quiz_extraction._extract_text_chunk", side_effect=extract_chunk):
                _text_extract("ab\n\ncd\n\nef", tenant_id="t", document_id="d")
        finally:
            logs._context.reset(token)
        self.assertGreater(len(observed), 1)
        self.assertEqual(set(observed), {"run"})
    def test_workflow_context_survives_nested_stages_and_links_quiz(self) -> None:
        client = MagicMock()
        observed = []
        profile = SimpleNamespace(tenant_id="tenant")

        @logs.track_quiz_workflow("generation")
        def nested(*, profile, document_id):
            with logs.ai_call_context("question_verification", tenant_id="tenant", document_id=document_id):
                observed.append(logs._context.get()["workflow_id"])
            return {"quiz_set_id": "quiz"}

        @logs.track_quiz_workflow("generation")
        def generate(*, profile, document_id):
            with logs.ai_call_context("quiz_generation", tenant_id="tenant", document_id=document_id):
                observed.append(logs._context.get()["workflow_id"])
                return nested(profile=profile, document_id=document_id)

        with patch.object(logs, "get_settings", return_value=SimpleNamespace(app_env="production")), patch.object(logs, "get_service_client", return_value=client):
            self.assertEqual(generate(profile=profile, document_id="document"), {"quiz_set_id": "quiz"})
        self.assertEqual(len(set(observed)), 1)
        self.assertTrue(observed[0])
        client.table.return_value.upsert.assert_called_once()
        self.assertEqual(client.table.return_value.update.call_args.args[0]["quiz_set_id"], "quiz")
        self.assertFalse(logs._context.get().get("workflow_id"))

    def test_telemetry_failure_never_blocks_generation(self) -> None:
        @logs.track_quiz_workflow("generation")
        def generate(*, profile):
            return {"quiz_set_id": "quiz"}
        with patch.object(logs, "get_settings", return_value=SimpleNamespace(app_env="production")), patch.object(logs, "get_service_client", side_effect=RuntimeError()):
            self.assertEqual(generate(profile=SimpleNamespace(tenant_id="t")), {"quiz_set_id": "quiz"})

    def test_worker_retry_reuses_workflow_and_failure_is_recorded(self) -> None:
        client = MagicMock()
        @logs.track_quiz_workflow("generation")
        def work(service, job):
            self.assertEqual(logs._context.get()["workflow_id"], "worker-job")
            raise ValueError("Failure")
        with patch.object(logs, "get_settings", return_value=SimpleNamespace(app_env="production")), patch.object(logs, "get_service_client", return_value=client):
            with self.assertRaises(ValueError):
                work(None, {"id": "worker-job", "tenant_id": "t", "kind": "extraction", "request": {"document_id": "d"}})
        payload = client.table.return_value.upsert.call_args.args[0]
        self.assertEqual(payload["id"], "worker-job")
        self.assertEqual(payload["kind"], "extraction")
        self.assertEqual(client.table.return_value.update.call_args.args[0]["status"], "failed")
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
        self.columns = ""

    def select(self, columns, **_kwargs): self.columns = columns; return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def is_(self, key, value): self.filters.append((key, None)); return self
    def gte(self, *_args): return self
    def lte(self, *_args): return self
    def order(self, *_args, **_kwargs): return self
    def range(self, *_args): return self
    def maybe_single(self): self.single = True; return self
    def execute(self):
        rows = [row for row in self.rows if all(row.get(k) == v for k, v in self.filters)]
        return type("Response", (), {"data": rows[0] if self.single and rows else (None if self.single else rows), "count": len(rows)})()


class ApiLogsEndpointTests(unittest.TestCase):
    def test_cost_summary_requires_super_admin(self) -> None:
        with patch.object(api_logs, "get_service_client") as client:
            for role in ("student", "teacher", "institution_admin"):
                self.assertEqual(self._client(role).get("/api/v1/platform/api-log-workflows").status_code, 403)
            client.assert_not_called()

    def test_cost_summary_filters_and_response_minimization(self) -> None:
        client = MagicMock()
        client.rpc.return_value.execute.return_value.data = {
            "items": [], "total": 0, "cost_usd": None, "call_count": 0, "unpriced_calls": 0,
            "raw_request": "must not escape",
        }
        with patch.object(api_logs, "get_service_client", return_value=client):
            response = self._client("super_admin").get("/api/v1/platform/api-log-workflows?kind=generation&page_size=20")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("raw_request", response.json())
        self.assertEqual(client.rpc.call_args.args[1]["p_kind"], "generation")

    def test_cost_summary_database_error_is_safe(self) -> None:
        with patch.object(api_logs, "get_service_client", side_effect=RuntimeError("private connection")):
            response = self._client("super_admin").get("/api/v1/platform/api-log-workflows")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private connection", response.text)
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
        query = _LogsQuery(rows)
        service = type("Service", (), {"table": lambda _self, _name: query})()
        with patch.object(api_logs, "get_service_client", return_value=service):
            body = self._client("super_admin").get(
                "/api/v1/platform/api-logs?provider=gemini&page=1&page_size=50"
            ).json()
        self.assertEqual(body["total"], 1)
        exposed = body["items"][0]
        self.assertEqual(exposed["provider"], "gemini")
        self.assertEqual(exposed["document_id"], "d1")
        self.assertEqual(exposed["tenant_id"], "t1")
        self.assertEqual(exposed["id"], "l1")
        for forbidden in (
            "document_name", "documents", "raw_request", "raw_response",
        ):
            self.assertNotIn(forbidden, exposed)
            self.assertNotIn(forbidden, query.columns)
        self.assertNotIn("*", query.columns)

    def test_all_other_roles_cannot_read_operational_identifiers(self) -> None:
        with patch.object(api_logs, "get_service_client") as service:
            for role in ("student", "teacher", "institution_admin"):
                self.assertEqual(self._client(role).get("/api/v1/platform/api-logs").status_code, 403)
            service.assert_not_called()

    def test_tenant_and_document_filters_are_validated_and_applied(self) -> None:
        query = _LogsQuery([])
        service = type("Service", (), {"table": lambda _self, _name: query})()
        tenant = "00000000-0000-0000-0000-000000000001"
        document = "00000000-0000-0000-0000-000000000002"
        with patch.object(api_logs, "get_service_client", return_value=service):
            client = self._client("super_admin")
            response = client.get(f"/api/v1/platform/api-logs?tenant_id={tenant}&document_id={document}")
            self.assertEqual(response.status_code, 200)
            self.assertIn(("tenant_id", tenant), query.filters)
            self.assertIn(("document_id", document), query.filters)
            self.assertEqual(client.get("/api/v1/platform/api-logs?document_id=invalid").status_code, 422)
            self.assertEqual(client.get("/api/v1/platform/api-logs?page_size=101").status_code, 422)

    def test_cost_drill_down_separates_runs_from_legacy_calls(self) -> None:
        query = _LogsQuery([])
        service = type("Service", (), {"table": lambda _self, _name: query})()
        run = "00000000-0000-0000-0000-000000000001"
        with patch.object(api_logs, "get_service_client", return_value=service):
            client = self._client("super_admin")
            self.assertEqual(client.get(f"/api/v1/platform/api-logs?workflow_id={run}").status_code, 200)
            self.assertIn(("workflow_id", run), query.filters)
            query.filters.clear()
            self.assertEqual(client.get("/api/v1/platform/api-logs?legacy_only=true&unlinked_only=true&platform_only=true").status_code, 200)
            self.assertEqual(query.filters, [("workflow_id", None), ("document_id", None), ("tenant_id", None)])

    def test_legacy_error_payload_is_not_exposed(self) -> None:
        row = {"status": "error", "error_message": "private prompt and credential",
               "cost_usd": None, "cost_inr": None}
        summary = api_logs._summary(row)
        self.assertEqual(summary["error_message"],
                         "Provider call failed. Check provider availability and configuration.")
