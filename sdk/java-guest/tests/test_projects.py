"""Compiler-free source-capture regressions, not runtime qualification."""
import json
from pathlib import Path
import tempfile
import sys
import unittest

from tools.java_capsule_project import TEMPLATES, create, validate
from tools.rust_capsule_project import snapshot
from tools.java_guest.compiler import source_module


class Projects(unittest.TestCase):
    def test_captured_helpers_do_not_reuse_other_projects_or_mutate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = list(sys.path)
            first, second = root / "one.py", root / "two.py"
            first.write_text("import sys\nsys.path.insert(0, 'captured-only')\nVALUE = 1\n", encoding="utf-8")
            second.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertEqual(source_module(first).VALUE, 1)
            self.assertEqual(source_module(second).VALUE, 2)
            self.assertEqual(sys.path, before)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["one.py", "two.py"])

    def test_printed_guide_has_six_closed_steps_and_only_declared_runtime_grants(self):
        from tools.java_capsule_project import ROOT
        text = (ROOT / "docs/component-development/java-authoring.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("```bash\n"), 6)
        self.assertIn('"engine": {"javaGuest": True}', text)
        self.assertIn('"${CARGO_TARGET_DIR:-$PWD/target}/debug"', text)
        self.assertIn("for name in clockMonotonic clockWall; do", text)
        self.assertNotIn('"random":', text)

    def test_five_projects_are_editable_outside_checkout_with_locked_sdk(self):
        with tempfile.TemporaryDirectory() as temporary:
            for template in TEMPLATES:
                with self.subTest(template=template):
                    project = create(Path(temporary) / template, template)
                    files = snapshot(project)
                    metadata, lock, pins = validate(files)
                    self.assertEqual(metadata["world"], f"examples:{template}/service@1.0.0")
                    self.assertEqual(lock["language"], "java")
                    self.assertEqual(pins["sdk"]["java"], "25.0.4.1+1")
                    self.assertIn(b"latent:clock/monotonic@0.1.0", files["wit/world.wit"])
                    files["src/dev/latent/app/Capsule.java"] += b"\n// authored outside the checkout\n"
                    validate(files)

    def test_sdk_drift_binary_overrides_and_nonfinite_budgets_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "app", "greeting"))
            drift = dict(files)
            drift["vendor/lsf/sdk/java-guest/compiler.gradle"] += b"\n// changed\n"
            with self.assertRaisesRegex(ValueError, "vendored SDK changed"): validate(drift)
            for path in ("build.gradle", "lib/dependency.jar", "src/secret.txt"):
                with self.subTest(path=path), self.assertRaises(ValueError): validate({**files, path: b"override"})
            project = json.loads(files["capsule-project.json"])
            for bad in (None, -1, True, 2**64):
                project["limits"]["cpuFuel"] = bad
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    validate({**files, "capsule-project.json": json.dumps(project).encode()})

    def test_existing_target_and_source_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "app"
            create(target, "greeting")
            with self.assertRaises(ValueError): create(target, "greeting")
            for name in ("../escape", "BadName", "a" * 65):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    create(Path(temporary) / "unused", "greeting", name)


if __name__ == "__main__": unittest.main()
