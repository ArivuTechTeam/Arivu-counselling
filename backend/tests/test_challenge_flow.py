from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.challenge import (
    CreateChallenge,
    JoinChallenge,
    accept_challenge,
    close_challenge,
    create_challenge,
    get_challenge,
    join_challenge,
    my_challenges,
)
from app.api.practice import SubmitPractice, SubmittedAnswer, get_practice, submit_practice
from app.lib.auth import CurrentProfile
from tests.test_student_experience import MutableService


def student(user_id: str, tenant_id: str = "t1") -> CurrentProfile:
    return CurrentProfile(user_id=user_id, tenant_id=tenant_id, role="student")


class ChallengeService(MutableService):
    pass


def challenge_tables() -> dict[str, list[dict]]:
    questions = [
        {
            "id": f"q{i}",
            "tenant_id": "t1",
            "chapter_id": "chapter-1",
            "review_status": "approved",
            "type": "mcq_single",
            "question_text": f"Original question {i}",
            "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
            "correct_answer": "A",
            "explanation": "A is correct",
            "marks": 1,
        }
        for i in range(1, 6)
    ]
    return {
        "profiles": [
            {"id": "u1", "tenant_id": "t1", "full_name": "Creator"},
            {"id": "u2", "tenant_id": "t1", "full_name": "Friend"},
            {"id": "u3", "tenant_id": "t1", "full_name": "Other Course"},
            {"id": "u4", "tenant_id": "t1", "full_name": "Late Friend"},
        ],
        "enrollments": [
            {"tenant_id": "t1", "profile_id": "u1", "course_id": "course-1"},
            {"tenant_id": "t1", "profile_id": "u2", "course_id": "course-1"},
            {"tenant_id": "t1", "profile_id": "u3", "course_id": "course-2"},
            {"tenant_id": "t1", "profile_id": "u4", "course_id": "course-1"},
        ],
        "subjects": [
            {"id": "subject-1", "tenant_id": "t1", "course_id": "course-1", "name": "Maths"},
            {"id": "subject-2", "tenant_id": "t1", "course_id": "course-2", "name": "Law"},
        ],
        "chapters": [
            {"id": "chapter-1", "tenant_id": "t1", "subject_id": "subject-1"}
        ],
        "questions": questions,
        "challenges": [],
        "practice_sessions": [],
        "practice_answers": [],
    }


