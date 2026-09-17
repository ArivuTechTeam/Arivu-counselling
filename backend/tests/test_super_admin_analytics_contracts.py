from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError

from app.api.admin import QuestionBankResponse


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "migration-36-super-admin-aggregates.sql"


class SuperAdminAnalyticsMigrationTests(unittest.TestCase):
    def test_migration_defines_service_role_only_invoker_functions(self) -> None:
        sql = MIGRATION.read_text().lower()
        for function in (
            "platform_overview_metrics",
            "platform_question_bank_metrics",
            "platform_ai_monitoring_metrics",
        ):
            self.assertIn(f"function public.{function}()", sql)
            self.assertIn(f"grant execute on function public.{function}() to service_role", sql)
        self.assertEqual(sql.count("security invoker"), 3)
        self.assertNotIn("security definer", sql)
        self.assertIn("from public, anon, authenticated", sql)

    def test_question_bank_contract_requires_review_status_breakdown(self) -> None:
        valid = {
            "total": 2,
            "uncategorised": 0,
            "courses": [
                {
                    "course": "Science",
                    "tenant": "Demo",
                    "questions": 2,
                    "subjects": 1,
                    "chapters": 1,
                    "difficulty": {"medium": 2},
                    "types": {"mcq_single": 2},
                    "review_status": {
                        "pending_review": 1,
                        "approved": 1,
                        "rejected": 0,
                        "needs_edit": 0,
                    },
                }
            ],
        }
        QuestionBankResponse.model_validate(valid)
        del valid["courses"][0]["review_status"]
        with self.assertRaises(ValidationError):
            QuestionBankResponse.model_validate(valid)


if __name__ == "__main__":
    unittest.main()
