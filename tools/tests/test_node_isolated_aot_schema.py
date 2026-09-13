"""Small parity checks for the optional isolatedAot operator member."""
import copy
import json
from pathlib import Path
import re
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-isolated-aot.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def example():
    return {
        "compilerExecutable": "/opt/lsf/bin/latent-aot-compiler",
        "compilerDigest": "sha256:" + "ab" * 32,
        "keyFile": "/etc/lsf/private/native-aot.key",
        "blobRoot": "/var/cache/lsf/native-blobs",
        "receiptRoot": "/var/cache/lsf/native-receipts",
    }


class NodeIsolatedAotSchema(unittest.TestCase):
    def test_schema_and_closed_minimum(self):
        VALIDATOR.check_schema(SCHEMA)
        self.assertTrue(VALIDATOR.is_valid(example()))
        for name in example():
            value = example()
            del value[name]
            self.assertFalse(VALIDATOR.is_valid(value), name)
        for value in (None, {}, [], True):
            self.assertFalse(VALIDATOR.is_valid(value))

    def test_unknown_null_and_secret_fields(self):
        for name, value in (("keyBytes", [0] * 32), ("compilerIdentity", "other"),
                            ("process", None), ("cache", {"extra": 1}),
                            ("images", {"maximumImages": 1.5})):
            member = example()
            member[name] = value
            self.assertFalse(VALIDATOR.is_valid(member), name)

    def test_exact_digest_and_paths(self):
        for name, value in (("compilerDigest", "sha256:" + "AB" * 32),
                            ("compilerDigest", example()["compilerDigest"] + "\n"),
                            ("compilerExecutable", "compiler"),
                            ("keyFile", ""), ("keyFile", "x" * 4097),
                            ("blobRoot", "cache\n")):
            member = example()
            member[name] = value
            self.assertFalse(VALIDATOR.is_valid(member), (name, value[:80]))
        value = example()
        value["keyFile"] = "private/key"
        value["blobRoot"] = "future/blobs"
        self.assertTrue(VALIDATOR.is_valid(value))

    def test_every_numeric_ceiling(self):
        for group in ("process", "cache", "images"):
            for name, field in SCHEMA["properties"][group]["properties"].items():
                for boundary in (field["minimum"], field["maximum"]):
                    member = example()
                    member[group] = {name: boundary}
                    self.assertTrue(VALIDATOR.is_valid(member), (group, name, boundary))
                for invalid in (field["minimum"] - 1, field["maximum"] + 1, None, True):
                    member = example()
                    member[group] = {name: invalid}
                    self.assertFalse(VALIDATOR.is_valid(member), (group, name, invalid))

    def test_published_operator_example_matches_closed_member(self):
        guide = (ROOT / "docs/reference/standalone-node.md").read_text(encoding="utf-8")
        members = []
        for snippet in re.findall(r"```json\n(.*?)\n```", guide, re.S):
            value = json.loads(snippet)
            if "isolatedAot" in value:
                members.append(copy.deepcopy(value["isolatedAot"]))
        self.assertEqual(len(members), 1)
        # The guide explicitly labels this as a replacement approval placeholder.
        members[0]["compilerDigest"] = example()["compilerDigest"]
        VALIDATOR.validate(members[0])


if __name__ == "__main__":
    unittest.main()
