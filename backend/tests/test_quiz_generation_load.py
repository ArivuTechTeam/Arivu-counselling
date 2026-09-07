from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.client import HTTPConnection
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

from app.api import quiz as quiz_api
from app.lib.auth import CurrentProfile, get_current_profile


CONCURRENT_REQUESTS = 15


class QuizGenerationLoadTests(unittest.TestCase):
    def test_fifteen_generation_requests_run_concurrently(self) -> None:
        app = FastAPI()
        app.include_router(quiz_api.router)
        app.dependency_overrides[get_current_profile] = lambda: CurrentProfile(
            user_id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000002",
            role="teacher",
        )

        arrival_barrier = threading.Barrier(CONCURRENT_REQUESTS, timeout=8)
        metrics_lock = threading.Lock()
        active_requests = 0
        peak_requests = 0

        def fake_generate_quiz(**_kwargs) -> dict:
            nonlocal active_requests, peak_requests
            with metrics_lock:
                active_requests += 1
                peak_requests = max(peak_requests, active_requests)
            try:
                arrival_barrier.wait()
                time.sleep(0.1)
                return {"status": "generated"}
            finally:
                with metrics_lock:
                    active_requests -= 1

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(128)
        port = server_socket.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="off")
        )
        server_thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [server_socket]},
            daemon=True,
        )

        payload = json.dumps(
            {
                "document_id": "load-test-document",
                "num_questions": 5,
                "question_types": ["mcq_single"],
                "cognitive_level": "mixed",
                "difficulty": "medium",
            }
        )

        def send_request(_request_number: int) -> tuple[int, float]:
            started = time.perf_counter()
            connection = HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                connection.request(
                    "POST",
                    "/api/v1/quiz-sets/generate",
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                response.read()
                return response.status, time.perf_counter() - started
            finally:
                connection.close()

        with ExitStack() as patches:
            patches.enter_context(
                patch.object(quiz_api, "generate_quiz", side_effect=fake_generate_quiz)
            )
            # Keep this test compatible with the P0 rate-limit branch when the
            # two PRs are combined; rate-limit behavior has its own tests.
            if hasattr(quiz_api, "enforce_ai_rate_limit"):
                patches.enter_context(
                    patch.object(quiz_api, "enforce_ai_rate_limit", return_value=None)
                )

            server_thread.start()
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.started, "Local load-test server did not start")

            overall_started = time.perf_counter()
            try:
                with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
                    results = list(executor.map(send_request, range(CONCURRENT_REQUESTS)))
            finally:
                server.should_exit = True
                server_thread.join(timeout=5)
                server_socket.close()

        statuses = [status for status, _latency in results]
        latencies = [latency for _status, latency in results]
        elapsed = time.perf_counter() - overall_started
        print(
            "quiz generation load test:",
            json.dumps(
                {
                    "requests": CONCURRENT_REQUESTS,
                    "statuses": {str(code): statuses.count(code) for code in set(statuses)},
                    "peak_concurrent_handlers": peak_requests,
                    "total_seconds": round(elapsed, 3),
                    "slowest_request_seconds": round(max(latencies), 3),
                }
            ),
        )

        self.assertEqual(statuses, [200] * CONCURRENT_REQUESTS)
        self.assertEqual(peak_requests, CONCURRENT_REQUESTS)
        self.assertLess(elapsed, 3.0)


if __name__ == "__main__":
    unittest.main()
