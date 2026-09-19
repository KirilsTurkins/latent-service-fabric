"""Validate only the installed provider configuration, never inferred profiles."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

import jsonschema

from tools.phase2_operator_process import write_json
from tools.phase3_management_scenario import configure_provider_node

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-providers.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


class NodeProvidersSchema(unittest.TestCase):
    def example(self):
        guide = (ROOT / "docs/reference/standalone-providers.md").read_text(encoding="utf-8")
        return json.loads(re.findall(r"```json\n(.*?)\n```", guide, re.S)[0])["providers"]

    def test_documented_blob_and_shared_real_workflow_http_configuration(self):
        VALIDATOR.check_schema(SCHEMA)
        VALIDATOR.validate(self.example())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, node = root / "fixture", root / "node"
            fixture.mkdir()
            node.mkdir()
            write_json(fixture / "policy.json", {"formatVersion": 1})
            config = json.loads(configure_provider_node(node, fixture, 32123).read_bytes())
            VALIDATOR.validate(config["providers"])
            for field, value in (("credentials", []), ("credentialDirectory", None),
                                 ("profile", "streaming-http-v1"), ("authorization", "PRIVATE")):
                invalid = copy.deepcopy(config["providers"])
                invalid["http"][field] = value
                self.assertFalse(VALIDATOR.is_valid(invalid), field)

    def test_null_unknown_future_profiles_and_path_escape_are_rejected(self):
        valid = self.example()
        for value in (None, {}, dict(valid, extra=True), dict(valid, http=None),
                      dict(valid, blob=None), dict(valid, formatVersion=2), dict(valid, bindings=[]),
                      dict(valid, bindings=valid["bindings"] * 17)):
            self.assertFalse(VALIDATOR.is_valid(value))
        for field, value in (("id", "../escape"), ("id", ".."), ("epoch", 0), ("epoch", True),
                             ("epoch", 18446744073709551616), ("tenant", ""), ("token", "PRIVATE")):
            invalid = copy.deepcopy(valid)
            invalid["blob"]["identity"][field] = value
            self.assertFalse(VALIDATOR.is_valid(invalid), field)
        invalid = copy.deepcopy(valid)
        invalid["bindings"][0]["contract"] = "latent:http/streaming-client@0.1.0"
        self.assertFalse(VALIDATOR.is_valid(invalid))


if __name__ == "__main__":
    unittest.main()
