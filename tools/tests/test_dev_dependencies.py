"""Real captured dependency bytes stay bound to approval, watch and build reuse."""
from __future__ import annotations

import base64
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.application_dependencies import MANIFEST, LOCK, capture
from tools.application_dependency_store import Store
from tools.build_dev_frontend import helper as helper_archive
from tools.build_snapshot import canonical
from tools.dev_workflow import build, common, dependencies, paths, project, snapshot, state
from tools.tests.test_dev_contracts import descriptor


class DependencyWorkflow(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "application"
        self.source.mkdir()
        (self.source / "src").mkdir()
        (self.source / "src/main.c").write_bytes(b"int main(void) { return 0; }\n")
        self.library = self.root / "private-unlisted-library"
        self.library.mkdir()
        (self.library / "outside.c").write_bytes(b"int external_value(void) { return 7; }\n")
        (self.source / "native.lock").write_bytes(b"unlisted/library@2.3\n")
        self.descriptor = descriptor()
        self.descriptor["language"] = "c"
        self.descriptor["template"]["ownerIssue"] = project.LANGUAGES["c"]
        self.manifest = {"formatVersion": 1, "language": "c", "selection": {
            "compiler": "zig-0.15.2", "target": "wasm32", "runtimeProfile": "closed-c-v1", "features": ["pure"]},
            "nativeLocks": ["native.lock"], "artifacts": [{"id": "unlisted/library@2.3", "role": "application",
                "format": "directory", "mount": "dependencies/unlisted", "source": {"path": "../private-unlisted-library"},
                "dependencies": [], "metadata": {"license": "MIT", "repository": "private-alias"}}],
            "transformations": []}
        self.save_descriptor()
        self.lock = self.capture()

    def save_descriptor(self):
        (self.source / "latent.project.json").write_bytes(common.encode(self.descriptor))

    def capture(self):
        (self.source / MANIFEST).write_bytes(canonical(self.manifest))
        lock = capture(self.source)
        (self.source / LOCK).write_bytes(canonical(lock))
        return lock

    def selected(self):
        return project.load(self.source)[0]

    def test_selection_and_closed_inputs_are_derived_without_descriptor_rewrite(self):
        before = (self.source / "latent.project.json").read_bytes()
        selected = self.selected()
        self.assertEqual(selected["dependencyInputs"]["applicationLock"], common.digest((self.source / LOCK).read_bytes()))
        self.assertEqual(selected["dependencyInputs"]["selection"], self.manifest["selection"])
        self.assertEqual(selected["inputRoots"], ["src", MANIFEST, LOCK, "native.lock", dependencies.OBJECTS])
        self.assertEqual((self.source / "latent.project.json").read_bytes(), before)
        dependencies.verify(self.source, selected)

    def test_source_edit_reuses_trust_but_changes_watch_snapshot(self):
        selected = self.selected()
        before, _ = snapshot.observe(self.source, selected["inputRoots"])
        (self.source / "src/main.c").write_bytes(b"int main(void) { return 1; }\n")
        after = self.selected()
        current, _ = snapshot.observe(self.source, after["inputRoots"])
        self.assertEqual(project.trust_identity(selected), project.trust_identity(after))
        self.assertNotEqual(before["identity"], current["identity"])

    def test_native_lock_or_profile_change_requires_new_trust(self):
        before = project.trust_identity(self.selected())
        (self.source / "native.lock").write_bytes(b"unlisted/library@3.0\n")
        self.capture()
        current = project.trust_identity(self.selected())
        self.assertNotEqual(before, current)
        self.manifest["selection"]["runtimeProfile"] = "changed-profile-v2"
        self.capture()
        self.assertNotEqual(current, project.trust_identity(self.selected()))

    def test_automatic_patch_identity_requires_new_trust(self):
        before = project.trust_identity(self.selected())
        self.manifest["selection"]["patchSet"] = "runtime-port-v2"
        self.capture()
        self.assertNotEqual(before, project.trust_identity(self.selected()))

    def test_stale_declared_binding_cannot_be_overwritten_implicitly(self):
        self.descriptor = self.selected()
        self.save_descriptor()
        (self.source / "native.lock").write_bytes(b"different selected graph\n")
        self.capture()
        with self.assertRaisesRegex(common.DevError, "dependency-trust-binding-drift"):
            self.selected()

    def test_orphan_lock_is_rejected(self):
        (self.source / MANIFEST).unlink()
        with self.assertRaisesRegex(common.DevError, "dependency-manifest-missing"):
            self.selected()

    def test_other_language_capture_is_rejected(self):
        self.manifest["language"] = "go"
        self.capture()
        with self.assertRaisesRegex(common.DevError, "version-or-language"):
            self.selected()

    def test_excluded_native_lock_cannot_disappear_from_snapshot(self):
        self.descriptor["exclude"] = ["native.lock"]
        self.save_descriptor()
        with self.assertRaisesRegex(common.DevError, "dependency-input-excluded"):
            self.selected()

    def test_controller_input_count_remains_an_explicit_limit(self):
        self.descriptor["inputRoots"] = [f"input-{number}" for number in range(64)]
        self.save_descriptor()
        with self.assertRaisesRegex(common.DevError, "project-path-count"):
            self.selected()

    def test_selection_credentials_and_invalid_executables_are_rejected(self):
        binding = self.selected()["dependencyInputs"]
        for key, value, code in (("selection", {"authorization": "private"}, "credentials-denied"),
                                 ("executableInputs", ["valid", "valid"], "duplicate"),
                                 ("applicationLock", "not-a-digest", "invalid-sha256")):
            changed = copy.deepcopy(binding)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(common.DevError, code):
                dependencies.validate(changed)

    def test_dependency_bytes_are_in_immutable_snapshot_without_originals_or_network(self):
        selected = self.selected()
        record, content = snapshot.observe(self.source, selected["inputRoots"])
        destination = self.root / "offline-snapshot"
        snapshot.materialize(destination, record, content)
        (self.library / "outside.c").unlink()
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("network called")):
            dependencies.verify(destination, selected)
            build.unchanged(destination, selected, record)
        self.assertEqual(snapshot.observe(destination, selected["inputRoots"])[0], record)

    def test_omitted_dependency_trust_binding_cannot_reuse_build(self):
        selected = self.selected()
        record, _ = snapshot.observe(self.source, selected["inputRoots"])
        selected.pop("dependencyInputs")
        with self.assertRaisesRegex(common.DevError, "dependency-trust-binding-drift"):
            build.unchanged(self.source, selected, record)

    def test_tampered_object_or_native_lock_rejected_before_build_reuse(self):
        selected = self.selected()
        record, _ = snapshot.observe(self.source, selected["inputRoots"])
        (self.source / "native.lock").write_bytes(b"tampered\n")
        with self.assertRaisesRegex(common.DevError, "dependency-native-lock-drift"):
            build.unchanged(self.source, selected, record)
        (self.source / "native.lock").write_bytes(b"unlisted/library@2.3\n")
        row = self.lock["artifacts"][0]["files"][0]
        Store(self.source / dependencies.OBJECTS).path(row["digest"]).write_bytes(b"tampered\n")
        with self.assertRaisesRegex(common.DevError, "dependency-artifact-integrity"):
            build.unchanged(self.source, selected, record)

    @unittest.skipUnless(sys.platform == "linux", "Linux helper imports pwd and owns backend state")
    def test_invalid_snapshot_does_not_advance_last_good_project(self):
        from tools.dev_workflow import helper
        selected = self.selected()
        selected.pop("dependencyInputs")
        record, content = snapshot.observe(self.source, selected["inputRoots"])
        backend = self.root / "backend"
        paths.new_directory(backend)
        prior = {"descriptor": {"name": "last-good"}, "snapshot": "prior"}
        state.atomic(backend, "project.json", prior)
        with self.assertRaisesRegex(common.DevError, "dependency-trust-binding-drift"):
            helper.sync(backend, {"project": selected, "trustedRecipe": project.trust_identity(selected),
                "snapshot": record, "content": {name: base64.b64encode(raw).decode() for name, raw in content.items()}})
        self.assertEqual(state.load(backend, "project.json"), prior)

    @unittest.skipUnless(sys.platform == "linux", "Linux helper owns backend state")
    def test_valid_offline_snapshot_is_accepted_with_bound_selection(self):
        from tools.dev_workflow import helper
        selected = self.selected()
        record, content = snapshot.observe(self.source, selected["inputRoots"])
        backend = self.root / "backend"
        paths.new_directory(backend)
        (self.library / "outside.c").unlink()
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("network called")):
            result = helper.sync(backend, {"project": selected, "trustedRecipe": project.trust_identity(selected),
                "snapshot": record, "content": {name: base64.b64encode(raw).decode() for name, raw in content.items()}})
        self.assertEqual(result["snapshot"], record["identity"])
        self.assertEqual(state.load(backend, "project.json")["descriptor"]["dependencyInputs"], selected["dependencyInputs"])

    @unittest.skipUnless(sys.platform == "linux", "symlink creation requires platform privilege")
    def test_cas_link_is_rejected(self):
        selected = self.selected()
        row = self.lock["artifacts"][0]["files"][0]
        target = Store(self.source / dependencies.OBJECTS).path(row["digest"])
        target.unlink()
        target.symlink_to(self.library / "outside.c")
        with self.assertRaisesRegex(common.DevError, "dependency-link-denied"):
            dependencies.verify(self.source, selected)

    def test_source_only_project_keeps_existing_trust(self):
        other = self.root / "source-only"
        other.mkdir()
        (other / "latent.project.json").write_bytes(common.encode(self.descriptor))
        selected, _ = project.load(other)
        self.assertEqual(selected, self.descriptor)
        self.assertEqual(project.trust_identity(selected), project.trust_identity(self.descriptor))

    def test_packaged_helper_imports_dependency_verification_outside_checkout(self):
        archive = self.root / "helper.pyz"
        identity = helper_archive(archive)
        self.assertEqual(identity, common.digest(archive.read_bytes()))
        with zipfile.ZipFile(archive) as packaged:
            self.assertIn("tools/dev_workflow/dependencies.py", packaged.namelist())
            self.assertIn("tools/application_dependencies.py", packaged.namelist())
        script = ("import sys; sys.path.insert(0,sys.argv[1]); "
                  "from tools.dev_workflow import project, dependencies; "
                  "from tools.application_dependencies import verify_inputs; "
                  "assert dependencies.OBJECTS == 'dependency-inputs/objects'")
        result = subprocess.run([sys.executable, "-I", "-c", script, str(archive)],
                                cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
