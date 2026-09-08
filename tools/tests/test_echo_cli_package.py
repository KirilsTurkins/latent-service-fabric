from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "echo_cli_package", ROOT / "tools" / "build_echo_capsule.py"
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def parsed_echo() -> dict:
    # The pinned wit-parser JSON uses integer type-arena references.
    return {
        "interfaces": [{"name": "api", "functions": {
            "echo": {"name": "echo", "kind": "freestanding",
                     "params": [{"name": "message", "type": "string"}], "result": 1}
        }}],
        "types": [
            {"name": "echo-error", "kind": {"variant": {"cases": [
                {"name": "empty-message", "type": None},
                {"name": "message-too-large", "type": None},
            ]}}},
            {"name": None, "kind": {"result": {"ok": "string", "err": 0}}},
        ],
    }


class EchoCliPackageTests(unittest.TestCase):
    def metadata(self) -> dict:
        return json.loads(builder.CONTRACT_METADATA.read_text(encoding="utf-8"))

    def test_maintained_descriptor_hashes_and_shape_match_parsed_wit(self) -> None:
        builder.validate_cli_contract_metadata(self.metadata(), parsed_echo())

    def test_signature_drift_is_rejected_before_cli_package_is_written(self) -> None:
        parsed = parsed_echo()
        parsed["interfaces"][0]["functions"]["echo"]["params"][0]["type"] = "u64"
        with self.assertRaises(builder.BuildError):
            builder.validate_cli_contract_metadata(self.metadata(), parsed)

    def test_new_error_case_and_stale_metadata_digest_are_rejected(self) -> None:
        parsed = parsed_echo()
        parsed["types"][0]["kind"]["variant"]["cases"].append(
            {"name": "new-error", "type": None}
        )
        with self.assertRaises(builder.BuildError):
            builder.validate_cli_contract_metadata(self.metadata(), parsed)
        metadata = copy.deepcopy(self.metadata())
        metadata["contracts"][0]["interfaces"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(builder.BuildError):
            builder.validate_cli_contract_metadata(metadata, parsed_echo())

    def test_generated_cli_inputs_use_actual_digest_and_positional_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            builder.write_cli_inputs(directory, "a" * 64, parsed_echo())
            deployment = json.loads((directory / "deployment.json").read_text())
            self.assertEqual(deployment["spec"]["release"], "sha256:" + "a" * 64)
            self.assertEqual(deployment["metadata"]["tenant"], "examples")
            self.assertEqual(
                json.loads((directory / "contracts.json").read_text()), self.metadata()
            )
            self.assertEqual(json.loads((directory / "input.json").read_text()), ["hello"])
            self.assertEqual(
                {path.name for path in directory.iterdir()},
                {"contracts.json", "deployment.json", "input.json"},
            )


if __name__ == "__main__":
    unittest.main()
