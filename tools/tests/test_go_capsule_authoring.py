"""Go project capture is independent; real compiler/node behavior is in CI."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.go_capsule_project import create, snapshot, validate, TEMPLATES, RUNTIME_IMPORTS
from tools.go_capsule_build import build


class GoAuthoringTests(unittest.TestCase):
    def test_every_editable_template_has_exact_runtime_imports_and_captured_sdk(self):
        for template in TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temporary:
                root = create(Path(temporary) / "project", template)
                files = snapshot(root)
                project, lock, _pins = validate(files)
                self.assertEqual(project["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(lock["language"], "go")
                self.assertTrue(files["src/main.go"].startswith(b"// lsf-example-begin:"))
                for capability in RUNTIME_IMPORTS:
                    self.assertIn(("import " + capability + ";").encode(), files["wit/world.wit"])
                self.assertNotIn(b"grants", files["capsule-project.json"])

    def test_sdk_mutation_does_not_silently_become_a_reviewed_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "project", "greeting"))
            files["vendor/lsf/sdk/go-guest/runtime/deny-wasi.wat"] += b"\n;; changed\n"
            with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                validate(files)

    def test_source_and_wit_remain_editable_but_budget_types_are_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "project", "greeting"))
            files["src/main.go"] += b"\n// developer edit\n"
            files["wit/world.wit"] += b"\n// contract edit\n"
            validate(files)
            for invalid in (True, -1, 2**64, None):
                changed = dict(files)
                value = json.loads(files["capsule-project.json"])
                value["limits"]["cpuFuel"] = invalid
                changed["capsule-project.json"] = json.dumps(value).encode()
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    validate(changed)

    def test_existing_source_and_overlapping_build_outputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create(Path(temporary) / "project", "greeting")
            before = snapshot(root)
            with self.assertRaises(ValueError):
                create(root, "shipping")
            for output in (root, root.parent, root / "output"):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, "build output"):
                    build(root, output, Path("missing"), Path("missing"), "https://example.invalid/source")
            self.assertEqual(snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
