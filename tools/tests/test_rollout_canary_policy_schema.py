"""Closed explicit canary thresholds and the published example."""
import json
from pathlib import Path
import re
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/rollout-canary-policy.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
POLICY = {"formatVersion": 1, "observationMillis": 1, "minimumCandidateSamples": 1,
          "maximumFailureBasisPoints": 0, "latencyThresholdMicros": 100,
          "maximumSlowBasisPoints": 0}


class CanaryPolicySchema(unittest.TestCase):
    def test_all_declarations_required_and_closed(self):
        VALIDATOR.check_schema(SCHEMA)
        VALIDATOR.validate(POLICY)
        for key in POLICY:
            missing = dict(POLICY)
            del missing[key]
            self.assertFalse(VALIDATOR.is_valid(missing), key)
            self.assertFalse(VALIDATOR.is_valid({**POLICY, key: None}), key)
        self.assertFalse(VALIDATOR.is_valid({**POLICY, "healthy": True}))

    def test_boundaries_and_fixed_latency_resolution(self):
        for key, maximum in (("observationMillis", 3_600_000), ("minimumCandidateSamples", 1_000_000),
                             ("maximumFailureBasisPoints", 9999), ("maximumSlowBasisPoints", 10_000)):
            VALIDATOR.validate({**POLICY, key: maximum})
            self.assertFalse(VALIDATOR.is_valid({**POLICY, key: maximum + 1}))
            self.assertFalse(VALIDATOR.is_valid({**POLICY, key: True}))
        for edge in SCHEMA["properties"]["latencyThresholdMicros"]["enum"]:
            VALIDATOR.validate({**POLICY, "latencyThresholdMicros": edge})
            self.assertFalse(VALIDATOR.is_valid({**POLICY, "latencyThresholdMicros": edge + 1}))

    def test_operator_declaration(self):
        guide = (ROOT / "docs/reference/management-services.md").read_text(encoding="utf-8")
        policies = [json.loads(text) for text in re.findall(r"```json\n(.*?)\n```", guide, re.S)
                    if "minimumCandidateSamples" in text]
        self.assertEqual(len(policies), 1)
        VALIDATOR.validate(policies[0])


if __name__ == "__main__":
    unittest.main()
