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

ROOT = Path(__file__).resolve().parents[2]


class HostAbiProfileTests(unittest.TestCase):
    def test_frozen_matrix_matches_exact_sources_world_and_pinned_generators(self):
        for version, world_directory in [(2, "runtime-phase3"), (3, "runtime-phase3-streaming")]:
            with self.subTest(version=version):
                self.check_matrix(version, world_directory)

    def check_matrix(self, version, world_directory):
        path = ROOT / f"wit/host-abi-phase3-v{version}.json"
        self.assertLess(path.stat().st_size, 16 * 1024)
        matrix = json.loads(path.read_text(encoding="utf-8"))
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
        self.assertEqual(dependencies["wasmtime"]["version"], "=" + matrix["wasmtimeVersion"])
        self.assertEqual("wit-bindgen@" + dependencies["wit-bindgen"].lstrip("="), matrix["guestGenerator"])


if __name__ == "__main__":
    unittest.main()
