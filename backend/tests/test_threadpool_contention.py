from __future__ import annotations

import asyncio
import statistics
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request

from app.api import quiz as quiz_api
from app.api import student as student_api
from app.lib.auth import CurrentProfile, get_current_profile


app = FastAPI()
app.include_router(quiz_api.router)
app.include_router(student_api.router)


class EmptyQuery:
    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class EmptyService:
    def table(self, _name: str) -> EmptyQuery:
        return EmptyQuery()

    def rpc(self, name: str, _params: dict):
        if name != "student_quiz_catalog_page":
            raise AssertionError(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


class ThreadpoolContentionProbe(unittest.IsolatedAsyncioTestCase):
    async def test_one_generation_does_not_delay_another_accounts_dashboard(self) -> None:
        generation_started = threading.Event()

        def slow_generation(**_kwargs):
            generation_started.set()
            time.sleep(0.5)
            return {"quiz_set_id": "probe", "questions": []}

        async def test_profile(request: Request) -> CurrentProfile:
            role = request.headers.get("x-test-role", "student")
            user_id = "teacher-probe" if role == "teacher" else "student-probe"
            return CurrentProfile(user_id=user_id, tenant_id="tenant-probe", role=role)

        app.dependency_overrides[get_current_profile] = test_profile
        transport = httpx.ASGITransport(app=app)
        service = EmptyService()
        try:
            with (
                patch("app.api.quiz.generate_quiz", side_effect=slow_generation),
                patch("app.api.quiz.enforce_ai_rate_limit"),
                patch(
                    "app.api.quiz.get_settings",
                    return_value=SimpleNamespace(
                        rate_limit_quiz_generation_per_hour=10
                    ),
                ),
                patch("app.api.student.get_service_client", return_value=service),
                patch(
                    "app.api.student.get_settings",
                    return_value=SimpleNamespace(student_quiz_attempt_limit=2),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://probe"
                ) as client:
                    dashboard_times = []
                    for _ in range(7):
                        started = time.perf_counter()
                        response = await client.get(
                            "/api/v1/quizzes", headers={"x-test-role": "student"}
                        )
                        self.assertEqual(response.status_code, 200)
                        dashboard_times.append(time.perf_counter() - started)

                    generation = asyncio.create_task(
                        client.post(
                            "/api/v1/quiz-sets/generate",
                            headers={"x-test-role": "teacher"},
                            json={
                                "document_id": "document-probe",
                                "num_questions": 1,
                                "question_types": ["mcq_single"],
                            },
                        )
                    )
                    while not generation_started.is_set():
                        await asyncio.sleep(0.001)

                    started = time.perf_counter()
                    dashboard = await client.get(
                        "/api/v1/quizzes", headers={"x-test-role": "student"}
                    )
                    during_generation = time.perf_counter() - started
                    generated = await generation

            baseline = statistics.median(dashboard_times)
            print(
                "threadpool-probe "
                f"baseline_ms={baseline * 1000:.2f} "
                f"during_one_generation_ms={during_generation * 1000:.2f} "
                f"difference_ms={(during_generation - baseline) * 1000:.2f}"
            )
            self.assertEqual(dashboard.status_code, 200)
            self.assertEqual(generated.status_code, 200)
            # One long-running sync handler occupies one of AnyIO's 40 default
            # worker tokens; it should not make an unrelated read wait for it.
            self.assertLess(during_generation, 0.25)
        finally:
            app.dependency_overrides.pop(get_current_profile, None)


if __name__ == "__main__":
    unittest.main()
