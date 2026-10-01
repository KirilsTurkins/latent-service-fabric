"""Original package identity and dependency selection; no compiler or grant."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools.composition_probe.source import _imports, java_component
from tools.dev_workflow import preflight
from tools.dev_workflow.common import digest, encode


API = "examples:domain/api@1.0.0"
TYPES = "examples:domain/types@1.0.0"
CLOCK = "latent:clock/wall@0.1.0"


class CompositionProbeSourceTests(unittest.TestCase):
    def fixture(self, root):
        package, build, output = root / "package", root / "build", root / "selected"
        for path in (package / "layers", build, output):
            path.mkdir(parents=True)
        metadata = {"format_version": 1, "contracts": [{"id": API,
            "dependencies": [TYPES], "interfaces": [{"functions": [{"id": "run"}]}]}]}
        component = b"\0asm\x0d\0\x01\0"
        capsule = {"component": {"digest": digest(component), "world": "examples:domain/service@1.0.0"},
            "exports": [API], "imports": [{"contract": CLOCK}],
            "execution": {"limits": {name: None if name == "wallTimeLimitMillis" else 1
                                     for name in preflight.BUDGETS}}}
        layers = []
        for role, name, raw in (("component", "component.wasm", component),
                               ("capsule-manifest", "capsule.json", encode(capsule)),
                               ("contracts", "contracts.json", encode(metadata))):
            (package / "layers" / name).write_bytes(raw)
            layers.append({"size": len(raw), "digest": digest(raw), "annotations": {
                "dev.latent.layer.role": role, "org.opencontainers.image.title": name}})
        descriptor = {"schemaVersion": 2, "artifactType": "application/vnd.latent.capsule.v1", "layers": layers}
        (package / "manifest.json").write_bytes(encode(descriptor))
        (build / "contracts.json").write_bytes(encode(metadata))
        (build / "surface.json").write_bytes(encode({"world": capsule["component"]["world"],
            "exports": [API], "imports": [CLOCK]}))
        (build / "BUILD-COMPLETE.json").write_bytes(encode({"packageAssembled": True,
            "componentDigest": digest(component), "observationDigest": "sha256:" + "b" * 64}))
        target = {"service": "examples/domain", "route": "domain", "revision": "revision-v1:sha256:" + "a" * 64,
            "publicationId": "publication:sha256:" + "c" * 64, "deploymentId": "domain",
            "deploymentGeneration": "1", "contract": API, "function": "run"}
        return package, build, target, output, descriptor, metadata

    def test_original_signed_contract_dependencies_complete_the_callable_build_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            package, build, target, output, descriptor, metadata = self.fixture(Path(temporary))
            selected = java_component(package, build, target, output, "domain")
            self.assertEqual(selected["imports"], [TYPES, CLOCK])
            self.assertEqual(selected["contractMetadataDigest"], digest(encode(metadata)))
            self.assertEqual(selected["packageDigest"], digest(encode(descriptor)))
            self.assertEqual((output / "domain/contracts.json").read_bytes(), encode(metadata))
            # Neither runtime observation nor an unsigned sidecar can supply a
            # different type declaration to this original-source observer.
            changed = copy.deepcopy(metadata)
            changed["contracts"][0]["dependencies"] = ["examples:other/types@1.0.0"]
            (build / "contracts.json").write_bytes(encode(changed))
            with self.assertRaisesRegex(RuntimeError, "composition-probe-build-and-original-package-mismatch"):
                java_component(package, build, target, output, "changed")

    def test_changed_original_metadata_layer_is_rejected_before_selecting_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            package, build, target, output, _, metadata = self.fixture(Path(temporary))
            metadata["contracts"][0]["dependencies"] = []
            (package / "layers/contracts.json").write_bytes(encode(metadata))
            (build / "contracts.json").write_bytes(encode(metadata))
            with self.assertRaisesRegex(RuntimeError, "composition-probe-original-layer-changed"):
                java_component(package, build, target, output, "domain")
            self.assertFalse((output / "domain").exists())

    def test_dependency_union_is_bounded_exact_and_excludes_locally_exported_type_owners(self):
        metadata = {"contracts": [{"id": API, "dependencies": [API, TYPES, CLOCK]}]}
        surface = {"imports": [CLOCK], "exports": [API]}
        self.assertEqual(_imports(metadata, surface), [TYPES, CLOCK])
        for dependencies in ([TYPES, TYPES], ["unversioned"], [[]], None,
                             [f"examples:p/type-{index}@1.0.0" for index in range(65)]):
            metadata["contracts"][0]["dependencies"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaises((RuntimeError, ValueError)):
                _imports(metadata, surface)
        metadata["contracts"][0]["dependencies"] = [f"examples:p/type-{index}@1.0.0" for index in range(64)]
        with self.assertRaisesRegex(RuntimeError, "composition-probe-original-import-bound"):
            _imports(metadata, surface)


if __name__ == "__main__":
    unittest.main()
