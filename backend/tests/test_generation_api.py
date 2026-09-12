from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import quiz as quiz_api
from app.lib.auth import CurrentProfile, get_current_profile

MOD = "app.api.quiz"


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


DOC_DB = {"documents": [
    {"id": "d1", "tenant_id": "t1", "uploaded_by": "u1",
     "storage_path": "p", "file_type": "pdf"}
]}


class AnalyzeTests(unittest.TestCase):
    def test_small_document_returns_direct_topics(self) -> None:
        with patch(f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))), patch(
            f"{MOD}.download_bytes", return_value=b""
        ), patch(f"{MOD}.extract_text", return_value="short text"), patch(
            f"{MOD}.enforce_ai_rate_limit"
        ), patch(f"{MOD}.extract_topics", return_value=["Alpha", "Beta"]):
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["mode"], "direct")
        self.assertEqual(body["topics"], ["Alpha", "Beta"])

    def test_large_document_creates_job(self) -> None:
        big = "x" * 200_000  # > default 100k trigger
        with patch(f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))), patch(
            f"{MOD}.download_bytes", return_value=b""
        ), patch(f"{MOD}.extract_text", return_value=big), patch(
            f"{MOD}.create_generation_job", return_value="job-1"
        ) as create:
            res = _client().post("/api/v1/quiz-sets/analyze", json={"document_id": "d1"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["mode"], "job")
        self.assertEqual(body["job_id"], "job-1")
        create.assert_called_once()

    def test_empty_text_is_rejected(self) -> None:
        with patch(f"{MOD}.get_service_client", return_value=_Fake(dict(DOC_DB))), patch(
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
        launch.assert_called_once_with("j1")
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
        with patch(f"{MOD}.enforce_ai_rate_limit"), patch(
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


if __name__ == "__main__":
    unittest.main()
