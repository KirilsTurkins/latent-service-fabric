"""Closed manual rollout node settings and the published operator example."""
import json
from pathlib import Path
import re
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-rollouts.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


class NodeRolloutsSchema(unittest.TestCase):
    def test_closed_manual_profile(self):
        VALIDATOR.check_schema(SCHEMA)
        VALIDATOR.validate({"mode": "manual"})
        for value in (None, {}, [], {"mode": "automatic"}, {"mode": "manual", "healthy": True}):
            self.assertFalse(VALIDATOR.is_valid(value), value)

    def test_individual_bounds(self):
        for name, field in SCHEMA["properties"].items():
            if name == "mode":
                continue
            for value in (field["minimum"], field["default"], field["maximum"]):
                VALIDATOR.validate({"mode": "manual", name: value})
            for value in (field["minimum"] - 1, field["maximum"] + 1, None, True, 1.5):
                self.assertFalse(VALIDATOR.is_valid({"mode": "manual", name: value}), (name, value))

    def test_operator_example(self):
        guide = (ROOT / "docs/reference/standalone-node.md").read_text(encoding="utf-8")
        examples = [json.loads(text)["rollouts"] for text in re.findall(r"```json\n(.*?)\n```", guide, re.S)
                    if "rollouts" in json.loads(text)]
        self.assertEqual(len(examples), 1)
        VALIDATOR.validate(examples[0])
        for name, field in SCHEMA["properties"].items():
            if "default" in field:
                self.assertEqual(examples[0][name], field["default"])


if __name__ == "__main__":
    unittest.main()
