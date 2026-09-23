from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.ai_log_retention import (
    _REDACTED,
    redact_expired_ai_logs,
    retention_cutoff,
)

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


class _Query:
    def __init__(self, service: "_Service") -> None:
        self.service = service
        self.op = "select"

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.service.updates.append(payload)
        return self

    def lt(self, *_a):
        return self

    def is_(self, *_a):
        return self

    def in_(self, column, values):
        self.service.updated_ids.append(list(values))
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self.op == "update":
            return SimpleNamespace(data=[])
        batch = self.service.batches.pop(0) if self.service.batches else []
        return SimpleNamespace(data=batch)


class _Service:
    def __init__(self, batches):
        self.batches = list(batches)
        self.updates = []
        self.updated_ids = []

    def table(self, _name):
        return _Query(self)


class _Boom:
    def table(self, _name):
        raise RuntimeError("db down")


class RetentionCutoffTests(unittest.TestCase):
    def test_cutoff_is_now_minus_days(self) -> None:
        self.assertEqual(retention_cutoff(NOW, 30), "2026-08-23T12:00:00+00:00")


class RedactExpiredAiLogsTests(unittest.TestCase):
    def test_redacts_a_single_batch_with_placeholder(self) -> None:
        service = _Service([[{"id": "a"}, {"id": "b"}]])
        result = redact_expired_ai_logs(service, retention_days=30, now=NOW, batch_limit=500)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["redacted"], 2)
        self.assertEqual(result["cutoff"], "2026-08-23T12:00:00+00:00")
        self.assertEqual(service.updates[0], {"raw_request": _REDACTED, "raw_response": _REDACTED})
        self.assertEqual(service.updated_ids[0], ["a", "b"])

    def test_loops_across_batches_until_drained(self) -> None:
        # First full batch (== limit) keeps looping; short batch ends it.
        service = _Service([[{"id": "1"}, {"id": "2"}], [{"id": "3"}]])
        result = redact_expired_ai_logs(service, retention_days=30, now=NOW, batch_limit=2)
        self.assertEqual(result["redacted"], 3)
        self.assertEqual(len(service.updates), 2)

    def test_no_expired_rows_is_a_clean_noop(self) -> None:
        service = _Service([[]])
        result = redact_expired_ai_logs(service, retention_days=30, now=NOW)
        self.assertEqual((result["status"], result["redacted"]), ("ok", 0))
        self.assertEqual(service.updates, [])

    def test_read_failure_is_best_effort(self) -> None:
        result = redact_expired_ai_logs(_Boom(), retention_days=30, now=NOW)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["redacted"], 0)


if __name__ == "__main__":
    unittest.main()
