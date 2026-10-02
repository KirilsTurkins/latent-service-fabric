"""Profile and companion integrity; these cases claim no guest execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import build_artifacts, build_cache, bundle, common, project, tool_inventory, transaction_binding
from tools.tests.test_dev_contracts import descriptor
from tools.transaction_guest_project import augment


def declaration():
    files = {}
    augment(files, {"service": "examples/aggregate", "name": "aggregate"})
    return files["transaction-binding.json"]


class TransactionGuestWorkflowTests(unittest.TestCase):
    def test_phase4_descriptor_requires_companion_and_changes_trust_and_cache_identity(self):
        old = descriptor()
        selected = copy.deepcopy(old)
        selected["hostAbi"] = common.TRANSACTION_HOST_ABI
        with self.assertRaises(common.DevError):
            project.validate(selected)
        selected["artifacts"]["transactionBinding"] = "output/transaction-binding.json"
        project.validate(selected)
        self.assertNotEqual(project.trust_identity(old), project.trust_identity(selected))
        record = {"identity": common.digest(b"source")}
        self.assertNotEqual(build_cache.identity(record, old, "same-recipe", "linux-x86_64", "same-packager"),
                            build_cache.identity(record, selected, "same-recipe", "linux-x86_64", "same-packager"))
        for value in ("future", None, {}, []):
            bad = copy.deepcopy(selected)
            bad["hostAbi"] = value
            with self.subTest(value=value), self.assertRaises(common.DevError):
                project.validate(bad)
        selected["hostAbi"] = common.HOST_ABI
        with self.assertRaises(common.DevError):
            project.validate(selected)

    def test_companion_preserves_exact_links_profile_and_bounded_unique_operations(self):
        original = json.loads(declaration())
        valid = lambda raw: transaction_binding.validate(raw, capsule="examples/aggregate", deployment="aggregate", binding="aggregate")
        self.assertEqual(valid(declaration()), original)
        changed = []
        for key in ("capsule", "deployment", "binding", "profile", "hostAbiDigest", "stateSchema"):
            changed.append({**original, key: "other"})
        changed.extend(({**original, "namespace": "é" * 129}, {**original, "namespace": "\ud800"},
                        {**original, "operations": []}, {**original, "operations": original["operations"] * 2},
                        {**original, "operations": [{**original["operations"][0], "mode": "guest-commit"}]},
                        {**original, "authority": "approved"}))
        for value in changed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid(json.dumps(value).encode())
        for raw in (b" " * 131073, b'{"kind":"TransactionBinding","kind":"TransactionBinding"}'):
            with self.assertRaises(ValueError):
                valid(raw)

    def test_checked_companion_is_the_exact_packaged_asset_before_operator_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            output = source / "output"
            output.mkdir()
            component = b"\0asm\x0d\0\x01\0"
            capsule = {"metadata": {"name": "examples/aggregate"}, "component": {"digest": common.digest(component)}}
            deployment = {"metadata": {"name": "aggregate"}, "spec": {"service": "examples/aggregate", "release": common.digest(component)}}
            recipe = {"layers": [{"path": "transaction-binding.json", "source": "transaction-binding.json",
                                    "role": "asset", "mediaType": transaction_binding.MEDIA_TYPE}]}
            artifacts = {key: "output/" + name for key, name in (("component", "component.wasm"),
                ("capsule", "capsule.json"), ("deployment", "deployment.json"),
                ("transactionBinding", "transaction-binding.json"), ("packageSource", "package-source.json"))}
            artifacts["packageRoot"] = "output/package"
            (output / "component.wasm").write_bytes(component)
            (output / "capsule.json").write_bytes(common.encode(capsule))
            (output / "deployment.json").write_bytes(common.encode(deployment))
            (output / "transaction-binding.json").write_bytes(declaration())
            (output / "package-source.json").write_bytes(common.encode(recipe))
            transaction_binding.check_package(source, artifacts, capsule)
            recorded = build_artifacts.identities(source, artifacts)
            (output / "wrong.json").write_bytes(b"changed")
            recipe["layers"][0]["source"] = "wrong.json"
            (output / "package-source.json").write_bytes(common.encode(recipe))
            with patch.object(build_artifacts, "invoke") as invoke, self.assertRaises(common.DevError):
                build_artifacts.package(Path("uninvoked-operator"), source, artifacts, 0, lambda: None, cached=False)
            invoke.assert_not_called()
            with self.assertRaises(common.DevError):
                build_artifacts.verify_receipt(source, {"artifacts": artifacts}, {"artifacts": recorded})

    def test_six_distribution_templates_capture_selected_profile_without_runtime_grants(self):
        from tools.dev_tool_distribution import compiler_inventory, templates
        with tempfile.TemporaryDirectory() as temporary:
            for language in project.LANGUAGES:
                payload = Path(temporary) / language
                for name in ("sdk/bin/python", "recipe/tools/dev_guest_recipe.py", "sdk/bin/capsule-contracts",
                             "sdk/bin/capsule-test-signer", "sdk/bin/wasm-tools", "sdk/bin/wit-bindgen",
                             "sdk/rust/bin/cargo", "sdk/rust/bin/rustc"):
                    path = payload / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"synthetic inventory bytes; never executed")
                inventory = compiler_inventory(payload, "a" * 40, language, host_abi=common.TRANSACTION_HOST_ABI)
                with self.assertRaises(common.DevError):
                    tool_inventory.validate(inventory, language, project.LANGUAGES[language], "linux-x86_64")
                with self.assertRaises(common.DevError):
                    templates(payload, "a" * 40, language)
                self.assertFalse((payload / "templates").exists())
                result = templates(payload, "a" * 40, language, host_abi=common.TRANSACTION_HOST_ABI)
                self.assertEqual(set(result), {"transactional-aggregate"})
                captured = payload / result["transactional-aggregate"]["path"]
                selected = json.loads((captured / "template.json").read_bytes())["project"]
                self.assertEqual(selected["hostAbi"], common.TRANSACTION_HOST_ABI)
                self.assertEqual(selected["artifacts"]["transactionBinding"], "output/transaction-binding.json")
                scenarios = json.loads((captured / "tests/scenarios.json").read_bytes())["scenarios"]
                self.assertTrue(all("transactional-state" in case["requires"] for case in scenarios))
                self.assertTrue(all(not any("state" in grant or "intents" in grant
                    for grant in case.get("execution", {}).get("grants", [])) for case in scenarios))
                if language == "rust":
                    other = payload / "default"
                    # The default still distributes the three existing tutorials.
                    (other / "sdk").mkdir(parents=True)
                    import shutil
                    shutil.copytree(payload / "sdk", other / "sdk", dirs_exist_ok=True)
                    shutil.copytree(payload / "recipe", other / "recipe")
                    compiler_inventory(other, "a" * 40, language)
                    self.assertEqual(set(templates(other, "a" * 40, language)), {"greeting", "word-count", "shipping"})

    def test_phase4_bundle_cannot_claim_a_portable_or_non_guest_profile(self):
        entries = [{"path": name, "size": 1, "sha256": common.digest(name.encode()), "executable": False}
                   for name in ("licenses/terms", "sbom.spdx.json", "guest-tools.json", "templates.json")]
        value = {"schemaVersion": "latent.dev.bundle.v1", "version": "candidate", "sourceCommit": "a" * 40,
            "target": "linux-x86_64", "hostAbi": common.TRANSACTION_HOST_ABI, "protocol": common.PROTOCOL,
            "archive": {"name": "candidate.zip", "size": 1, "sha256": common.digest(b"archive")},
            "files": entries, "licenses": ["licenses/terms"], "sbom": "sbom.spdx.json"}
        bundle.manifest(value, target="linux-x86_64", version="candidate", commit="a" * 40)
        for target, files in (("windows-x86_64", entries), ("linux-x86_64", entries[:2])):
            with self.subTest(target=target), self.assertRaises(common.DevError):
                bundle.manifest({**value, "target": target, "files": files}, target=target, version="candidate", commit="a" * 40)


if __name__ == "__main__":
    unittest.main()
