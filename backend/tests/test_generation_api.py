from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import quiz as quiz_api
from app.lib.auth import CurrentProfile, get_current_profile

MOD = "app.api.quiz"

SETTINGS = SimpleNamespace(
    chunking_trigger_chars=100_000,
    rate_limit_topic_extraction_per_hour=10,
    generation_chunk_stuck_seconds=900,
    rate_limit_quiz_generation_per_hour=10,
    rate_limit_blueprint_per_hour=10,
)


def _client(role="teacher"):
    app = FastAPI()
    app.include_router(quiz_api.router)
    app.dependency_overrides[get_current_profile] = lambda: CurrentProfile(
        user_id="u1", tenant_id="t1", role=role
    )
    return TestClient(app)


# --- fake supabase ----------------------------------------------------------

class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self._single = "select", [], None, False

    def select(self, *_a):
        self.op = "select"; return self

    def update(self, values):
        self.op, self.payload = "update", values; return self

    def eq(self, k, v):
        self.filters.append((k, v)); return self

    def maybe_single(self):
        self._single = True; return self

    def _match(self, r):
        return all(r.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            return type("R", (), {"data": (out[0] if out else None) if self._single else out})
        if self.op == "update":
            changed = []
            for r in rows:
                if self._match(r):
                    r.update(self.payload); changed.append(dict(r))
            return type("R", (), {"data": changed})
        return type("R", (), {"data": []})


class _Fake:
    def __init__(self, db=None):
        self.db = db or {}

    def table(self, name):
        return _Query(self.db, name)


class _RateLimitCall:
    def __init__(self, owner, params):
        self.owner = owner
        self.params = params

    def execute(self):
        self.owner.rate_count += 1
        limit = self.params["p_limit"]
        allowed = self.owner.rate_count <= limit
        return type("R", (), {"data": [{
            "allowed": allowed,
            "retry_after_seconds": 3600 if not allowed else 0,
            "remaining": max(0, limit - self.owner.rate_count),
        }]})


class _RateLimitedFake(_Fake):
    def __init__(self, db=None):
        super().__init__(db)
        self.rate_count = 0

    def rpc(self, name, params):
        self.last_rpc = (name, params)
        return _RateLimitCall(self, params)


DOC_DB = {"documents": [
    {"id": "d1", "tenant_id": "t1", "uploaded_by": "u1",
     "storage_path": "p", "file_type": "pdf"}
]}


class AnalyzeTests(unittest.TestCase):
    def test_small_document_returns_direct_topics(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))
        ), patch(
            f"{MOD}.download_bytes", return_value=b""
        ), patch(f"{MOD}.extract_text", return_value="short text"), patch(
            f"{MOD}.enforce_ai_rate_limit"
        ), patch(f"{MOD}.profile_document", return_value={}), patch(
            f"{MOD}.extract_topic_details",
            return_value=[
                {"topic_name": "Alpha", "source_excerpts": [{"text": "Alpha fact"}]},
                {
                    "topic_name": "Beta",
                    "formulas": [{"formula": "x = 2"}],
                    "source_excerpts": [{"text": "x = 2"}],
                },
            ],
        ):
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["mode"], "direct")
        self.assertEqual(body["topics"], ["Alpha", "Beta"])
        self.assertEqual(body["topic_question_limits"], {"Alpha": 1, "Beta": 3})

    def test_small_document_returns_major_topic_with_child_preview(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))
        ), patch(f"{MOD}.download_bytes", return_value=b""), patch(
            f"{MOD}.extract_text", return_value="short text"
        ), patch(f"{MOD}.enforce_ai_rate_limit"), patch(
            f"{MOD}.profile_document", return_value={}
        ), patch(
            f"{MOD}.extract_topic_details",
            return_value=[{
                "topic_name": "Electromagnetism",
                "subtopics": ["Ohm's Law", "Coulomb's Law"],
                "formulas": [
                    {"name": "Ohm's Law", "formula": "V = IR"},
                    {"name": "Coulomb's Law", "formula": "F = k(q1q2)/r²"},
                ],
            }],
        ):
            res = _client().post(
                "/api/v1/quiz-sets/analyze", json={"document_id": "d1"}
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["topics"], ["Electromagnetism"])
        self.assertEqual(
            res.json()["topic_groups"][0]["subtopics"],
            ["Ohm's Law", "Coulomb's Law"],
        )

    def test_large_document_creates_job(self) -> None:
        big = "x" * 200_000  # > default 100k trigger
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))
        ), patch(
            f"{MOD}.download_bytes", return_value=b""
        ), patch(f"{MOD}.extract_text", return_value=big), patch(
            f"{MOD}.enforce_ai_rate_limit"
        ) as limit, patch(f"{MOD}.create_generation_job", return_value="job-1"
        ) as create:
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["mode"], "job")
        self.assertEqual(body["job_id"], "job-1")
        create.assert_called_once_with(
            document_id="d1", tenant_id="t1", created_by="u1",
            params={"profile_rate_limit_reserved": True},
        )
        limit.assert_called_once()

    def test_large_document_rate_limit_blocks_before_job_creation(self) -> None:
        big = "x" * 200_000
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))
        ), patch(f"{MOD}.download_bytes", return_value=b""), patch(
            f"{MOD}.extract_text", return_value=big
        ), patch(
            f"{MOD}.enforce_ai_rate_limit",
            side_effect=HTTPException(status_code=429, detail="limit reached"),
        ), patch(f"{MOD}.create_generation_job") as create:
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 429)
        create.assert_not_called()

    def test_repeated_large_analyze_requests_stop_at_configured_limit(self) -> None:
        settings = SimpleNamespace(**{**SETTINGS.__dict__, "rate_limit_topic_extraction_per_hour": 2})
        service = _RateLimitedFake(dict(DOC_DB))
        big = "x" * 200_000
        with patch(f"{MOD}.get_settings", return_value=settings), patch(
            f"{MOD}.get_service_client", return_value=service
        ), patch(
            "app.services.rate_limit.get_service_client", return_value=service
        ), patch(f"{MOD}.download_bytes", return_value=b""), patch(
            f"{MOD}.extract_text", return_value=big
        ), patch(f"{MOD}.create_generation_job", return_value="job-1") as create:
            responses = [
                _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
                for _ in range(3)
            ]
        self.assertEqual([response.status_code for response in responses], [200, 200, 429])
        self.assertEqual(create.call_count, 2)
        self.assertEqual(service.last_rpc[0], "consume_ai_rate_limit")

    def test_empty_text_is_rejected(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))
        ), patch(
            f"{MOD}.download_bytes", return_value=b""
        ), patch(f"{MOD}.extract_text", return_value="   "):
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 400)

    def test_missing_document_404(self) -> None:
        with patch(f"{MOD}.get_service_client", return_value=_Fake({"documents": []})):
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "zzz"})
        self.assertEqual(res.status_code, 404)

    def test_non_teacher_forbidden(self) -> None:
        res = _client(role="student").post(
            "/api/v1/quiz-sets/analyze", json={"document_id": "d1"}
        )
        self.assertEqual(res.status_code, 403)


