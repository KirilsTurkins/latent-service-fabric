"""Parity checks for the standalone node's optional durable audit member."""
import json
from pathlib import Path
import re
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-audit.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


class NodeAuditSchema(unittest.TestCase):
    def test_closed_required_mode(self):
        VALIDATOR.check_schema(SCHEMA)
        VALIDATOR.validate({"mode": "durable"})
        for value in (None, {}, [], True, {"mode": "memory"},
                      {"mode": "durable", "path": "other"},
                      {"mode": "durable", "enabled": False}):
            self.assertFalse(VALIDATOR.is_valid(value), value)

    def test_each_count_and_byte_boundary(self):
        for name, field in SCHEMA["properties"].items():
            if name == "mode":
                continue
            for value in (field["minimum"], field["default"], field["maximum"]):
                VALIDATOR.validate({"mode": "durable", name: value})
            for value in (field["minimum"] - 1, field["maximum"] + 1, None, True, 1.5):
                self.assertFalse(VALIDATOR.is_valid({"mode": "durable", name: value}), (name, value))

    def test_published_operator_example(self):
        guide = (ROOT / "docs/reference/standalone-node.md").read_text(encoding="utf-8")
        members = []
        for snippet in re.findall(r"```json\n(.*?)\n```", guide, re.S):
            value = json.loads(snippet)
            if "audit" in value:
                members.append(value["audit"])
        self.assertEqual(len(members), 1)
        VALIDATOR.validate(members[0])
        for name, field in SCHEMA["properties"].items():
            if "default" in field:
                self.assertEqual(members[0][name], field["default"])


if __name__ == "__main__":
    unittest.main()
