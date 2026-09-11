from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.challenge import (
    _load_challenge,
    _require_student as require_challenge_student,
)
from app.api.practice import (
    AutosavePractice,
    StartPractice,
    SubmitPractice,
    SubmittedAnswer as PracticeSubmittedAnswer,
    _require_student as require_practice_student,
    _daily_today,
    _streak,
    autosave_practice,
    exam_config,
    get_daily,
    get_practice,
    leaderboard,
    practice_subjects,
    preview_practice,
    start_practice,
    start_daily,
    start_exam,
    submit_practice,
)
from app.api.student import (
    StartAttemptRequest,
    RevisedTopic,
    SubmitRequest,
    SubmittedAnswer,
    _require_student as require_quiz_student,
    _student_graded_answers,
    get_attempt,
    mark_topic_revised,
    revision_topics,
    start_attempt,
    student_attempts,
    submit_attempt,
)
from app.lib.auth import CurrentProfile
from app.services.grading import grade_answer
from app.services.student_access import student_has_graded_question


def profile(role: str = "student") -> CurrentProfile:
    return CurrentProfile(user_id="u1", tenant_id="t1", role=role)


class MemoryQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.want_single = False

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def neq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) != value]
        return self

    def in_(self, key, values):
        allowed = set(values)
        self.rows = [row for row in self.rows if row.get(key) in allowed]
        return self

    def order(self, key, desc=False):
        self.rows.sort(key=lambda row: row.get(key) or "", reverse=desc)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def maybe_single(self):
        self.want_single = True
        return self

    def execute(self):
        data = (
            self.rows[0]
            if self.want_single and self.rows
            else None
            if self.want_single
            else self.rows
        )
        return SimpleNamespace(data=data)


class MemoryService:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables

    def table(self, name: str) -> MemoryQuery:
        return MemoryQuery([dict(row) for row in self.tables.get(name, [])])


