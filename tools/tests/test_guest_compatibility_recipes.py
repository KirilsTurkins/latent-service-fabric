"""Actual recipe capture controls; these do not certify guest execution."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule_build, dev_tool_distribution, go_capsule_build
from tools import guest_compatibility_build as build
from tools import java_capsule_build, rust_capsule_build
from tools.dotnet_guest import build as dotnet_build
from tools.typescript_guest import build as typescript_build
from tools.dev_workflow.common import DevError, encode
from tools.rust_capsule_project import inventory

V4 = "lsf-host-abi-phase3-v4"
V5 = "lsf-host-abi-phase3-v5"
RUNTIME = "latent:runtime/activation@0.1.0"
HTTP = "latent:http/streaming@0.3.0"
RANDOM = "latent:random/random@0.1.0"
OWNERS = (rust_capsule_build, c_capsule_build, java_capsule_build,
          dotnet_build, go_capsule_build, typescript_build)


class DeclaredRecipeCapture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.files = {}
        for name in build.RECIPE:
            raw = encode({"id": V4}) if name == build.HOST_MANIFESTS[V4] else name.encode()
            self.put(name, raw)
            self.files[name] = raw
        self.recorded = inventory(self.files)
        (self.output / "recipe-inputs.json").write_bytes(self.recorded)
        self.root_patch = patch.object(build, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def put(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def capture(self, imports=(RUNTIME,)):
        return build.capture_host_recipe(self.output, self.files, self.recorded, {"imports": list(imports)})

    def unchanged(self):
        self.assertEqual((self.output / "recipe-inputs.json").read_bytes(), self.recorded)
        self.assertEqual(set(self.files), set(build.RECIPE))

    def test_all_six_v4_recipes_need_no_v5_material(self):
        for owner in OWNERS:
            with self.subTest(owner=owner.__name__):
                self.assertIn(build.HOST_MANIFESTS[V4], owner.RECIPE)
                self.assertNotIn(build.HOST_MANIFESTS[V5], owner.RECIPE)
        self.assertFalse((self.root / build.HOST_MANIFESTS[V5]).exists())
        self.assertEqual(self.capture((HTTP, RANDOM)), self.recorded)
        self.unchanged()

    def test_declared_v5_adds_exact_manifest_to_retained_and_rechecked_recipe(self):
        raw = encode({"id": V5, "fixture": "controlled identity; no runtime implementation"})
        self.put(build.HOST_MANIFESTS[V5], raw)
        result = self.capture()
        expected = {**self.files, build.HOST_MANIFESTS[V5]: raw}
        self.assertEqual(result, inventory(expected))
        self.assertEqual(self.files[build.HOST_MANIFESTS[V5]], raw)
        self.assertEqual((self.output / "recipe-inputs.json").read_bytes(), result)
        self.assertEqual(inventory({name: build.read_file(self.root / name) for name in self.files}), result)

    def test_missing_v5_is_denied_without_v4_fallback_or_overwriting_capture(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            self.capture()
        self.unchanged()

    def test_wrong_v5_identity_does_not_overwrite_original_capture(self):
        self.put(build.HOST_MANIFESTS[V5], encode({"id": V4}))
        with self.assertRaisesRegex(DevError, "profile-identity"):
            self.capture()
        self.unchanged()

    def test_added_manifest_cannot_hide_changed_original_recipe(self):
        self.put(build.HOST_MANIFESTS[V5], encode({"id": V5}))
        self.put(build.RECIPE[0], b"changed compiler input")
        with self.assertRaisesRegex(DevError, "stale-recipe"):
            self.capture()
        self.unchanged()

    def test_changed_v5_after_capture_fails_final_recipe_recheck(self):
        path = self.put(build.HOST_MANIFESTS[V5], encode({"id": V5}))
        result = self.capture()
        path.write_bytes(encode({"id": V5, "changed": True}))
        self.assertNotEqual(inventory({name: build.read_file(self.root / name) for name in self.files}), result)
        self.assertEqual((self.output / "recipe-inputs.json").read_bytes(), result)

    def test_unknown_interface_version_does_not_select_or_capture_v5(self):
        self.assertEqual(self.capture(("latent:runtime/activation@0.2.0", RANDOM)), self.recorded)
        self.unchanged()


class AdvertisedRecipeDistribution(unittest.TestCase):
    def stage(self, profile):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        root = Path(owned.name)
        source, payload = root / "source", root / "payload"
        source.mkdir()
        payload.mkdir()
        names = {*go_capsule_build.RECIPE, "tools/dev_guest_recipe.py", "tools/dev_guest_tools.py",
                 "tools/dev_workflow/__init__.py", "tools/dev_workflow/common.py", "tools/dev_workflow/paths.py",
                 "tools/dev_managed_tools.py", "examples/echo-contract/capsule.json",
                 "examples/echo-contract/deployment.json", build.HOST_MANIFESTS[profile]}
        for name in names:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        with patch.object(dev_tool_distribution, "ROOT", source), \
                patch.object(dev_tool_distribution, "HOST_ABI", profile):
            dev_tool_distribution.recipe(payload, "go")
        return source, payload / "recipe"

    def test_advertised_v4_distribution_still_works_without_any_v5_manifest(self):
        source, staged = self.stage(V4)
        self.assertFalse((source / build.HOST_MANIFESTS[V5]).exists())
        self.assertFalse((staged / build.HOST_MANIFESTS[V5]).exists())
        self.assertEqual((staged / build.HOST_MANIFESTS[V4]).read_bytes(),
                         (source / build.HOST_MANIFESTS[V4]).read_bytes())

    def test_advertised_v5_distribution_retains_both_exact_manifest_inputs(self):
        source, staged = self.stage(V5)
        for profile in (V4, V5):
            self.assertEqual((staged / build.HOST_MANIFESTS[profile]).read_bytes(),
                             (source / build.HOST_MANIFESTS[profile]).read_bytes())


if __name__ == "__main__":
    unittest.main()
