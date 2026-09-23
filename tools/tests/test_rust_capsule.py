"""Offline tests for independent project boundaries, not guest execution evidence."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import rust_capsule as capsule


class RustCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lsf-authoring-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "application"

    def scaffold(self, template="greeting"):
        capsule.new_project(self.project, template, "application")
        return capsule.project(self.project)

    def replace_json(self, name, value):
        (self.project / name).write_bytes(capsule.canonical(value))

    def test_tutorials_are_copied_from_the_single_maintained_source(self):
        for template in capsule.TUTORIALS:
            with self.subTest(template=template):
                directory = self.root / template
                capsule.new_project(directory, template, template)
                original = capsule.ROOT / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
                self.assertEqual((directory / "wit/world.wit").read_bytes(), (original / "world.wit").read_bytes())
                self.assertEqual((directory / "src/lib.rs").read_text().replace('path: "wit"', f'path: "examples/tutorial_{template.replace("-", "_")}"'), (original / "component.rs").read_text())
                self.assertEqual(capsule.project(directory)["world"], f"examples:{template}/service@1.0.0")

    def test_each_capability_uses_the_maintained_sdk_and_exact_host_wit(self):
        for name in capsule.GUESTS:
            with self.subTest(capability=name):
                destination = self.root / name
                capsule.new_project(destination, "guest-" + name, "app-" + name)
                profile = capsule.document(capsule.ROOT / f"tools/toolchain-smoke/examples/guest_{name}/profile.json")
                self.assertEqual(capsule.project(destination)["world"], profile["world"])
                if profile.get("witDirectory"):
                    dependency = profile["witDirectory"]
                    self.assertEqual((destination / f"wit/deps/{dependency}/package.wit").read_bytes(), (capsule.ROOT / f"wit/platform/{dependency}/package.wit").read_bytes())

    def test_standalone_workspace_and_toolchain_are_pinned(self):
        value = self.scaffold()
        manifest = tomllib.loads((self.project / "Cargo.toml").read_text())
        self.assertEqual(manifest["workspace"], {})
        self.assertEqual(manifest["lib"]["crate-type"], ["cdylib"])
        self.assertEqual(value["sdkSnapshotDigest"], capsule.digest(capsule.sdk_inputs()))
        self.assertFalse(capsule.ROOT in self.project.parents)
        self.assertEqual(value["limits"]["outboundRequests"], 0)
        self.assertNotIn("grants", value)

    def test_existing_destination_invalid_names_and_internal_workspace_are_rejected(self):
        self.scaffold()
        for name in ("a/b", "..", "A", "a_", "a-", "a" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                capsule.new_project(self.root / "other", "greeting", name)
        with self.assertRaises(ValueError):
            capsule.new_project(self.project, "greeting", "application")
        with self.assertRaises(ValueError):
            capsule.new_project(capsule.ROOT / "forbidden-authoring-project", "greeting", "application")

    def test_cargo_sdk_and_binding_overrides_cannot_hide_from_capture(self):
        self.scaffold()
        path = self.project / "Cargo.toml"
        original = path.read_text()
        for changed in (original.replace('crate-type = ["cdylib"]', 'crate-type = ["rlib"]'),
                        original.replace('name = "application"', 'name = "elsewhere"'),
                        original.replace('latent-guest = { path = ', 'latent-guest = { git = '),
                        original.replace('wit-bindgen = "=', 'wit-bindgen = "^'),
                        original + '\n[dependencies]\nother = { path = "../escape" }\n',
                        original + '\n[patch.crates-io]\nother = { path = "../escape" }\n'):
            path.write_text(changed)
            with self.assertRaises(ValueError):
                capsule.project(self.project)
        path.write_text(original)
        (self.project / ".cargo").mkdir()
        with self.assertRaises(ValueError):
            capsule.project(self.project)

    def test_application_sources_can_change_but_change_the_snapshot(self):
        self.scaffold()
        before = capsule.source_inputs(self.project)
        source = self.project / "src/lib.rs"
        source.write_text(source.read_text().replace("Hello,", "Welcome,"))
        self.assertEqual(capsule.project(self.project)["name"], "application")
        self.assertNotEqual(before, capsule.source_inputs(self.project))

    def test_sdk_pin_and_duplicate_json_members_are_rejected(self):
        value = self.scaffold()
        value["sdkSnapshotDigest"] = "sha256:" + "0" * 64
        self.replace_json("capsule-project.json", value)
        with self.assertRaises(ValueError):
            capsule.project(self.project)
        self.replace_json("capsule-project.json", {})
        with self.assertRaises(ValueError):
            capsule.project(self.project)
        (self.project / "capsule-project.json").write_text('{"formatVersion":1,"formatVersion":1}')
        with self.assertRaises(ValueError):
            capsule.document(self.project / "capsule-project.json")

    def test_source_capture_rejects_links_and_byte_count_overruns(self):
        self.scaffold()
        linked = self.project / "src/linked.rs"
        linked.symlink_to(self.project / "src/lib.rs")
        with self.assertRaises(ValueError):
            capsule.source_inputs(self.project)
        with self.assertRaises(ValueError):
            capsule.read(linked)
        linked.unlink()
        with patch.object(capsule, "MAX_FILES", 1), self.assertRaises(ValueError):
            capsule.files(self.project)
        with self.assertRaises(ValueError):
            capsule.read(self.project / "src/lib.rs", 2)
        with self.assertRaises(ValueError):
            capsule.inventory([("a", self.project / "src/lib.rs"), ("A", self.project / "src/lib.rs")])

    def test_lock_requires_explicit_review_before_replacing_a_binding_lock(self):
        self.scaffold()
        (self.project / "bindings.lock.json").write_text("{}")
        with self.assertRaises(ValueError):
            capsule.lock_project(self.project)

    def test_failed_build_preserves_stage_and_never_claims_execution(self):
        self.scaffold()
        (self.project / "Cargo.lock").write_text("version = 4\n")
        (self.project / "bindings.lock.json").write_text("{}")
        output = self.root / "attempt"
        with patch.object(capsule, "Tools", side_effect=ValueError("intentional toolchain failure")):
            with self.assertRaises(ValueError):
                capsule.build(self.project, output, Path(__file__).resolve(), "https://example.com/repository")
        failure = capsule.document(output / "BUILD-FAILED.json")
        self.assertEqual(failure["stage"], "toolchain")
        self.assertEqual(failure["errorType"], "ValueError")
        self.assertNotIn("intentional", json.dumps(failure))
        self.assertFalse((output / "BUILD-COMPLETE.json").exists())
        with self.assertRaises(ValueError):
            capsule.build(self.project, output, Path(__file__).resolve(), "https://example.com/repository")

    def test_diagnostics_are_a_standalone_contract_not_an_ambient_host_grant(self):
        value = self.scaffold("diagnostics")
        self.assertEqual(value["world"], "examples:authoring-diagnostics/service@1.0.0")
        self.assertNotIn("import", (self.project / "wit/world.wit").read_text())
        self.assertEqual(value["limits"]["outboundRequests"], 0)


if __name__ == "__main__":
    unittest.main()