class ChallengeFlowTests(unittest.TestCase):
    def test_creator_friend_snapshot_grading_leaderboard_and_close(self) -> None:
        service = ChallengeService(challenge_tables())
        settings = SimpleNamespace(
            challenge_expiry_days=30,
            rate_limit_challenge_join_per_hour=30,
        )
        with (
            patch("app.api.challenge.get_service_client", return_value=service),
            patch("app.api.practice.get_service_client", return_value=service),
            patch("app.api.challenge.get_settings", return_value=settings),
        ):
            created = create_challenge(
                CreateChallenge(
                    subject_id="subject-1", type_counts={"mcq_single": 5}
                ),
                student("u1"),
            )
            token = created["token"]
            self.assertEqual(created["questions"], 5)
            self.assertEqual(created["duration_minutes"], 5)
            self.assertEqual(created["type_counts"], {"mcq_single": 5})
            self.assertRegex(created["join_code"], r"^[2-9A-HJ-NP-Z]{8}$")
            self.assertEqual(service.tables["practice_sessions"], [])

            with patch("app.api.challenge.enforce_rate_limit") as limiter:
                joined = join_challenge(
                    JoinChallenge(
                        code=(
                            f"{created['join_code'][:4]}-"
                            f"{created['join_code'][4:]}"
                        )
                    ),
                    student("u2"),
                )
            self.assertEqual(joined["token"], token)
            limiter.assert_called_once()

            lobby = get_challenge(token, student("u1"))
            self.assertEqual(lobby["my_status"], "not_taken")
            creator_started = accept_challenge(token, student("u1"))
            self.assertEqual(len(creator_started["questions"]), 5)
            self.assertNotIn("correct_answer", creator_started["questions"][0])

            # Editing the live bank after creation must not change this challenge.
            service.tables["questions"][0]["question_text"] = "Edited later"
            service.tables["questions"][0]["correct_answer"] = "B"
            restored = get_practice(creator_started["session_id"], student("u1"))
            restored_q1 = next(q for q in restored["questions"] if q["id"] == "q1")
            self.assertEqual(restored_q1["question_text"], "Original question 1")

            creator_result = submit_practice(
                creator_started["session_id"],
                SubmitPractice(
                    answers=[SubmittedAnswer(question_id=f"q{i}", student_answer="A") for i in range(1, 6)]
                ),
                student("u1"),
            )
            self.assertEqual(creator_result["total_score"], 5)
            self.assertEqual(creator_result["challenge_token"], token)

            hub = get_challenge(token, student("u2"))
            self.assertEqual(hub["subject_name"], "Maths")
            friend_started = accept_challenge(token, student("u2"))
            self.assertEqual(len(friend_started["questions"]), 5)
            self.assertNotIn("correct_answer", friend_started["questions"][0])
            friend_result = submit_practice(
                friend_started["session_id"],
                SubmitPractice(
                    answers=[SubmittedAnswer(question_id=f"q{i}", student_answer="A") for i in range(1, 6)]
                ),
                student("u2"),
            )
            self.assertEqual(friend_result["total_score"], 5)

            ranked = get_challenge(token, student("u2"))
            self.assertEqual([row["rank"] for row in ranked["leaderboard"]], [1, 2])
            self.assertTrue(all(row["pct"] == 100 for row in ranked["leaderboard"]))
            with self.assertRaises(HTTPException) as repeated:
                accept_challenge(token, student("u2"))
            self.assertEqual(repeated.exception.status_code, 400)

            with self.assertRaises(HTTPException) as wrong_course:
                get_challenge(token, student("u3"))
            self.assertEqual(wrong_course.exception.status_code, 403)

            with patch("app.api.challenge.enforce_rate_limit"):
                with self.assertRaises(HTTPException) as wrong_course_code:
                    join_challenge(
                        JoinChallenge(code=created["join_code"]),
                        student("u3"),
                    )
                with self.assertRaises(HTTPException) as wrong_tenant_code:
                    join_challenge(
                        JoinChallenge(code=created["join_code"]),
                        student("u2", tenant_id="t2"),
                    )
            self.assertEqual(wrong_course_code.exception.status_code, 403)
            self.assertEqual(wrong_tenant_code.exception.status_code, 404)

            listed = my_challenges(student("u1"))
            self.assertEqual(listed[0]["token"], token)
            self.assertEqual(listed[0]["players"], 2)
            close_challenge(token, student("u1"))
            with self.assertRaises(HTTPException) as closed:
                accept_challenge(token, student("u4"))
            self.assertEqual(closed.exception.status_code, 410)

    def test_requested_question_type_mix_is_frozen_exactly(self) -> None:
        tables = challenge_tables()
        requested_types = [
            "mcq_single",
            "mcq_single",
            "mcq_multi",
            "true_false",
            "numerical",
        ]
        for question, question_type in zip(tables["questions"], requested_types):
            question["type"] = question_type
        service = ChallengeService(tables)
        with (
            patch("app.api.challenge.get_service_client", return_value=service),
            patch(
                "app.api.challenge.get_settings",
                return_value=SimpleNamespace(challenge_expiry_days=30),
            ),
        ):
            created = create_challenge(
                CreateChallenge(
                    subject_id="subject-1",
                    type_counts={
                        "mcq_single": 2,
                        "mcq_multi": 1,
                        "true_false": 1,
                        "numerical": 1,
                        "fill_blank": 0,
                    },
                ),
                student("u1"),
            )
        self.assertEqual(
            created["type_counts"],
            {"mcq_single": 2, "mcq_multi": 1, "true_false": 1, "numerical": 1},
        )
        self.assertEqual(service.tables["practice_sessions"], [])

    def test_exact_custom_mix_and_allowed_values_are_enforced(self) -> None:
        tables = challenge_tables()
        tables["questions"] = tables["questions"][:2]
        service = ChallengeService(tables)
        with patch("app.api.challenge.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as short:
                create_challenge(
                    CreateChallenge(
                        subject_id="subject-1", type_counts={"mcq_single": 5}
                    ),
                    student("u1"),
                )
            self.assertEqual(short.exception.status_code, 400)
            self.assertIn("mcq single: 2 available", short.exception.detail)
        with self.assertRaises(ValidationError):
            CreateChallenge(subject_id="subject-1", count=101)
        with self.assertRaises(ValidationError):
            CreateChallenge(subject_id="subject-1", type_counts={"essay": 5})

    def test_expired_challenge_rejects_only_new_attempts(self) -> None:
        tables = challenge_tables()
        tables["challenges"] = [
            {
                "id": "c1",
                "tenant_id": "t1",
                "creator_id": "u1",
                "creator_name": "Creator",
                "subject_id": "subject-1",
                "course_ids": ["course-1"],
                "question_ids": [f"q{i}" for i in range(1, 6)],
                "question_snapshot": tables["questions"],
                "duration_minutes": 5,
                "share_token": "expired",
                "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "is_active": True,
            }
        ]
        service = ChallengeService(tables)
        with patch("app.api.challenge.get_service_client", return_value=service):
            creator_started = accept_challenge("expired", student("u1"))
            self.assertEqual(len(creator_started["questions"]), 5)
            with self.assertRaises(HTTPException) as expired:
                accept_challenge("expired", student("u2"))
            self.assertEqual(expired.exception.status_code, 410)
