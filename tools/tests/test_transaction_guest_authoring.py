"""Authoring capture contracts; compiler and signed-node evidence are separate."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from tools.rust_capsule_project import AUTHORING_TEMPLATES, TEMPLATES, ROOT, snapshot
from tools.transaction_guest_project import TEMPLATE, package_companion


class TransactionGuestAuthoringTests(unittest.TestCase):
    def test_six_creators_capture_one_exact_profile_and_linked_companion(self):
        from tools.rust_capsule_project import create as rust
        from tools.c_capsule_project import create as c
        from tools.typescript_guest.project import create as typescript
        from tools.go_capsule_project import create as go
        from tools.java_capsule_project import create as java
        from tools.dotnet_guest.project import create as dotnet
        self.assertNotIn(TEMPLATE, TEMPLATES)
        self.assertIn(TEMPLATE, AUTHORING_TEMPLATES)
        with tempfile.TemporaryDirectory() as temporary:
            for language, create in (("rust", rust), ("c", c), ("typescript", typescript),
                                     ("go", go), ("java", java), ("dotnet", dotnet)):
                with self.subTest(language=language):
                    project_path = create(Path(temporary) / language, TEMPLATE, "synthetic-aggregate")
                    files = snapshot(project_path)
                    project = json.loads(files["capsule-project.json"])
                    declaration = json.loads(files["transaction-binding.json"])
                    self.assertEqual(declaration["capsule"], project["service"])
                    self.assertEqual(declaration["deployment"], project["name"])
                    self.assertEqual(declaration["binding"], project["name"])
                    self.assertEqual(declaration["namespace"], TEMPLATE)
                    self.assertEqual(declaration["hostAbiDigest"], json.loads(files["transaction-profile.json"])["hostAbiDigest"])
                    self.assertEqual([(value["operation"], value["mode"]) for value in declaration["operations"]],
                        [("update", "strict-command"), ("query", "fresh-query"), ("scan", "fresh-query")])
                    for package in ("state", "intents"):
                        self.assertEqual(files["wit/deps/" + package + "/package.wit"],
                            (ROOT / "wit/platform" / package / "package.wit").read_bytes())
                    output = Path(temporary) / (language + "-package")
                    output.mkdir()
                    layer = package_companion(output, project, files)
                    self.assertEqual(layer[0], "transaction-binding.json")
                    self.assertEqual((output / layer[0]).read_bytes(), files["transaction-binding.json"])

    def test_packaging_rejects_mismatched_duplicate_and_unbounded_companions(self):
        from tools.rust_capsule_project import create
        with tempfile.TemporaryDirectory() as temporary:
            source = create(Path(temporary) / "source", TEMPLATE)
            files = snapshot(source)
            project = json.loads(files["capsule-project.json"])
            declaration = json.loads(files["transaction-binding.json"])
            for field in ("capsule", "deployment", "profile", "kind"):
                changed = {**declaration, field: "other"}
                invalid = {**files, "transaction-binding.json": json.dumps(changed).encode()}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    package_companion(Path(temporary), project, invalid)
            for raw in (b'{"kind":"TransactionBinding","kind":"TransactionBinding"}', b" " * 131073):
                with self.assertRaises(ValueError):
                    package_companion(Path(temporary), project, {**files, "transaction-binding.json": raw})
            self.assertIsNone(package_companion(Path(temporary), project, {}))