class MutableQuery:
    def __init__(self, service: "MutableService", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.neq_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.operation = "select"
        self.payload = None
        self.want_single = False

    def select(self, *_args):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def upsert(self, payload, **_kwargs):
        self.operation = "upsert"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def neq(self, key, value):
        self.neq_filters.append((key, value))
        return self

    def in_(self, key, values):
        self.in_filters.append((key, set(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def maybe_single(self):
        self.want_single = True
        return self

    def single(self):
        self.want_single = True
        return self

    def _matches(self, row: dict) -> bool:
        return (
            all(row.get(k) == v for k, v in self.filters)
            and all(row.get(k) != v for k, v in self.neq_filters)
            and all(row.get(k) in values for k, values in self.in_filters)
        )

    def execute(self):
        rows = self.service.tables.setdefault(self.table, [])
        matches = [row for row in rows if self._matches(row)]
        if self.operation in {"insert", "upsert"}:
            incoming = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for item in incoming:
                row = dict(item)
                row.setdefault("id", f"{self.table}-{self.service.next_id}")
                self.service.next_id += 1
                rows.append(row)
                created.append(dict(row))
            return SimpleNamespace(data=created)
        if self.operation == "update":
            for row in matches:
                row.update(self.payload)
            return SimpleNamespace(data=[dict(row) for row in matches])
        if self.operation == "delete":
            self.service.tables[self.table] = [row for row in rows if not self._matches(row)]
            return SimpleNamespace(data=[dict(row) for row in matches])
        data = [dict(row) for row in matches]
        return SimpleNamespace(
            data=(data[0] if data else None) if self.want_single else data
        )


class MutableService:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables
        self.next_id = 1
        self.calls: list[str] = []

    def table(self, name: str) -> MutableQuery:
        self.calls.append(name)
        return MutableQuery(self, name)


class GradingTests(unittest.TestCase):
    def test_every_supported_question_type_is_deterministic(self) -> None:
        cases = [
            ({"type": "mcq_single", "correct_answer": "B", "marks": 2}, "B", True, 2),
            ({"type": "true_false", "correct_answer": "true", "marks": 1}, "false", False, 0),
            ({"type": "mcq_multi", "correct_answer": ["A", "C"], "marks": 3}, ["C", "A"], True, 3),
            ({"type": "numerical", "correct_answer": {"value": 10, "tolerance": 0.1}, "marks": 2}, 10.05, True, 2),
            ({"type": "fill_blank", "correct_answer": {"answers": ["Net profit"]}, "marks": 1}, " net   profit. ", True, 1),
        ]
        for question, answer, expected_correct, expected_marks in cases:
            with self.subTest(question_type=question["type"]):
                self.assertEqual(
                    grade_answer(question, answer),
                    (expected_correct, float(expected_marks)),
                )

    def test_missing_or_unknown_answers_fail_closed(self) -> None:
        question = {"type": "unknown", "correct_answer": "anything", "marks": 5}
        self.assertEqual(grade_answer(question, "anything"), (False, 0.0))
        question["type"] = "mcq_single"
        self.assertEqual(grade_answer(question, None), (False, 0.0))


class StudentAnalyticsTests(unittest.TestCase):
    def test_history_derives_subject_for_chapter_practice(self) -> None:
        service = MemoryService(
            {
                "quiz_attempts": [],
                "practice_sessions": [
                    {
                        "id": "p1",
                        "tenant_id": "t1",
                        "student_id": "u1",
                        "status": "graded",
                        "mode": "chapter",
                        "subject_id": None,
                        "chapter_id": "chapter-1",
                        "total_score": 4,
                        "max_score": 5,
                        "submitted_at": "2026-09-10T10:00:00Z",
                    },
                    {
                        "id": "challenge-history",
                        "tenant_id": "t1",
                        "student_id": "u1",
                        "status": "graded",
                        "mode": "challenge",
                        "subject_id": "subject-1",
                        "chapter_id": None,
                        "total_score": 5,
                        "max_score": 5,
                        "submitted_at": "2026-09-10T11:00:00Z",
                    },
                ],
                "chapters": [
                    {
                        "id": "chapter-1",
                        "tenant_id": "t1",
                        "subject_id": "subject-1",
                    }
                ],
            }
        )

        with patch("app.api.student.get_service_client", return_value=service):
            history = student_attempts(profile())

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["source"], "practice")
        self.assertEqual(history[0]["subject_id"], "subject-1")
        self.assertEqual(history[0]["chapter_id"], "chapter-1")

    def test_quiz_and_practice_answers_are_combined_and_scoped(self) -> None:
        service = MemoryService(
            {
                "quiz_attempts": [
                    {"id": "a1", "tenant_id": "t1", "student_id": "u1", "status": "graded"},
                    {"id": "a2", "tenant_id": "t1", "student_id": "u2", "status": "graded"},
                ],
                "practice_sessions": [
                    {"id": "p1", "tenant_id": "t1", "student_id": "u1", "status": "graded"},
                    {"id": "p2", "tenant_id": "other", "student_id": "u1", "status": "graded"},
                ],
                "attempt_answers": [
                    {"attempt_id": "a1", "tenant_id": "t1", "question_id": "q1", "is_correct": True},
                    {"attempt_id": "a2", "tenant_id": "t1", "question_id": "q2", "is_correct": True},
                ],
                "practice_answers": [
                    {"session_id": "p1", "tenant_id": "t1", "question_id": "q3", "is_correct": False},
                    {"session_id": "p2", "tenant_id": "other", "question_id": "q4", "is_correct": True},
                ],
            }
        )
        answers, work_count = _student_graded_answers(service, "t1", "u1")
        self.assertEqual(work_count, 2)
        self.assertEqual({row["question_id"] for row in answers}, {"q1", "q3"})

    def test_leaderboard_excludes_other_course_and_ambiguous_practice(self) -> None:
        service = MemoryService(
            {
                "enrollments": [
                    {"tenant_id": "t1", "profile_id": "u1", "course_id": "c1"},
                    {"tenant_id": "t1", "profile_id": "u1", "course_id": "c2"},
                    {"tenant_id": "t1", "profile_id": "u2", "course_id": "c1"},
                ],
                "courses": [
                    {"id": "c1", "tenant_id": "t1", "name": "Course 1"},
                    {"id": "c2", "tenant_id": "t1", "name": "Course 2"},
                ],
                "subjects": [
                    {"id": "s1", "tenant_id": "t1", "course_id": "c1"},
                    {"id": "s2", "tenant_id": "t1", "course_id": "c2"},
                ],
                "quiz_attempts": [
                    {"id": "a1", "tenant_id": "t1", "student_id": "u1", "status": "graded", "variant_id": "v1", "total_score": 3},
                    {"id": "a2", "tenant_id": "t1", "student_id": "u1", "status": "graded", "variant_id": "v2", "total_score": 100},
                    {"id": "a3", "tenant_id": "t1", "student_id": "u2", "status": "graded", "variant_id": "v1", "total_score": 2},
                ],
                "quiz_variants": [
                    {"id": "v1", "tenant_id": "t1", "quiz_set_id": "set1", "total_marks": 4},
                    {"id": "v2", "tenant_id": "t1", "quiz_set_id": "set2", "total_marks": 100},
                ],
                "quiz_sets": [
                    {"id": "set1", "tenant_id": "t1", "subject_id": "s1"},
                    {"id": "set2", "tenant_id": "t1", "subject_id": "s2"},
                ],
                "practice_sessions": [
                    {"id": "p1", "tenant_id": "t1", "student_id": "u1", "status": "graded", "subject_id": "s1", "chapter_id": None, "total_score": 0.75, "max_score": 1},
                    {"id": "p2", "tenant_id": "t1", "student_id": "u1", "status": "graded", "subject_id": "s2", "chapter_id": None, "total_score": 50, "max_score": 50},
                    {"id": "p3", "tenant_id": "t1", "student_id": "u2", "status": "graded", "subject_id": None, "chapter_id": None, "total_score": 1, "max_score": 1},
                    {"id": "p4", "tenant_id": "t1", "student_id": "u1", "status": "graded", "subject_id": None, "chapter_id": None, "total_score": 10, "max_score": 10},
                ],
                "attempt_answers": [
                    {"tenant_id": "t1", "attempt_id": "a1", "is_correct": True},
                    {"tenant_id": "t1", "attempt_id": "a1", "is_correct": False},
                    {"tenant_id": "t1", "attempt_id": "a2", "is_correct": True},
                    {"tenant_id": "t1", "attempt_id": "a3", "is_correct": True},
                ],
                "practice_answers": [
                    {"tenant_id": "t1", "session_id": "p1", "is_correct": False},
                    {"tenant_id": "t1", "session_id": "p2", "is_correct": True},
                    {"tenant_id": "t1", "session_id": "p3", "is_correct": True},
                    {"tenant_id": "t1", "session_id": "p4", "is_correct": True},
                ],
                "profiles": [
                    {"id": "u1", "tenant_id": "t1", "full_name": "One", "role": "student"},
                    {"id": "u2", "tenant_id": "t1", "full_name": "Two", "role": "student"},
                ],
            }
        )
        with patch("app.api.practice.get_service_client", return_value=service):
            result = leaderboard(course_id="c1", profile=profile())

        rows = {row["name"]: row for row in result["top"]}
        self.assertEqual(rows["One"]["points"], 3.75)
        self.assertEqual(rows["One"]["quizzes"], 2)
        self.assertEqual(rows["One"]["accuracy"], 33)
        self.assertEqual(rows["Two"]["points"], 3.0)
        self.assertNotEqual(rows["One"]["points"], 163.75)


class QuizAttemptFlowTests(unittest.TestCase):
    def test_start_take_submit_grade_review_and_history(self) -> None:
        service = MutableService(
            {
                "enrollments": [
                    {"tenant_id": "t1", "profile_id": "u1", "course_id": "c1"}
                ],
                "subjects": [{"id": "s1", "tenant_id": "t1", "course_id": "c1"}],
                "quiz_sets": [
                    {
                        "id": "set1",
                        "tenant_id": "t1",
                        "subject_id": "s1",
                        "status": "published",
                        "title": "Known answers",
                    }
                ],
                "quiz_variants": [
                    {
                        "id": "v1",
                        "tenant_id": "t1",
                        "quiz_set_id": "set1",
                        "variant_type": "mixed",
                        "total_marks": 3,
                        "time_limit_minutes": 10,
                    }
                ],
                "quiz_variant_questions": [
                    {"tenant_id": "t1", "variant_id": "v1", "question_id": "q1", "order_index": 0},
                    {"tenant_id": "t1", "variant_id": "v1", "question_id": "q2", "order_index": 1},
                ],
                "questions": [
                    {
                        "id": "q1",
                        "tenant_id": "t1",
                        "review_status": "approved",
                        "type": "mcq_single",
                        "question_text": "Pick B",
                        "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
                        "correct_answer": "B",
                        "explanation": "B is correct",
                        "marks": 2,
                    },
                    {
                        "id": "q2",
                        "tenant_id": "t1",
                        "review_status": "approved",
                        "type": "true_false",
                        "question_text": "True statement",
                        "options": [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
                        "correct_answer": "true",
                        "explanation": None,
                        "marks": 1,
                    },
                ],
                "quiz_attempts": [],
                "attempt_answers": [],
                "practice_sessions": [],
            }
        )
        with (
            patch("app.api.student.get_service_client", return_value=service),
            patch("app.api.student.log_event"),
            patch(
                "app.api.student.get_settings",
                return_value=SimpleNamespace(student_quiz_attempt_limit=2),
            ),
        ):
            started = start_attempt(StartAttemptRequest(variant_id="v1"), profile())
            attempt_id = started["attempt_id"]
            self.assertEqual(started["status"], "in_progress")
            self.assertEqual(len(started["questions"]), 2)
            self.assertNotIn("correct_answer", started["questions"][0])
            self.assertEqual(started["time_limit_minutes"], 10.0)
            self.assertEqual(
                sum(q["suggested_seconds"] for q in started["questions"]), 600
            )
            # Starting returns the already-loaded state. The eighth query is the
            # backend-enforced two-attempt limit check.
            self.assertEqual(len(service.calls), 8)

            taking = get_attempt(attempt_id, profile())
            # The timed state adds one tenant-scoped variant lookup so refreshes
            # can restore the server-authoritative deadline.
            self.assertEqual(len(service.calls), 12)
            self.assertEqual(taking["status"], "in_progress")
            self.assertNotIn("correct_answer", taking["questions"][0])

            with self.assertRaises(HTTPException) as incomplete:
                submit_attempt(
                    attempt_id,
                    SubmitRequest(
                        answers=[
                            SubmittedAnswer(question_id="q1", student_answer="B")
                        ]
                    ),
                    profile(),
                )
            self.assertEqual(incomplete.exception.status_code, 400)
            self.assertIn("every question", incomplete.exception.detail.lower())

            result = submit_attempt(
                attempt_id,
                SubmitRequest(
                    answers=[
                        SubmittedAnswer(question_id="q1", student_answer="B"),
                        SubmittedAnswer(question_id="q2", student_answer="false"),
                    ]
                ),
                profile(),
            )
            self.assertEqual(result["quiz_title"], "Known answers")
            self.assertEqual(result["total_score"], 2.0)
            self.assertEqual(result["max_score"], 3.0)
            self.assertEqual([r["is_correct"] for r in result["results"]], [True, False])

            reviewed = get_attempt(attempt_id, profile())
            self.assertEqual(reviewed["total_score"], 2.0)
            history = student_attempts(profile())
            self.assertEqual(history[0]["attempt_id"], attempt_id)
            self.assertEqual(history[0]["variant_id"], "v1")
            self.assertEqual(history[0]["subject_id"], "s1")
            self.assertIsNone(history[0]["chapter_id"])

            second = start_attempt(StartAttemptRequest(variant_id="v1"), profile())
            abandoned = submit_attempt(
                second["attempt_id"],
                SubmitRequest(
                    answers=[
                        SubmittedAnswer(question_id="q1", student_answer="B")
                    ],
                    finalize_reason="left",
                ),
                profile(),
            )
            self.assertEqual(abandoned["total_score"], 2.0)
            self.assertIsNone(abandoned["results"][1]["student_answer"])
            self.assertEqual(abandoned["results"][1]["marks_awarded"], 0.0)
            with self.assertRaises(HTTPException) as limit_reached:
                start_attempt(StartAttemptRequest(variant_id="v1"), profile())
            self.assertEqual(limit_reached.exception.status_code, 400)
            self.assertIn("all 2 attempts", limit_reached.exception.detail.lower())

            other = CurrentProfile(user_id="u2", tenant_id="t1", role="student")
            with self.assertRaises(HTTPException) as caught:
                get_attempt(attempt_id, other)
            self.assertEqual(caught.exception.status_code, 404)


class PracticeAndRevisionFlowTests(unittest.TestCase):
    def test_smart_quiz_start_autosave_submit_and_all_subject_history(self) -> None:
        service = MutableService(
            {
                "enrollments": [
                    {"tenant_id": "t1", "profile_id": "u1", "course_id": "c1"}
                ],
                "subjects": [
                    {"id": "s1", "tenant_id": "t1", "course_id": "c1", "name": "Maths"}
                ],
                "chapters": [{"id": "ch1", "tenant_id": "t1", "subject_id": "s1"}],
                "questions": [
                    {
                        "id": "q1",
                        "tenant_id": "t1",
                        "chapter_id": "ch1",
                        "review_status": "approved",
                        "difficulty": "easy",
                        "type": "mcq_single",
                        "question_text": "Pick A",
                        "options": [{"id": "A", "text": "A"}],
                        "correct_answer": "A",
                        "explanation": "A",
                        "marks": 1,
                    },
                    {
                        "id": "q2",
                        "tenant_id": "t1",
                        "chapter_id": "ch1",
                        "review_status": "approved",
                        "difficulty": "easy",
                        "type": "numerical",
                        "question_text": "One plus one",
                        "options": None,
                        "correct_answer": {"value": 2, "tolerance": 0},
                        "explanation": "2",
                        "marks": 2,
                    },
                ],
                "practice_sessions": [],
                "practice_answers": [],
                "quiz_attempts": [],
            }
        )
        body = StartPractice(mode="smart", count=10, difficulty="easy")
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.student.get_service_client", return_value=service),
        ):
            listed_subjects = practice_subjects(profile())
            self.assertEqual(
                [(row["id"], row["name"]) for row in listed_subjects],
                [("s1", "Maths")],
            )
            self.assertEqual(preview_practice(body, profile())["question_count"], 2)
            self.assertEqual(service.tables["practice_sessions"], [])

            started = start_practice(body, profile())
            session_id = started["session_id"]
            self.assertEqual(len(started["questions"]), 2)
            self.assertNotIn("correct_answer", started["questions"][0])

            autosave_practice(
                session_id, AutosavePractice(answers={"q1": "A"}), profile()
            )
            restored = get_practice(session_id, profile())
            self.assertEqual(restored["autosave_state"], {"q1": "A"})

            result = submit_practice(
                session_id,
                SubmitPractice(
                    answers=[
                        PracticeSubmittedAnswer(question_id="q1", student_answer="A"),
                        PracticeSubmittedAnswer(question_id="q2", student_answer=2),
                    ]
                ),
                profile(),
            )
            self.assertEqual(result["total_score"], 3.0)
            self.assertEqual([row["is_correct"] for row in result["results"]], [True, True])
            history = student_attempts(profile())
            self.assertEqual(history[0]["attempt_id"], session_id)
            self.assertIsNone(history[0]["subject_id"])
            self.assertEqual(history[0]["source"], "practice")

    def test_revised_topic_returns_after_new_weak_work(self) -> None:
        service = MutableService(
            {
                "quiz_attempts": [],
                "attempt_answers": [],
                "practice_sessions": [
                    {"id": "p1", "tenant_id": "t1", "student_id": "u1", "status": "graded"}
                ],
                "practice_answers": [
                    {"session_id": "p1", "tenant_id": "t1", "question_id": "q1", "is_correct": False}
                ],
                "questions": [{"id": "q1", "tenant_id": "t1", "chapter_id": "ch1", "topic_id": "tp1"}],
                "chapters": [{"id": "ch1", "tenant_id": "t1", "subject_id": "s1", "name": "Numbers"}],
                "subjects": [{"id": "s1", "tenant_id": "t1", "name": "Maths"}],
                "topics": [{"id": "tp1", "tenant_id": "t1", "name": "Addition"}],
                "revised_topics": [],
            }
        )
        with patch("app.api.student.get_service_client", return_value=service):
            first = revision_topics(profile())
            self.assertEqual(first[0]["key"], "topic:tp1")
            mark_topic_revised(RevisedTopic(key=first[0]["key"]), profile())
            self.assertEqual(revision_topics(profile()), [])

            service.tables["practice_sessions"].append(
                {"id": "p2", "tenant_id": "t1", "student_id": "u1", "status": "graded"}
            )
            service.tables["practice_answers"].append(
                {"session_id": "p2", "tenant_id": "t1", "question_id": "q1", "is_correct": False}
            )
            refreshed = revision_topics(profile())
            self.assertEqual(refreshed[0]["answered"], 2)


class DailyAndExamFlowTests(unittest.TestCase):
    @staticmethod
    def _questions(count: int) -> list[dict]:
        return [
            {
                "id": f"q{i}",
                "tenant_id": "t1",
                "review_status": "approved",
                "type": "mcq_single",
                "question_text": f"Question {i}",
                "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
                "correct_answer": "A",
                "explanation": "A is correct",
                "marks": 1,
            }
            for i in range(1, count + 1)
        ]

    def test_daily_full_lifecycle_is_exactly_ten_and_updates_streak(self) -> None:
        questions = self._questions(10)
        ids = [q["id"] for q in questions]
        service = MutableService(
            {
                "practice_sessions": [],
                "practice_answers": [],
                "questions": questions,
            }
        )
        fixed_day = date(2026, 9, 10)
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.practice.select_question_ids", return_value=ids),
            patch("app.api.practice._daily_today", return_value=fixed_day),
        ):
            started = start_daily(profile())
            self.assertEqual(len(started["questions"]), 10)
            self.assertNotIn("correct_answer", started["questions"][0])
            self.assertEqual(started["time_limit_minutes"], 10.0)
            self.assertIsNotNone(started["deadline_at"])
            session_id = started["session_id"]

            autosave_practice(
                session_id, AutosavePractice(answers={"q1": "A"}), profile()
            )
            resumed = start_daily(profile())
            self.assertEqual(resumed["session_id"], session_id)
            self.assertEqual(resumed["autosave_state"], {"q1": "A"})

            result = submit_practice(
                session_id,
                SubmitPractice(
                    answers=[
                        PracticeSubmittedAnswer(
                            question_id=question_id, student_answer="A"
                        )
                        for question_id in ids
                    ]
                ),
                profile(),
            )
            self.assertEqual(result["total_score"], 10)
            daily = get_daily(profile())
            self.assertTrue(daily["done_today"])
            self.assertTrue(daily["attempted_today"])
            self.assertEqual(daily["streak"], 1)
            with self.assertRaises(HTTPException) as caught:
                start_daily(profile())
            self.assertEqual(caught.exception.status_code, 400)

    def test_abandoned_daily_consumes_today_without_extending_streak(self) -> None:
        questions = self._questions(10)
        ids = [q["id"] for q in questions]
        service = MutableService(
            {
                "practice_sessions": [],
                "practice_answers": [],
                "questions": questions,
            }
        )
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.practice.select_question_ids", return_value=ids),
            patch("app.api.practice._daily_today", return_value=date(2026, 9, 10)),
        ):
            session_id = start_daily(profile())["session_id"]
            result = submit_practice(
                session_id,
                SubmitPractice(
                    answers=[
                        PracticeSubmittedAnswer(question_id="q1", student_answer="A")
                    ],
                    finalize_reason="left",
                ),
                profile(),
            )
            self.assertEqual(result["total_score"], 1)
            daily = get_daily(profile())
            self.assertFalse(daily["done_today"])
            self.assertTrue(daily["attempted_today"])
            self.assertEqual(daily["streak"], 0)
            with self.assertRaises(HTTPException):
                start_daily(profile())

    def test_daily_and_exam_refuse_partial_question_sets(self) -> None:
        service = MutableService(
            {
                "practice_sessions": [],
                "questions": self._questions(1),
                "tenants": [
                    {
                        "id": "t1",
                        "exam_config": {
                            "questions": 2,
                            "duration_minutes": 30,
                            "negative_marking": 0.25,
                        },
                    }
                ],
            }
        )
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.practice.select_question_ids", return_value=["q1"]),
            patch("app.api.practice._daily_today", return_value=date(2026, 9, 10)),
        ):
            with self.assertRaises(HTTPException) as daily_error:
                start_daily(profile())
            self.assertIn("10 approved questions", daily_error.exception.detail)
            with self.assertRaises(HTTPException) as exam_error:
                start_exam(profile())
            self.assertIn("requires 2 approved questions", exam_error.exception.detail)
        self.assertEqual(service.tables["practice_sessions"], [])

    def test_exam_resumes_one_active_session_and_grades_deterministically(self) -> None:
        questions = self._questions(2)
        ids = [q["id"] for q in questions]
        service = MutableService(
            {
                "practice_sessions": [],
                "practice_answers": [],
                "questions": questions,
                "tenants": [
                    {
                        "id": "t1",
                        "exam_config": {
                            "questions": 2,
                            "duration_minutes": 30,
                            "negative_marking": 0.25,
                        },
                    }
                ],
            }
        )
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.practice.select_question_ids", return_value=ids),
        ):
            self.assertIsNone(exam_config(profile())["active_session_id"])
            started = start_exam(profile())
            session_id = started["session_id"]
            self.assertEqual(len(started["questions"]), 2)
            self.assertIsNotNone(started["deadline_at"])
            self.assertEqual(start_exam(profile())["session_id"], session_id)
            self.assertEqual(exam_config(profile())["active_session_id"], session_id)

            result = submit_practice(
                session_id,
                SubmitPractice(
                    answers=[
                        PracticeSubmittedAnswer(question_id="q1", student_answer="A"),
                        PracticeSubmittedAnswer(question_id="q2", student_answer="B"),
                    ]
                ),
                profile(),
            )
            self.assertEqual(result["total_score"], 0.75)
            self.assertIsNone(exam_config(profile())["active_session_id"])

    def test_daily_date_uses_configured_calendar_timezone(self) -> None:
        settings = SimpleNamespace(daily_challenge_timezone="Asia/Kolkata")
        with patch("app.api.practice.get_settings", return_value=settings):
            self.assertEqual(
                _daily_today(datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)),
                date(2026, 9, 10),
            )