JOB_ROW = {
    "id": "j1", "tenant_id": "t1", "created_by": "u1", "document_id": "d1",
    "status": "completed", "phase": "ready", "total_chunks": 3, "done_chunks": 3,
    "error_message": None, "quiz_set_id": None,
    "master_blueprint": {"topics": [
        {"topic_name": "Strings", "subtopics": ["indexing"]},
        {"topic_name": ""},  # dropped
    ]},
}


class JobStatusTests(unittest.TestCase):
    def test_returns_status_and_blueprint_topics(self) -> None:
        with patch(f"{MOD}.get_service_client",
                   return_value=_Fake({"quiz_generation_jobs": [dict(JOB_ROW)]})):
            res = _client().get("/api/v1/quiz-sets/generation-jobs/j1")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["done_chunks"], 3)
        self.assertEqual([t["name"] for t in body["topics"]], ["Strings"])

    def test_stale_running_job_becomes_retryable_failure(self) -> None:
        stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        row = dict(JOB_ROW, status="running", phase="mapping", updated_at=stale)
        fake = _Fake({
            "quiz_generation_jobs": [row],
            "document_chunks": [{
                "id": "c1", "document_id": "d1", "tenant_id": "t1",
                "map_status": "running",
            }],
        })
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.get_service_client", return_value=fake
        ):
            res = _client().get("/api/v1/quiz-sets/generation-jobs/j1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "failed")
        self.assertIn("Retry", res.json()["error_message"])
        self.assertEqual(fake.db["document_chunks"][0]["map_status"], "failed")

    def test_other_tenant_job_404(self) -> None:
        row = dict(JOB_ROW, tenant_id="OTHER")
        with patch(f"{MOD}.get_service_client",
                   return_value=_Fake({"quiz_generation_jobs": [row]})):
            res = _client().get("/api/v1/quiz-sets/generation-jobs/j1")
        self.assertEqual(res.status_code, 404)


class JobRetryTests(unittest.TestCase):
    def test_retry_failed_job_relaunches(self) -> None:
        row = dict(JOB_ROW, status="failed")
        fake = _Fake({"quiz_generation_jobs": [row]})
        with patch(f"{MOD}.get_service_client", return_value=fake), patch(
            f"{MOD}.launch_job"
        ) as launch:
            res = _client().post("/api/v1/quiz-sets/generation-jobs/j1/retry")
        self.assertEqual(res.status_code, 200)
        launch.assert_called_once_with("j1", "t1")
        self.assertEqual(fake.db["quiz_generation_jobs"][0]["status"], "queued")

    def test_cannot_retry_completed_job(self) -> None:
        with patch(f"{MOD}.get_service_client",
                   return_value=_Fake({"quiz_generation_jobs": [dict(JOB_ROW)]})), patch(
            f"{MOD}.launch_job"
        ) as launch:
            res = _client().post("/api/v1/quiz-sets/generation-jobs/j1/retry")
        self.assertEqual(res.status_code, 400)
        launch.assert_not_called()


class JobGenerateTests(unittest.TestCase):
    def _payload(self, **over):
        base = {
            "subject_id": "s1", "chapter_name": "Ch",
            "selected_topics": [{"name": "Strings", "weight": "high"}],
            "type_counts": {"mcq_single": 3},
            "cognitive_level": "mixed", "difficulty": "medium",
        }
        base.update(over)
        return base

    def test_delegates_to_generator_service(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=SETTINGS), patch(
            f"{MOD}.enforce_ai_rate_limit"
        ), patch(
            f"{MOD}.QuizGeneratorService"
        ) as Svc:
            Svc.return_value.generate_from_job.return_value = {"quiz_set_id": "qs1"}
            res = _client().post(
                "/api/v1/quiz-sets/generation-jobs/j1/generate", json=self._payload()
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["quiz_set_id"], "qs1")
        kwargs = Svc.return_value.generate_from_job.call_args.kwargs
        self.assertEqual(kwargs["total_questions"], 3)
        self.assertEqual(kwargs["question_types"], ["mcq_single"])

    def test_rejects_bad_type(self) -> None:
        with patch(f"{MOD}.enforce_ai_rate_limit"), patch(f"{MOD}.QuizGeneratorService"):
            res = _client().post(
                "/api/v1/quiz-sets/generation-jobs/j1/generate",
                json=self._payload(type_counts={"essay": 3}),
            )
        self.assertEqual(res.status_code, 400)

    def test_rejects_over_50(self) -> None:
        with patch(f"{MOD}.enforce_ai_rate_limit"), patch(f"{MOD}.QuizGeneratorService"):
            res = _client().post(
                "/api/v1/quiz-sets/generation-jobs/j1/generate",
                json=self._payload(type_counts={"mcq_single": 51}),
            )
        self.assertEqual(res.status_code, 400)

    def test_rejects_more_topics_than_questions_before_generation(self) -> None:
        topics = [
            {"name": "One", "weight": "high"},
            {"name": "Two", "weight": "medium"},
            {"name": "Three", "weight": "low"},
            {"name": "Four", "weight": "low"},
        ]
        with patch(f"{MOD}.enforce_ai_rate_limit") as limit, patch(
            f"{MOD}.QuizGeneratorService"
        ) as generator:
            res = _client().post(
                "/api/v1/quiz-sets/generation-jobs/j1/generate",
                json=self._payload(selected_topics=topics),
            )
        self.assertEqual(res.status_code, 400)
        self.assertIn("no more topics", res.json()["detail"])
        limit.assert_not_called()
        generator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
