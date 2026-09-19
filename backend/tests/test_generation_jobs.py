from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.generation_jobs import (
    GenerationJobRunner,
    create_generation_job,
)
from app.services.extraction import ExtractedText, PageSpan

MODULE = "app.services.generation_jobs"


# --- tiny in-memory fake supabase (select/eq/maybe_single/update/insert) ----

class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self._single = "select", [], None, False

    def select(self, *_a):
        self.op = "select"; return self

    def insert(self, rows):
        self.op, self.payload = "insert", rows if isinstance(rows, list) else [rows]
        return self

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
            if self._single:
                return type("R", (), {"data": out[0] if out else None})
            return type("R", (), {"data": out})
        if self.op == "insert":
            created = []
            for p in self.payload:
                r = dict(p); r.setdefault("id", f"{self.table}-{len(rows)+len(created)+1}")
                created.append(r)
            rows.extend(created)
            return type("R", (), {"data": created})
        if self.op == "update":
            changed = []
            for r in rows:
                if self._match(r):
                    r.update(self.payload); changed.append(dict(r))
            return type("R", (), {"data": changed})
        return type("R", (), {"data": []})


class _Fake:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Query(self.db, name)


class _StubChunker:
    def __init__(self, fake, chunk_count):
        self.fake, self.chunk_count = fake, chunk_count
        self.calls = 0

    def chunk_and_store(self, *, document_id, tenant_id, text, page_spans=()):
        self.calls += 1
        rows = self.fake.db.setdefault("document_chunks", [])
        if not any(r["document_id"] == document_id for r in rows):
            for i in range(self.chunk_count):
                rows.append(
                    {"id": f"c{i}", "document_id": document_id,
                     "tenant_id": tenant_id, "chunk_index": i}
                )


class _StubMapper:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.last_summary = None

    def run(
        self, *, document_id, tenant_id, document_title="", document_summary="",
        profile=None,
    ):
        self.calls += 1
        self.last_summary = document_summary
        return self.result


class _StubReducer:
    def __init__(self, blueprint=None, error=None):
        self.blueprint, self.error = blueprint, error
        self.calls = 0
        self.last_summary = None

    def synthesize(
        self, *, document_id, tenant_id, document_title="", document_summary="",
        profile=None,
    ):
        self.calls += 1
        self.last_summary = document_summary
        if self.error:
            raise self.error
        return self.blueprint


class _StubProfiler:
    """Stand-in for profile_document so tests never hit the LLM."""

    def __init__(self, profile=None):
        self.profile = profile if profile is not None else {"subject": "S", "summary": "Y"}
        self.calls = 0

    def __call__(self, text):
        self.calls += 1
        return self.profile


class _StubSingleCallAnalyzer:
    def __init__(self, blueprint=None, error=None, raw_response=None):
        self.blueprint = blueprint
        self.error = error
        self.raw_response = raw_response
        self.calls = 0
        self.saved_responses = []

    def __call__(
        self,
        extracted,
        *,
        document_title="",
        saved_response=None,
        response_checkpoint=None,
    ):
        self.calls += 1
        self.saved_responses.append(saved_response)
        if response_checkpoint is not None and self.raw_response is not None:
            response_checkpoint(self.raw_response)
        if self.error:
            raise self.error
        return self.blueprint


def _seed_job(fake, *, job_id="j1", tenant_id="t1", document_id="d1", chapter="Ch"):
    fake.db.setdefault("quiz_generation_jobs", []).append(
        {
            "id": job_id, "tenant_id": tenant_id, "document_id": document_id,
            "created_by": "u1", "params": {"profile_rate_limit_reserved": True},
            "chapter_name": chapter, "status": "queued", "phase": "queued",
            "total_chunks": 0, "done_chunks": 0, "master_blueprint": None,
            "error_message": None,
        }
    )


BP = {"document_title": "Ch", "source_topic_count": 5, "topics": [{"topic_name": "A"}]}