class StudentBoundaryTests(unittest.TestCase):
    def test_question_level_access_recognizes_both_quiz_engines(self) -> None:
        service = MemoryService(
            {
                "attempt_answers": [
                    {"tenant_id": "t1", "attempt_id": "other", "question_id": "q1"}
                ],
                "quiz_attempts": [
                    {
                        "id": "other",
                        "tenant_id": "t1",
                        "student_id": "u2",
                        "status": "graded",
                    }
                ],
                "practice_answers": [
                    {"tenant_id": "t1", "session_id": "mine", "question_id": "q2"}
                ],
                "practice_sessions": [
                    {
                        "id": "mine",
                        "tenant_id": "t1",
                        "student_id": "u1",
                        "status": "graded",
                    }
                ],
            }
        )
        self.assertFalse(student_has_graded_question(service, "q1", profile()))
        self.assertTrue(student_has_graded_question(service, "q2", profile()))

    def test_daily_streak_counts_current_and_longest_runs(self) -> None:
        completed = {
            "2026-09-01",
            "2026-09-02",
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
        }
        self.assertEqual(_streak(completed, date(2026, 9, 10)), (3, 3))

    def test_challenge_token_is_tenant_scoped(self) -> None:
        same_tenant = MemoryService(
            {"challenges": [{"share_token": "token", "tenant_id": "t1"}]}
        )
        self.assertEqual(
            _load_challenge(same_tenant, "token", profile())["tenant_id"], "t1"
        )

        other_tenant = MemoryService(
            {"challenges": [{"share_token": "token", "tenant_id": "t2"}]}
        )
        with self.assertRaises(HTTPException) as caught:
            _load_challenge(other_tenant, "token", profile())
        self.assertEqual(caught.exception.status_code, 404)

    def test_student_endpoints_reject_staff_roles(self) -> None:
        for guard in (
            require_quiz_student,
            require_practice_student,
            require_challenge_student,
        ):
            guard(profile())
            for role in ("teacher", "institution_admin", "super_admin"):
                with self.subTest(guard=guard.__module__, role=role):
                    with self.assertRaises(HTTPException) as caught:
                        guard(profile(role))
                    self.assertEqual(caught.exception.status_code, 403)

    def test_generic_practice_cannot_bypass_special_mode_rules(self) -> None:
        for mode in ("daily", "exam", "challenge"):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                StartPractice(mode=mode)

    def test_expired_exam_cannot_be_autosaved(self) -> None:
        expired = {
            "id": "p1",
            "status": "in_progress",
            "mode": "exam",
            "started_at": "2020-01-01T00:00:00Z",
            "config": {"duration_minutes": 1},
            "question_ids": ["q1"],
        }
        with (
            patch("app.api.practice.get_service_client", return_value=object()),
            patch("app.api.practice._load_session", return_value=expired),
            self.assertRaises(HTTPException) as caught,
        ):
            autosave_practice("p1", AutosavePractice(answers={"q1": "A"}), profile())
        self.assertEqual(caught.exception.status_code, 400)

    def test_practice_requires_every_question_before_early_submit(self) -> None:
        service = MutableService(
            {
                "practice_sessions": [
                    {
                        "id": "p1",
                        "tenant_id": "t1",
                        "student_id": "u1",
                        "status": "in_progress",
                        "mode": "smart",
                        "config": {},
                        "question_ids": ["q1", "q2"],
                    }
                ],
                "questions": [
                    {
                        "id": "q1",
                        "tenant_id": "t1",
                        "type": "mcq_single",
                        "question_text": "One",
                        "options": [],
                        "correct_answer": "A",
                        "explanation": None,
                        "marks": 1,
                    },
                    {
                        "id": "q2",
                        "tenant_id": "t1",
                        "type": "mcq_single",
                        "question_text": "Two",
                        "options": [],
                        "correct_answer": "B",
                        "explanation": None,
                        "marks": 1,
                    },
                ],
            }
        )
        with (
            patch("app.api.practice.get_service_client", return_value=service),
            self.assertRaises(HTTPException) as caught,
        ):
            submit_practice(
                "p1",
                SubmitPractice(
                    answers=[
                        PracticeSubmittedAnswer(
                            question_id="q1", student_answer="A"
                        )
                    ]
                ),
                profile(),
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("every question", caught.exception.detail.lower())

    def test_question_level_access_requires_the_students_graded_work(self) -> None:
        service = MemoryService(
            {
                "attempt_answers": [
                    {"tenant_id": "t1", "attempt_id": "a1", "question_id": "q1"},
                    {"tenant_id": "t1", "attempt_id": "a2", "question_id": "q2"},
                ],
                "quiz_attempts": [
                    {"id": "a1", "tenant_id": "t1", "student_id": "u1", "status": "graded"},
                    {"id": "a2", "tenant_id": "t1", "student_id": "u2", "status": "graded"},
                ],
            }
        )
        self.assertTrue(student_has_graded_question(service, "q1", profile()))
        self.assertFalse(student_has_graded_question(service, "q2", profile()))


if __name__ == "__main__":
    unittest.main()
