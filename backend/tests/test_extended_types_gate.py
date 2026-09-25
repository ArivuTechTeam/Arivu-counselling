"""Phase 6.4: the extended types are selectable only when the flag is on."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api import quiz


class AllowedTypesGateTests(unittest.TestCase):
    def _allowed(self, enabled):
        with patch.object(
            quiz, "get_settings",
            return_value=SimpleNamespace(extended_question_types_enabled=enabled),
        ):
            return quiz.allowed_question_types()

    def test_flag_off_is_exactly_core_types(self):
        self.assertEqual(self._allowed(False), quiz.CORE_TYPES)
        for t in ("assertion_reason", "mrm", "matching"):
            self.assertNotIn(t, self._allowed(False))

    def test_flag_on_adds_extended_types(self):
        allowed = self._allowed(True)
        self.assertEqual(allowed, quiz.CORE_TYPES | quiz.EXTENDED_TYPES)
        for t in ("assertion_reason", "mrm", "matching"):
            self.assertIn(t, allowed)


if __name__ == "__main__":
    unittest.main()
