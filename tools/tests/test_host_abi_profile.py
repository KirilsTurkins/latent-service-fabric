"""Independent WIT/schema/binding-generator parity for the frozen Phase 3 ABI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import tomllib
import unittest

from jsonschema import Draft202012Validator

# Superseded matrices are historical qualification records, not active pins.
HISTORICAL_MATRICES = {
    2: "dc045e56df0bfbf132a485e24c89447768fa5c8d3eb2787c322e2426b43c261f",
    3: "e566e93362c4c9174a5fc50aa7b7cd93c3414719d0f69df7f08b7bf1c13dd58f",
}

ROOT = Path(__file__).resolve().parents[2]


class HostAbiProfileTests(unittest.TestCase):
    def test_frozen_matrix_matches_exact_sources_world_and_pinned_generators(self):
        for version, world_directory in [(2, "runtime-phase3"), (3, "runtime-phase3-streaming"), (4, "runtime-phase3-blobs")]:
            with self.subTest(version=version):
                self.check_matrix(version, world_directory)

    def check_matrix(self, version, world_directory):
        path = ROOT / f"wit/host-abi-phase3-v{version}.json"
        self.assertLess(path.stat().st_size, 16 * 1024)
        raw = path.read_bytes()
        if version in HISTORICAL_MATRICES:
            self.assertEqual(hashlib.sha256(raw).hexdigest(), HISTORICAL_MATRICES[version])
        matrix = json.loads(raw)
        schema = json.loads((ROOT / "schemas/host-abi-profile.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(matrix)
        digest = hashlib.sha256(b"lsf-host-abi-profile-v1\0")

        def frame(value):
            digest.update(struct.pack("<Q", len(value)))
            digest.update(value)

        frame(matrix["id"].encode())
        digest.update(struct.pack("<Q", len(matrix["interfaces"])))
        names = set()
        for item in matrix["interfaces"]:
            self.assertNotIn(item["interface"], names)
            names.add(item["interface"])
            source = (ROOT / item["source"]).read_bytes()
            self.assertLess(len(source), 16 * 1024)
            self.assertNotIn(b"\r", source)
            self.assertEqual(item["sourceSha256"], "sha256:" + hashlib.sha256(source).hexdigest())
            frame(item["interface"].encode())
            frame(item["package"].encode())
            digest.update(bytes([item["binding"] == "provider", item["asynchronous"]]))
            frame(source)
        self.assertEqual(matrix["digest"], "sha256:" + digest.hexdigest())
        world = (ROOT / f"wit/platform/{world_directory}/world.wit").read_text(encoding="utf-8")
        self.assertEqual(names, set(re.findall(r"^\s*import ([^;]+);", world, re.MULTILINE)))
        self.assertIn("package " + matrix["world"].replace("/capsule", "") + ";", world)
        dependencies = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["dependencies"]
        self.check_generator_pins(version, matrix, dependencies)

    def check_generator_pins(self, version, matrix, dependencies):
        self.assertEqual(matrix["id"], f"lsf-host-abi-phase3-v{version}")
        if version in HISTORICAL_MATRICES:
            self.assertEqual(matrix["wasmtimeVersion"], "47.0.4")
            self.assertEqual(matrix["guestGenerator"], "wit-bindgen@0.62.0")
        else:
            self.assertEqual(version, 4, "new active ABI profiles require explicit review")
            self.assertEqual(dependencies["wasmtime"]["version"], "=" + matrix["wasmtimeVersion"])
            self.assertEqual("wit-bindgen@" + dependencies["wit-bindgen"].lstrip("="), matrix["guestGenerator"])

    def test_active_and_historical_generator_mismatches_are_rejected(self):
        dependencies = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["dependencies"]
        for version in (2, 3, 4):
            matrix = json.loads((ROOT / f"wit/host-abi-phase3-v{version}.json").read_bytes())
            for field, invalid in (("wasmtimeVersion", "0.0.0"), ("guestGenerator", "wit-bindgen@0.0.0")):
                with self.subTest(version=version, field=field), self.assertRaises(AssertionError):
                    self.check_generator_pins(version, {**matrix, field: invalid}, dependencies)
        with self.assertRaises(AssertionError):
            self.check_generator_pins(5, {**matrix, "id": "lsf-host-abi-phase3-v5"}, dependencies)


if __name__ == "__main__":
    unittest.main()
