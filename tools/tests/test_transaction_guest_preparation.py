"""Preparation trust boundaries, without compiler or node execution claims."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_build as compatibility_build
from tools import prepare_transaction_guest_packages as preparation
from tools.dev_workflow.common import DevError
from tools.rust_capsule_project import ROOT, digest, inventory, snapshot, write_json

STATE = "latent:state/key-value@0.2.0"
INTENTS = "latent:intents/staging@0.1.0"
HTTP = "latent:http/client@0.2.0"


def captured_profile() -> dict[str, bytes]:
    # These are structural fixture inputs, not a compiled source observation.
    return {"capsule-project.json": b'{"name":"aggregate","service":"aggregate-service"}',
            "transaction-profile.json": (ROOT / "sdk/profile/transaction-requirements-v1.json").read_bytes(),
            "transaction-binding.json": json.dumps({
                "apiVersion": "latent.dev/v1", "kind": "TransactionBinding", "capsule": "aggregate-service",
                "deployment": "aggregate", "binding": "aggregate", "namespace": "transactional-aggregate",
                "profile": "lsf-transaction-v1", "hostAbiDigest": compatibility_build.read_json(
                    ROOT / "wit/host-abi-phase4-v1.json")["digest"], "stateSchema": "sha256:" + "1" * 64,
                "operations": [{"operation": "update", "mode": "strict-command", "inputFormat": "lsf-wit-values-v1",
                                "resultFormat": "lsf-wit-values-v1"}],
            }).encode()}


def unsigned_inputs(root: Path):
    project, built = root / "project", root / "built"
    project.mkdir()
    built.mkdir()
    (project / "app.txt").write_bytes(b"synthetic unsigned input")
    source = inventory(snapshot(project))
    component = b"synthetic output; this is deliberately not a valid component"
    (built / "component.wasm").write_bytes(component)
    (built / "source-inputs.json").write_bytes(source)
    recipe = inventory({"fixture-recipe": b"synthetic unsigned fixture recipe"})
    (built / "recipe-inputs.json").write_bytes(recipe)
    write_json(built / "package-source.json", {"layers": [{"source": "component.wasm"}]})
    package = inventory({"package-source.json": (built / "package-source.json").read_bytes(), "component.wasm": component})
    (built / "package-inputs.json").write_bytes(package)
    observation = {"formatVersion": 1, "buildType": "synthetic-unit-fixture",
        "componentDigest": digest(component), "componentSize": len(component),
        "source": {"repository": preparation.REPOSITORY, "snapshotDigest": digest(source), "revision": digest(source)[7:],
                   "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
        "materials": [{"name": name, "digest": digest(data), "size": len(data)} for name, data in (
            ("source-snapshot", source), ("build-recipe", recipe), ("package-inputs", package))]}
    write_json(built / "build-observation.json", observation)
    marker = {"formatVersion": 1, "packageAssembled": True, "sourceDigest": digest(source),
              "componentDigest": digest(component), "observationDigest": digest((built / "build-observation.json").read_bytes())}
    write_json(built / "BUILD-COMPLETE.json", marker)
    return project, built, observation, marker


class TransactionGuestPreparation(unittest.TestCase):
    def test_stateless_selection_keeps_original_profile_and_refuses_state(self):
        host = compatibility_build.host_profile()
        self.assertEqual(host, compatibility_build.read_json(ROOT / "wit/host-abi-phase3-v4.json"))
        self.assertEqual(compatibility_build.host_profile({"ordinary-source": b"no companion"}), host)
        findings = compatibility.import_findings([STATE], [STATE], host)
        self.assertIn("unknown-import", [row["classification"] for row in findings])

    def test_checked_transaction_signature_recognition_keeps_execution_unproven(self):
        host = compatibility_build.host_profile(captured_profile())
        self.assertEqual(host["id"], "lsf-host-abi-phase4-v1")
        findings = compatibility.import_findings([STATE, INTENTS, HTTP], [STATE, INTENTS, HTTP], host)
        self.assertEqual([row["classification"] for row in findings], ["unresolved-behavior"])
        for unknown in ("wasi:sockets/tcp@0.2.0", "latent:http/client@0.3.0", "latent:state/key-value@0.1.0"):
            with self.subTest(unknown=unknown):
                findings = compatibility.import_findings([unknown], [unknown], host)
                self.assertIn("unknown-import", [row["classification"] for row in findings])

    def test_incomplete_forged_and_cross_linked_profile_cannot_select_phase4(self):
        original = captured_profile()
        for name in ("transaction-binding.json", "transaction-profile.json", "capsule-project.json"):
            with self.subTest(missing=name), self.assertRaises((DevError, ValueError)):
                compatibility_build.host_profile({key: raw for key, raw in original.items() if key != name})
        for changed in ({**original, "transaction-profile.json": b'{}'},
                        {**original, "capsule-project.json": b'{"name":"other","service":"aggregate-service"}'},
                        {**original, "transaction-binding.json": original["transaction-binding.json"].replace(b'lsf-transaction-v1', b'future-profile')}):
            with self.assertRaises((DevError, ValueError)):
                compatibility_build.host_profile(changed)

    def test_original_unsigned_facts_are_required_and_changed_inputs_are_rejected(self):
        mutations = ("source", "component", "package-inputs", "observation", "missing-material", "duplicate-material")
        for mutation in mutations:
            with tempfile.TemporaryDirectory() as temporary, self.subTest(mutation=mutation):
                project, built, observation, marker = unsigned_inputs(Path(temporary))
                preparation.verify_observation(project, built, "synthetic-unit-fixture", [])
                if mutation == "source":
                    (project / "app.txt").write_bytes(b"changed original application")
                elif mutation == "component":
                    (built / "component.wasm").write_bytes(b"changed emitted bytes")
                elif mutation == "package-inputs":
                    (built / "package-inputs.json").write_bytes(b'{}')
                elif mutation == "observation":
                    (built / "build-observation.json").write_bytes(b'{}')
                else:
                    if mutation == "missing-material":
                        observation["materials"].pop()
                    else:
                        observation["materials"].append(observation["materials"][0])
                    (built / "build-observation.json").write_bytes(json.dumps(observation).encode())
                    marker["observationDigest"] = digest((built / "build-observation.json").read_bytes())
                    (built / "BUILD-COMPLETE.json").write_bytes(json.dumps(marker).encode())
                with self.assertRaises(ValueError):
                    preparation.verify_observation(project, built, "synthetic-unit-fixture", [])

    def test_missing_completion_is_not_replaced_with_a_fabricated_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = tuple(root.iterdir())
            with self.assertRaises((ValueError, OSError)):
                preparation.verify_observation(root, root, "synthetic-unit-fixture", [])
            self.assertEqual(tuple(root.iterdir()), before)

    def test_selected_language_delegates_to_the_complete_maintained_build_owner(self):
        root = Path("synthetic-owner-dispatch")
        for language in preparation.LANGUAGES:
            with self.subTest(language=language), patch(preparation.OWNERS[language] + ".build", return_value=root) as build:
                result = preparation.observed_build(language, root / "project", root / "output", root / "contracts", root / "packager",
                    tools=root / "managed-tools", wasi_sdk=root / "wasi-sdk", offline=True,
                    rust_bin=root / "rust", host_linker=root / "linker", go_cache=root / "go-cache", gradle_cache=root / "gradle-cache")
                self.assertEqual(result, root)
                self.assertEqual(build.call_args.args, (root / "project", root / "output", root / "contracts", root / "packager", preparation.REPOSITORY))
                options = build.call_args.kwargs
                if language == "java": self.assertEqual(options["wasi_sdk"], root / "wasi-sdk")
                if language in {"typescript", "dotnet"}: self.assertEqual(options["tools"], root / "managed-tools")
                if language in {"rust", "dotnet"}: self.assertIs(options["offline"], True)

    def test_invalid_language_and_missing_selected_prefix_leave_output_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            for language in ("future", "typescript", "dotnet", "java"):
                with self.subTest(language=language), self.assertRaises(ValueError):
                    preparation.prepare(language, output, output / "contracts", output / "packager")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
