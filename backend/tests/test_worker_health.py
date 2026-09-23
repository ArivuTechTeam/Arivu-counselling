from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.worker_health import evaluate_worker_health, worker_health

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def _iso(delta_seconds: int) -> str:
    return (NOW + timedelta(seconds=delta_seconds)).isoformat()


def _evaluate(jobs, stale=120):
    return evaluate_worker_health(jobs, now=NOW, stale_seconds=stale)


class EvaluateWorkerHealthTests(unittest.TestCase):
    def test_ok_when_a_worker_holds_a_live_lease(self) -> None:
        result = _evaluate([
            {"status": "running", "created_at": _iso(-30), "updated_at": _iso(-5),
             "lease_expires_at": _iso(25)},  # live lease -> worker alive
            {"status": "queued", "created_at": _iso(-300)},  # old, but a worker exists
        ])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["healthy"])
        self.assertTrue(result["worker_active"])
        self.assertEqual((result["queued"], result["running"]), (1, 1))

    def test_stalled_when_queue_waits_past_threshold_with_no_live_lease(self) -> None:
        result = _evaluate([{"status": "queued", "created_at": _iso(-300)}])
        self.assertEqual(result["status"], "stalled")
        self.assertFalse(result["healthy"])
        self.assertFalse(result["worker_active"])
        self.assertEqual(result["oldest_backlog_seconds"], 300)

    def test_running_job_with_expired_lease_is_backlog(self) -> None:
        # Worker died mid-job: running, lease long expired -> counts as stalled work.
        result = _evaluate([{"status": "running", "created_at": _iso(-400),
                             "updated_at": _iso(-300), "lease_expires_at": _iso(-60)}])
        self.assertEqual(result["status"], "stalled")
        self.assertFalse(result["worker_active"])

    def test_not_stalled_before_threshold(self) -> None:
        # A freshly queued job is not an alarm; a worker may claim it any moment.
        result = _evaluate([{"status": "queued", "created_at": _iso(-30)}])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["healthy"])

    def test_idle_when_no_active_jobs(self) -> None:
        result = _evaluate([])
        self.assertEqual(result["status"], "idle")
        self.assertTrue(result["healthy"])
        self.assertEqual((result["queued"], result["running"]), (0, 0))

    def test_malformed_rows_do_not_raise(self) -> None:
        result = _evaluate([{"status": "queued"}, {"status": "running", "lease_expires_at": "bad"}])
        self.assertIn(result["status"], {"ok", "stalled", "idle"})


class WorkerHealthWrapperTests(unittest.TestCase):
    def test_disabled_when_faculty_jobs_off(self) -> None:
        settings = SimpleNamespace(faculty_jobs_enabled=False)
        self.assertEqual(worker_health(object(), settings)["status"], "disabled")

    def test_read_error_is_reported_safely(self) -> None:
        class _Boom:
            def table(self, *_a):
                return self

            def select(self, *_a):
                return self

            def in_(self, *_a):
                return self

            def limit(self, *_a):
                return self

            def execute(self):
                raise RuntimeError("db down")

        settings = SimpleNamespace(faculty_jobs_enabled=True, faculty_worker_stale_seconds=120)
        result = worker_health(_Boom(), settings, now=NOW)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["healthy"])  # monitoring never hard-fails


if __name__ == "__main__":
    unittest.main()
