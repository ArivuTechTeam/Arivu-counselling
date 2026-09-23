from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.practice import PracticeResultOut, PracticeSessionOut


def test_practice_session_response_accepts_timed_attempt_shape() -> None:
    now = datetime.now(timezone.utc)
    response = PracticeSessionOut.model_validate(
        {
            "session_id": "session-1",
            "attempt_id": "session-1",
            "status": "in_progress",
            "questions": [
                {
                    "id": "question-1",
                    "type": "mcq",
                    "question_text": "What is 2 + 2?",
                    "options": ["3", "4"],
                    "marks": 1,
                    "suggested_seconds": 30,
                }
            ],
            "autosave_state": {},
            "time_limit_minutes": 1,
            "started_at": now.isoformat(),
            "deadline_at": now,
            "remaining_seconds": 60,
        }
    )

    assert response.status == "in_progress"
    assert response.questions[0].suggested_seconds == 30


def test_practice_result_response_accepts_graded_attempt_shape() -> None:
    response = PracticeResultOut.model_validate(
        {
            "attempt_id": "session-1",
            "status": "graded",
            "quiz_title": "Smart practice",
            "total_score": 1,
            "max_score": 1,
            "challenge_token": None,
            "results": [
                {
                    "id": "question-1",
                    "type": "mcq",
                    "question_text": "What is 2 + 2?",
                    "options": ["3", "4"],
                    "correct_answer": "4",
                    "student_answer": "4",
                    "is_correct": True,
                    "marks": 1,
                    "marks_awarded": 1,
                }
            ],
        }
    )

    assert response.status == "graded"
    assert response.results[0].is_correct is True


def test_practice_responses_reject_undocumented_fields() -> None:
    with pytest.raises(ValidationError):
        PracticeSessionOut.model_validate(
            {
                "attempt_id": "session-1",
                "status": "in_progress",
                "questions": [],
                "autosave_state": {},
                "internal_answer": "must not leak",
            }
        )
