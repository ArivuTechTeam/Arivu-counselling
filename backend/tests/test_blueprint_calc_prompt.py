from __future__ import annotations

import unittest

from app.services.blueprint_prompts import build_blueprint_system_prompt
from app.services.numeric_checks import FAMILY_INPUT_KEYS

TYPES = ["mcq_single", "numerical"]


class CommerceCalcPromptTests(unittest.TestCase):
    def test_prompt_byte_identical_when_disabled(self):
        # The default (flag off) must not differ from an explicit disable, and must
        # never mention the optional calc contract.
        default = build_blueprint_system_prompt(TYPES, "mixed", "medium")
        explicit_off = build_blueprint_system_prompt(
            TYPES, "mixed", "medium", commerce_calc_enabled=False
        )
        self.assertEqual(default, explicit_off)
        self.assertNotIn("calc", default)
        self.assertNotIn("OPTIONAL NUMERIC CHECK", default)

    def test_enabled_prompt_extends_disabled_prompt(self):
        off = build_blueprint_system_prompt(TYPES, "mixed", "medium")
        on = build_blueprint_system_prompt(
            TYPES, "mixed", "medium", commerce_calc_enabled=True
        )
        # Adding the calc rule only appends — the base instructions are untouched.
        self.assertIn(off.replace("Return the JSON object now — JSON only.", ""), on)
        self.assertIn("OPTIONAL NUMERIC CHECK", on)

    def test_enabled_prompt_lists_every_supported_family_and_keys(self):
        on = build_blueprint_system_prompt(
            TYPES, "mixed", "medium", commerce_calc_enabled=True
        )
        for family, keys in FAMILY_INPUT_KEYS.items():
            self.assertIn(family, on)
            for key in keys:
                self.assertIn(key, on)


if __name__ == "__main__":
    unittest.main()
