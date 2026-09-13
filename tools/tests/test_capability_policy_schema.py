"""Closed policy examples and independent WIT/operation contract parity."""
import copy
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("capability-policy", "capability-provider-binding", "capability-policy-resource", "capability-policy-config")
SCHEMAS = {name: json.loads((ROOT / "schemas" / (name + ".schema.json")).read_text(encoding="utf-8")) for name in NAMES}
REGISTRY = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values())


class CapabilityPolicySchemaTests(unittest.TestCase):
    def validator(self, name):
        schema = SCHEMAS[name]
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, registry=REGISTRY)

    def test_published_examples_and_closed_required_fields(self):
        guide = (ROOT / "docs/runtime/capability-policies.md").read_text(encoding="utf-8")
        examples = [json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", guide, re.S)]
        self.assertEqual(len(examples), len(NAMES))
        for name, example in zip(NAMES, examples):
            validator = self.validator(name)
            validator.validate(example)
            self.assertFalse(validator.is_valid(dict(example, unexpected=True)))
            for key in example:
                self.assertFalse(validator.is_valid(dict(example, **{key: None})), (name, key))

    def test_capability_operation_and_resource_kinds_cannot_be_mixed(self):
        validator = self.validator("capability-policy")
        rule = {"id": "allow", "effect": "allow", "principals": [{"kind": "user", "subject": "alice"}],
                "services": ["echo"], "publications": ["publication:sha256:" + "1" * 64],
                "capability": "latent:secrets/reader@0.1.0", "operations": ["read"],
                "resources": {"kind": "secrets", "references": ["test-key"]},
                "ceiling": {"operations": 1, "inputBytes": 0, "outputBytes": 128, "wallTimeMillis": 100}}
        good = {"formatVersion": 1, "tenant": "a", "rules": [rule]}
        validator.validate(good)
        for change in ({"operations": ["send"]}, {"operations": ["read", "read"]},
                       {"capability": "latent:secrets/reader@0.2.0"}, {"resources": {"kind": "random"}},
                       {"ceiling": {**rule["ceiling"], "outputBytes": 67108865}}):
            self.assertFalse(validator.is_valid({**good, "rules": [{**rule, **change}]}))
        for key in ("principals", "services", "publications", "operations"):
            empty = copy.deepcopy(good)
            empty["rules"][0][key] = []
            validator.validate(empty)  # Legal data; evaluator tests prove default deny.

    def test_policy_operation_table_matches_each_frozen_wit_interface(self):
        matrix = json.loads((ROOT / "wit/host-abi-phase3-v2.json").read_text(encoding="utf-8"))
        rust = (ROOT / "crates/latent-policy/src/capability.rs").read_text(encoding="utf-8")
        actual = {cap: set(re.findall(r'"([a-z0-9-]+)"', operations))
                  for cap, operations in re.findall(r'"(latent:[^\"]+)"\s*=>\s*&\[(.*?)\]', rust, re.S)}
        expected = {}
        for entry in matrix["interfaces"]:
            interface = entry["interface"].split("/")[1].split("@")[0]
            text = (ROOT / entry["source"]).read_text(encoding="utf-8")
            active = False
            depth = 0
            operations = set()
            for raw in text.splitlines():
                line = raw.split("//", 1)[0]
                if not active:
                    if re.match(r"\s*interface\s+" + re.escape(interface) + r"\s*\{", line):
                        active = True
                        depth = 1
                    continue
                if depth == 1:
                    function = re.match(r"\s*([a-z0-9-]+):\s*(?:async\s+)?func\b", line)
                    if function:
                        operations.add(function[1])
                depth += line.count("{") - line.count("}")
                if depth == 0:
                    break
            self.assertTrue(operations, entry["interface"])
            expected[entry["interface"]] = operations
        self.assertEqual(actual, expected)
        constraints = SCHEMAS["capability-policy"]["$defs"]["rule"]["allOf"]
        self.assertEqual({v["if"]["properties"]["capability"]["const"]:
                          set(v["then"]["properties"]["operations"]["items"]["enum"]) for v in constraints}, expected)


if __name__ == "__main__":
    unittest.main()
