"""Guest recipe isolation and bounded generator installation; no compiler/load."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from tools import install_guest_bindgen as install
from tools.build_snapshot import validate_workspace
from tools.tests.test_build_provenance_schemas import samples, DIGEST

ROOT = Path(__file__).resolve().parents[2]


def guest(language):
    value = samples()["build-observation"]
    value["buildType"] = f"https://latent.dev/build/{language}-guest/v1"
    value["source"].update(revision=DIGEST[7:], capture="explicit-input-files")
    value["dependencyCompleteness"] = "declared-inputs-incomplete"
    value["materials"].append({"name": "wit-bindgen", "digest": DIGEST, "size": 1})
    if language == "rust":
        value["parameters"]["cargoExample"] = "guest-http"
    else:
        value["parameters"] = {"compiler": "zig-cc", "fixture": "blob",
                               "target": "wasm32-wasi", "optimization": "O2"}
        value["materials"] = [m for m in value["materials"]
                              if m["name"] not in {"cargo", "rustc", "dependency-lock"}]
        value["materials"].append({"name": "zig", "digest": DIGEST, "size": 1})
    return value


class GuestProfileSchemas(unittest.TestCase):
    def test_echo_snapshot_can_still_capture_every_workspace_member(self):
        validate_workspace(ROOT)

    def validate(self, value, *, valid=True):
        for name in ("build-observation", "package-provenance-statement"):
            document = value
            if name == "package-provenance-statement":
                document = samples()[name]
                document["predicate"]["observation"] = value
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            validator = Draft202012Validator(schema)
            with self.subTest(schema=name):
                self.assertEqual(validator.is_valid(document), valid,
                                 list(validator.iter_errors(document)))

    def test_guest_and_legacy_profiles_are_separate(self):
        self.validate(samples()["build-observation"])
        for language in ("rust", "c"):
            value = guest(language)
            self.validate(value)
            changed = copy.deepcopy(value)
            changed["buildType"] = "https://latent.dev/build/echo-capsule/v1"
            self.validate(changed, valid=False)
            changed = copy.deepcopy(value)
            changed["parameters"] = guest("c" if language == "rust" else "rust")["parameters"]
            self.validate(changed, valid=False)
            for name in [m["name"] for m in value["materials"]]:
                changed = copy.deepcopy(value)
                changed["materials"] = [m for m in changed["materials"] if m["name"] != name]
                self.validate(changed, valid=False)
            for field, replacement in (("hermetic", True), ("dependencyCompleteness", "complete")):
                self.validate({**value, field: replacement}, valid=False)
            for key in value["parameters"]:
                changed = copy.deepcopy(value)
                del changed["parameters"][key]
                self.validate(changed, valid=False)
            changed = copy.deepcopy(value)
            changed["parameters"]["unreviewedOption"] = True
            self.validate(changed, valid=False)


class GeneratorArchive(unittest.TestCase):
    def archive(self, kinds):
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w:gz") as archive:
            for kind in kinds:
                info = tarfile.TarInfo("ignored-parent/wit-bindgen")
                info.type = kind
                info.size = 4 if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(b"tool") if info.size else None)
        return result.getvalue()

    def test_verified_regular_binary_only(self):
        data = self.archive([tarfile.REGTYPE])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            install.binary(data)
        with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()):
            self.assertEqual(install.binary(data), b"tool")

    def test_links_missing_duplicate_and_oversized_binary_fail(self):
        for kinds in ([], [tarfile.SYMTYPE], [tarfile.REGTYPE, tarfile.REGTYPE]):
            data = self.archive(kinds)
            with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(ValueError):
                    install.binary(data)
        data = self.archive([tarfile.REGTYPE])
        with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()), \
                patch.object(install, "MAX_BINARY", 3), self.assertRaises(ValueError):
            install.binary(data)


if __name__ == "__main__":
    unittest.main()
