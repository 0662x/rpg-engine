from __future__ import annotations

import json
import unittest
from pathlib import Path

from rpg_engine.capabilities import ACTION_CAPABILITIES, V1_CAPABILITIES, V1_CAPABILITY_SET, capability_for_action


ENGINE_ROOT = Path(__file__).resolve().parents[1]


class CapabilityContractTests(unittest.TestCase):
    def test_capabilities_schema_matches_runtime_source(self) -> None:
        schema = json.loads((ENGINE_ROOT / "schemas" / "capabilities.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(schema["items"]["enum"]), V1_CAPABILITIES)

    def test_action_capabilities_are_declared_or_explicitly_non_v1(self) -> None:
        for action, capability in ACTION_CAPABILITIES.items():
            with self.subTest(action=action):
                self.assertEqual(capability_for_action(action), capability)
                self.assertIn(capability, V1_CAPABILITY_SET)


if __name__ == "__main__":
    unittest.main()