class RunTests(unittest.TestCase):
    def _runner(self, fake, *, chunks=3, map_res=None, reducer=None, profiler=None):
        return GenerationJobRunner(
            service=fake,
            chunker=_StubChunker(fake, chunks),
            mapper=_StubMapper(map_res or {"total": chunks, "succeeded": chunks, "failed": 0}),
            reducer=reducer or _StubReducer(blueprint=BP),
            text_loader=lambda *_a: "some extracted text",
            profiler=profiler or _StubProfiler(),
        )

    def test_happy_path_completes(self) -> None:
        fake = _Fake(); _seed_job(fake)
        result = self._runner(fake).run(job_id="j1")

        self.assertEqual(result["status"], "completed")
        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["phase"], "ready")
        self.assertEqual(job["total_chunks"], 3)
        self.assertEqual(job["done_chunks"], 3)
        self.assertEqual(job["master_blueprint"], BP)
        self.assertIsNone(job["error_message"])

    def test_partial_when_some_chunks_fail(self) -> None:
        fake = _Fake(); _seed_job(fake)
        runner = self._runner(
            fake, chunks=3, map_res={"total": 3, "succeeded": 2, "failed": 1}
        )
        result = runner.run(job_id="j1")

        self.assertEqual(result["status"], "partial")
        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["phase"], "mapping")
        self.assertEqual(job["done_chunks"], 2)
        self.assertIsNone(job["master_blueprint"])
        self.assertIn("1 of 3", job["error_message"])

    def test_all_chunks_fail_marks_job_failed(self) -> None:
        fake = _Fake(); _seed_job(fake)
        runner = self._runner(
            fake, chunks=3, map_res={"total": 3, "succeeded": 0, "failed": 3}
        )
        with self.assertRaises(RuntimeError):
            runner.run(job_id="j1")

        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(job["status"], "failed")
        self.assertIn("every chunk", job["error_message"])
        self.assertIsNone(job["master_blueprint"])

    def test_reduce_error_marks_job_failed(self) -> None:
        fake = _Fake(); _seed_job(fake)
        runner = self._runner(fake, reducer=_StubReducer(error=RuntimeError("reduce boom")))
        with self.assertRaises(RuntimeError):
            runner.run(job_id="j1")
        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(job["status"], "failed")
        self.assertIn("reduce boom", job["error_message"])

    def test_resume_does_not_rechunk(self) -> None:
        """Second run() reuses stored chunks (idempotent chunker)."""
        fake = _Fake(); _seed_job(fake)
        chunker = _StubChunker(fake, 3)
        runner = GenerationJobRunner(
            service=fake, chunker=chunker,
            mapper=_StubMapper({"total": 3, "succeeded": 3, "failed": 0}),
            reducer=_StubReducer(blueprint=BP),
            text_loader=lambda *_a: "text",
            profiler=_StubProfiler(),
        )
        runner.run(job_id="j1")
        runner.run(job_id="j1")  # resume
        self.assertEqual(chunker.calls, 2)
        # only 3 chunk rows despite two runs (chunker skipped the second time)
        self.assertEqual(len(fake.db["document_chunks"]), 3)

    def test_missing_job_is_noop(self) -> None:
        fake = _Fake()
        result = self._runner(fake).run(job_id="nope")
        self.assertEqual(result["status"], "missing")

    def test_text_loader_failure_marks_failed(self) -> None:
        fake = _Fake(); _seed_job(fake)

        def boom(*_a):
            raise ValueError("no text")

        runner = GenerationJobRunner(
            service=fake, chunker=_StubChunker(fake, 3),
            mapper=_StubMapper({"total": 3, "succeeded": 3, "failed": 0}),
            reducer=_StubReducer(blueprint=BP), text_loader=boom,
            profiler=_StubProfiler(),
        )
        with self.assertRaises(ValueError):
            runner.run(job_id="j1")
        self.assertEqual(fake.db["quiz_generation_jobs"][0]["status"], "failed")

    def test_profiles_once_and_passes_summary_to_map_and_reduce(self) -> None:
        fake = _Fake(); _seed_job(fake)
        profiler = _StubProfiler({"subject": "Algebra", "summary": "Teaches algebra."})
        mapper = _StubMapper({"total": 3, "succeeded": 3, "failed": 0})
        reducer = _StubReducer(blueprint=BP)
        runner = GenerationJobRunner(
            service=fake, chunker=_StubChunker(fake, 3), mapper=mapper,
            reducer=reducer, text_loader=lambda *_a: "text", profiler=profiler,
        )
        runner.run(job_id="j1")

        # profile stored on the job, and its summary reached MAP and REDUCE
        self.assertEqual(profiler.calls, 1)
        stored = fake.db["quiz_generation_jobs"][0]["params"]["document_profile"]
        self.assertEqual(stored["subject"], "Algebra")
        self.assertIn("Algebra", mapper.last_summary)
        self.assertIn("Teaches algebra.", reducer.last_summary)

        # resume reuses the stored profile — no second profiling call
        runner.run(job_id="j1")
        self.assertEqual(profiler.calls, 1)

    def test_unreserved_background_profile_call_is_rate_limited(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {}
        with patch(
            f"{MODULE}.get_settings",
            return_value=SimpleNamespace(rate_limit_topic_extraction_per_hour=10),
        ), patch(f"{MODULE}.enforce_ai_rate_limit") as limit:
            self._runner(fake).run(job_id="j1")
        limit.assert_called_once()
        self.assertEqual(limit.call_args.kwargs["endpoint"], "topic_extraction")

    def test_confident_local_outline_skips_every_ai_analysis_stage(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {
            "prefer_local_outline": True,
            "profile_rate_limit_reserved": False,
        }
        local_blueprint = {
            "analysis_mode": "local_typed_pdf_outline",
            "source_topic_count": 1,
            "topics": [{"topic_name": "Networks"}],
            "local_outline": {"provider_calls": 0},
        }
        chunker = _StubChunker(fake, 3)
        mapper = _StubMapper({"total": 3, "succeeded": 3, "failed": 0})
        reducer = _StubReducer(blueprint=BP)
        profiler = _StubProfiler()
        extracted = ExtractedText(
            "typed pdf text",
            (PageSpan(1, 0, len("typed pdf text")),),
        )
        runner = GenerationJobRunner(
            service=fake,
            chunker=chunker,
            mapper=mapper,
            reducer=reducer,
            text_loader=lambda *_a: extracted,
            profiler=profiler,
        )
        with patch(f"{MODULE}.build_local_pdf_outline", return_value=local_blueprint), patch(
            f"{MODULE}.enforce_ai_rate_limit"
        ) as limit:
            result = runner.run(job_id="j1")

        self.assertEqual(result["analysis_mode"], "local_typed_pdf_outline")
        self.assertEqual(chunker.calls, 0)
        self.assertEqual(mapper.calls, 0)
        self.assertEqual(reducer.calls, 0)
        self.assertEqual(profiler.calls, 0)
        limit.assert_not_called()
        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["master_blueprint"]["topics"][0]["topic_name"], "Networks")

    def test_inconclusive_local_outline_uses_exactly_one_ai_analysis(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {
            "prefer_local_outline": True,
            "profile_rate_limit_reserved": False,
            "single_call_ai_outline": True,
            "allow_multi_call_fallback": False,
        }
        blueprint = {
            "analysis_mode": "single_call_ai_outline",
            "source_topic_count": 3,
            "topics": [{"topic_name": "Networks"}],
        }
        analyzer = _StubSingleCallAnalyzer(blueprint)
        chunker = _StubChunker(fake, 3)
        mapper = _StubMapper({"total": 3, "succeeded": 3, "failed": 0})
        reducer = _StubReducer(blueprint=BP)
        profiler = _StubProfiler()
        extracted = ExtractedText("typed pdf text", (PageSpan(1, 0, 14),))
        runner = GenerationJobRunner(
            service=fake,
            chunker=chunker,
            mapper=mapper,
            reducer=reducer,
            text_loader=lambda *_a: extracted,
            profiler=profiler,
            single_call_analyzer=analyzer,
        )
        with patch(f"{MODULE}.build_local_pdf_outline", return_value=None), patch(
            f"{MODULE}.enforce_ai_rate_limit"
        ) as limit:
            result = runner.run(job_id="j1")

        self.assertEqual(result["analysis_mode"], "single_call_ai_outline")
        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(chunker.calls, 0)
        self.assertEqual(mapper.calls, 0)
        self.assertEqual(reducer.calls, 0)
        self.assertEqual(profiler.calls, 0)
        limit.assert_called_once()
        self.assertEqual(fake.db["quiz_generation_jobs"][0]["status"], "completed")

    def test_non_paginated_document_uses_same_single_call_path(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {
            "prefer_local_outline": False,
            "profile_rate_limit_reserved": True,
            "single_call_ai_outline": True,
            "allow_multi_call_fallback": False,
        }
        blueprint = {
            "analysis_mode": "single_call_ai_outline",
            "source_topic_count": 1,
            "topics": [{"topic_name": "Employment law"}],
        }
        analyzer = _StubSingleCallAnalyzer(blueprint)
        chunker = _StubChunker(fake, 3)
        mapper = _StubMapper({"total": 3, "succeeded": 3, "failed": 0})
        reducer = _StubReducer(blueprint=BP)
        profiler = _StubProfiler()
        runner = GenerationJobRunner(
            service=fake,
            chunker=chunker,
            mapper=mapper,
            reducer=reducer,
            text_loader=lambda *_a: ExtractedText("A long DOCX document"),
            profiler=profiler,
            single_call_analyzer=analyzer,
        )

        with patch(f"{MODULE}.enforce_ai_rate_limit") as limit:
            result = runner.run(job_id="j1")

        self.assertEqual(result["analysis_mode"], "single_call_ai_outline")
        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(chunker.calls, 0)
        self.assertEqual(mapper.calls, 0)
        self.assertEqual(reducer.calls, 0)
        self.assertEqual(profiler.calls, 0)
        limit.assert_not_called()

    def test_one_call_failure_never_enters_costly_map_reduce(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {
            "prefer_local_outline": True,
            "profile_rate_limit_reserved": False,
            "single_call_ai_outline": True,
            "allow_multi_call_fallback": False,
        }
        analyzer = _StubSingleCallAnalyzer(error=RuntimeError("provider failed"))
        chunker = _StubChunker(fake, 3)
        mapper = _StubMapper({"total": 3, "succeeded": 3, "failed": 0})
        reducer = _StubReducer(blueprint=BP)
        extracted = ExtractedText("typed pdf text", (PageSpan(1, 0, 14),))
        runner = GenerationJobRunner(
            service=fake,
            chunker=chunker,
            mapper=mapper,
            reducer=reducer,
            text_loader=lambda *_a: extracted,
            profiler=_StubProfiler(),
            single_call_analyzer=analyzer,
        )
        with patch(f"{MODULE}.build_local_pdf_outline", return_value=None), patch(
            f"{MODULE}.enforce_ai_rate_limit"
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                runner.run(job_id="j1")

        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(chunker.calls, 0)
        self.assertEqual(mapper.calls, 0)
        self.assertEqual(reducer.calls, 0)
        self.assertEqual(fake.db["quiz_generation_jobs"][0]["status"], "failed")

    def test_one_call_retry_reuses_checkpoint_without_provider_or_rate_limit(self) -> None:
        fake = _Fake(); _seed_job(fake)
        fake.db["quiz_generation_jobs"][0]["params"] = {
            "prefer_local_outline": False,
            "profile_rate_limit_reserved": False,
            "single_call_ai_outline": True,
            "allow_multi_call_fallback": False,
        }
        raw_response = {"document_title": "Saved", "groups": []}
        first = _StubSingleCallAnalyzer(
            error=RuntimeError("local processing failed"),
            raw_response=raw_response,
        )
        extracted = ExtractedText("typed pdf text", (PageSpan(1, 0, 14),))
        first_runner = GenerationJobRunner(
            service=fake,
            text_loader=lambda *_a: extracted,
            single_call_analyzer=first,
        )
        with patch(f"{MODULE}.enforce_ai_rate_limit") as first_limit:
            with self.assertRaisesRegex(RuntimeError, "local processing failed"):
                first_runner.run(job_id="j1")
        first_limit.assert_called_once()

        job = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(
            job["params"]["single_call_response_checkpoint"], raw_response
        )
        job["status"] = "queued"
        resumed = _StubSingleCallAnalyzer(blueprint=BP)
        resumed_runner = GenerationJobRunner(
            service=fake,
            text_loader=lambda *_a: extracted,
            single_call_analyzer=resumed,
        )
        with patch(f"{MODULE}.enforce_ai_rate_limit") as retry_limit:
            result = resumed_runner.run(job_id="j1")

        retry_limit.assert_not_called()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(resumed.calls, 1)
        self.assertEqual(resumed.saved_responses, [raw_response])
        self.assertEqual(job["params"]["single_call_checkpoint_status"], "processed")


class CreateJobTests(unittest.TestCase):
    def test_create_inserts_queued_and_launches(self) -> None:
        fake = _Fake()
        with patch(f"{MODULE}.get_service_client", return_value=fake), patch(
            f"{MODULE}.launch_job"
        ) as launch:
            job_id = create_generation_job(
                document_id="d1", tenant_id="t1", created_by="u1",
                subject_id="s1", chapter_name="Ch",
            )
        row = fake.db["quiz_generation_jobs"][0]
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["phase"], "queued")
        self.assertEqual(row["document_id"], "d1")
        launch.assert_called_once_with(job_id, "t1")

    def test_create_can_skip_launch(self) -> None:
        fake = _Fake()
        with patch(f"{MODULE}.get_service_client", return_value=fake), patch(
            f"{MODULE}.launch_job"
        ) as launch:
            create_generation_job(
                document_id="d1", tenant_id="t1", created_by="u1", launch=False
            )
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
