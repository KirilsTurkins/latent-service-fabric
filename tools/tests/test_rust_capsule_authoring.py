"""Authoring boundaries; compiler/provider execution stays in the real gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import rust_capsule_build as build
from tools import rust_capsule_project as project


class RustProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="rust-authoring-tests-")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.source = project.create(Path(cls.workspace.name) / "project", "greeting")
        cls.inputs = project.snapshot(cls.source)

    def files(self):
        return dict(self.inputs)

    def changed(self, filename, change):
        files = self.files()
        value = json.loads(files[filename])
        change(value)
        files[filename] = json.dumps(value).encode()
        return files

    def test_independent_project_preserves_canonical_source_and_exact_lock(self):
        value, pins = build.validate_project(self.files())
        cargo = tomllib.loads(self.inputs["Cargo.toml"].decode())
        self.assertEqual(cargo["package"]["name"], "my-greeting")
        self.assertEqual(cargo["lib"], {"crate-type": ["cdylib"]})
        self.assertEqual(value["world"], "examples:greeting/service@1.0.0")
        source = project.ROOT / pins["template"]["source"] / "component.rs"
        self.assertEqual(project.digest(source.read_bytes()), pins["template"]["componentDigest"])
        self.assertEqual(source.read_bytes().replace(b'path: "examples/tutorial_greeting"', b'path: "wit"'), self.inputs["src/lib.rs"])
        self.assertNotIn(b"latent-node", self.inputs["Cargo.lock"])

    def test_all_tutorials_and_capability_examples_create_valid_standalone_inputs(self):
        for template in project.TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temp:
                root = project.create(Path(temp) / "project", template)
                value, _pins = build.validate_project(project.snapshot(root))
                self.assertEqual(value["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(value["limits"]["outboundRequests"], int(template == "http-status"))

    def test_fresh_projects_never_overwrite_existing_files(self):
        before = project.snapshot(self.source)
        with self.assertRaisesRegex(ValueError, "fresh"):
            project.create(self.source, "shipping")
        self.assertEqual(project.snapshot(self.source), before)

    def test_nonportable_and_colliding_package_names_are_rejected_before_creation(self):
        for name in ("../escape", "Cap", "a--b", "a_underscore", "x" * 65, "wit-bindgen"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / "project"
                with self.assertRaises(ValueError):
                    project.create(out, "greeting", name)
                self.assertFalse(out.exists())

    def test_reviewed_dependency_lock_rejects_changed_authoritative_checksums(self):
        original = project.ROOT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tools").mkdir()
            (root / "tools/rust_capsule.lock").write_bytes((original / "tools/rust_capsule.lock").read_bytes())
            (root / "Cargo.lock").write_text('version = 4\npackage = []\n')
            with patch.object(project, "ROOT", root), self.assertRaisesRegex(ValueError, "lock drift"):
                project.locked_dependencies("my-project")

    def test_edited_sdk_does_not_satisfy_the_original_source_lock(self):
        files = self.files()
        files["vendor/lsf/sdk/rust-guest/src/blob.rs"] += b"\n// edited\n"
        with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
            build.validate_project(files)

    def test_sdk_inheritance_cannot_introduce_uncaptured_dependency_overrides(self):
        files = self.files()
        files["Cargo.toml"] = files["Cargo.toml"].replace(b"[workspace.dependencies]", b'[workspace.dependencies]\ninjected = { path = "/escape" }', 1)
        self.assertNotEqual(files["Cargo.toml"], self.inputs["Cargo.toml"])
        with self.assertRaisesRegex(ValueError, "inheritance"):
            build.validate_project(files)

    def test_cargo_configuration_and_toolchain_overrides_are_rejected(self):
        for key, value in ((".cargo/config.toml", b'[build]\nrustc-wrapper = "/escape"'),
                           ("rust-toolchain.toml", b'[toolchain]\nchannel = "nightly"')):
            with self.subTest(key=key):
                files = self.files()
                files[key] = value
                with self.assertRaises(ValueError):
                    build.validate_project(files)

    def test_cargo_and_manifest_identity_must_agree(self):
        files = self.changed("capsule-project.json", lambda value: value.update(name="other"))
        with self.assertRaisesRegex(ValueError, "identities disagree"):
            build.validate_project(files)

    def test_manifest_fields_budgets_and_versions_are_closed(self):
        changes = [lambda value: value.update(extra=True), lambda value: value.update(formatVersion=True),
                   lambda value: value.update(name=[]), lambda value: value.update(limits=[]),
                   lambda value: value["limits"].update(cpuFuel=True), lambda value: value["limits"].update(cpuFuel=0),
                   lambda value: value["limits"].update(memoryBytes=2**64), lambda value: value["limits"].update(logBytes=-1)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.validate_project(self.changed("capsule-project.json", change))

    def test_sdk_lock_shape_and_version_fail_closed(self):
        for value in ([], {"formatVersion": 1}, {"formatVersion": True}, None):
            files = self.files()
            files["sdk-lock.json"] = json.dumps(value).encode()
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.validate_project(files)

    def test_duplicate_nonfinite_and_excessively_nested_json_are_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[' * 2000 + b']' * 2000, b'"\xff"'):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                project.decode_json(data)

    def test_captured_application_code_can_change_without_runtime_edits(self):
        files = self.files()
        files["src/lib.rs"] = files["src/lib.rs"].replace(b"Hello,", b"Welcome,")
        build.validate_project(files)
        self.assertNotEqual(project.inventory(files), project.inventory(self.files()))

    def test_additional_dependencies_require_exact_versions_and_no_path_escape(self):
        for spec in ('"1.0"', '{path="/outside"}', '{version="=1.0.0",git="https://invalid/repo"}', '[]'):
            files = self.files()
            files["Cargo.toml"] += f'\n[dependencies]\nextra = {spec}\n'.encode()
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                build.validate_project(files)
        files["Cargo.toml"] = self.inputs["Cargo.toml"] + b'\n[dependencies]\nextra = "=1.0.0"\n'
        build.validate_project(files)

    def test_build_script_must_be_captured_not_an_absolute_escape(self):
        files = self.files()
        files["Cargo.toml"] = files["Cargo.toml"].replace(b'publish = false', b'publish = false\nbuild = "/outside/build.rs"')
        with self.assertRaisesRegex(ValueError, "build script"):
            build.validate_project(files)

    def test_snapshot_excludes_only_root_build_and_git_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for directory in ("target", ".git", "source/target"):
                (root / directory).mkdir(parents=True)
                (root / directory / "file").write_bytes(b"data")
            self.assertEqual(project.snapshot(root), {"source/target/file": b"data"})

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_snapshot_rejects_linked_files_directories_and_ancestors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source").mkdir()
            (root / "source/data").write_bytes(b"data")
            (root / "alias").symlink_to(root / "source", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                project.snapshot(root / "alias")
            (root / "alias").unlink()
            (root / "source/link").symlink_to(root / "source/data")
            with self.assertRaisesRegex(ValueError, "regular file"):
                project.snapshot(root / "source")

    def test_snapshot_enforces_file_byte_count_and_total_budgets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "file").write_bytes(b"12345")
            with self.assertRaises(ValueError):
                project.read_file(root / "file", 4)
            with patch.object(project, "MAX_SOURCE", 4), self.assertRaises(ValueError):
                project.snapshot(root)
            with patch.object(project, "MAX_FILES", 0), self.assertRaises(ValueError):
                project.snapshot(root)

    def test_build_rejects_source_output_overlap_before_tool_execution(self):
        for output in (self.source, self.source.parent, self.source / "artifacts"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "overlap|inside target"):
                build.build(self.source, output, Path("missing"), Path("missing"), "https://example.com/repo")

    def test_build_failure_retains_stage_but_cannot_publish_a_success_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "failed"
            with patch.object(build, "resolve_tools", side_effect=ValueError("pinned compiler unavailable")):
                with self.assertRaisesRegex(ValueError, "pinned compiler"):
                    build.build(self.source, output, Path("missing"), Path("missing"), "https://example.com/repo")
            record = project.read_json(output / "BUILD-FAILED.json")
            self.assertEqual(record["stage"], "prepare")
            self.assertEqual(record["commands"], [])
            self.assertFalse((output / "BUILD-COMPLETE.json").exists())
            self.assertFalse((output / "build-observation.json").exists())

    def test_opt_in_diagnostics_keep_nonzero_status_without_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = build.Commands(root, root, dict(os.environ))
            with self.assertRaisesRegex(ValueError, "compile failed"):
                commands.run("compile", sys.executable, "-c", "import sys; print('typed compiler error',file=sys.stderr); sys.exit(7)")
            self.assertEqual(commands.records[0]["exitCode"], 7)
            self.assertEqual((root / "logs/00-compile.stderr.txt").read_text(), "typed compiler error\n")

    def test_overall_command_deadline_precedes_child_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = build.Commands(root, root, {})
            commands.deadline = 0
            with self.assertRaisesRegex(ValueError, "deadline"):
                commands.run("compile", "not-a-command")
            self.assertEqual(commands.records, [])


if __name__ == "__main__":
    unittest.main()
