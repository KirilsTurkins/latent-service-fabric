"""Companion integrity and typed cleanup at the language-owned adapter boundary."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.dev_workflow import build, bundle, common, paths, project, tool_inventory
from tools.dev_guest_tools import stage_registry
from tools.tests.test_dev_contracts import descriptor


class FrontendDistribution(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Candidate assembly runs on Linux")
    def test_candidate_rejects_changed_added_or_removed_frontend_libraries_before_assembly(self):
        import json
        from tools import build_dev_bundle as builder
        from tools.dev_distribution import frontend_files
        for mutation in ("change", "add", "remove"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                frontend = root / "frontend"
                for name in ("dist/latent-dev/latent-dev", "dist/latent-dev/_internal/library.so",
                             "licenses/terms.txt", "helper.pyz", "python-inventory.json"):
                    path = frontend / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(name.encode())
                record = {"sourceCommit": "a" * 40, "sourceDirty": False, "hostAbi": common.HOST_ABI,
                          "protocol": common.PROTOCOL, "target": "linux-x86_64", "files": frontend_files(frontend)}
                (frontend / "build.json").write_text(json.dumps(record))
                library = frontend / "dist/latent-dev/_internal/library.so"
                if mutation == "change":
                    library.write_bytes(b"substituted native library")
                elif mutation == "add":
                    library.with_name("extra.so").write_bytes(b"unrecorded native library")
                else:
                    library.unlink()
                with patch.object(sys, "argv", ["builder", "--target", "linux-x86_64", "--frontend", str(frontend),
                        "--portable", str(root / "missing-host"), "--output", str(root / "output")]), \
                        patch.object(builder.subprocess, "check_output", side_effect=["a" * 40, b"", b"1600000000"]):
                    with self.assertRaisesRegex(common.DevError, "frontend-distribution-bytes-changed"):
                        builder.main()
                self.assertFalse((root / "output").exists())


class CompanionInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        files = []
        for name, raw in (("sdk/bin/tool", b"compiler"), ("sdk/lib/library", b"library"), ("recipe/build.py", b"recipe")):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append({"path": name, "size": len(raw), "sha256": common.digest(raw)})
        value = {"schemaVersion": "latent.dev.guest-tools.v1", "language": "rust", "ownerIssue": 544,
            "sourceCommit": "a" * 40, "hostAbi": common.HOST_ABI, "host": "linux-x86_64", "files": files}
        value["identity"] = common.digest(common.encode(value))
        self.value = value
        raw = common.encode(value)
        (self.root / "guest-tools.json").write_bytes(raw)
        self.descriptor = descriptor()
        self.descriptor["build"].update(argv=["cargo"], inventory={"path": "guest-tools.json", "sha256": common.digest(raw)},
            tools=[{"name": "cargo", "path": files[0]["path"], "sha256": files[0]["sha256"], "version": "1.97.1"}])

    def test_companion_modification_is_not_a_cache_hit(self):
        self.assertEqual(tool_inventory.check(self.root, self.descriptor, "linux-x86_64"), self.value["identity"])
        (self.root / "sdk/lib/library").write_bytes(b"different")
        with self.assertRaisesRegex(common.DevError, "companion-modified"):
            tool_inventory.check(self.root, self.descriptor, "linux-x86_64")

    def test_unrecorded_importable_file_is_rejected(self):
        (self.root / "recipe/injected.py").write_bytes(b"pass\n")
        with self.assertRaisesRegex(common.DevError, "unrecorded-file"):
            tool_inventory.check(self.root, self.descriptor, "linux-x86_64")

    def test_wrong_owner_host_and_template_revision_fail_before_execution(self):
        for change in (lambda v: v.update(language="c"), lambda v: v["template"].update(revision="b" * 40)):
            value = copy.deepcopy(self.descriptor)
            change(value)
            with self.assertRaises(common.DevError):
                tool_inventory.check(self.root, value, "linux-x86_64")
        with self.assertRaisesRegex(common.DevError, "owner-or-target"):
            tool_inventory.check(self.root, self.descriptor, "windows-x86_64")

    def test_verification_observes_cancellation(self):
        def cancelled():
            raise common.DevError("build-superseded")
        with self.assertRaisesRegex(common.DevError, "build-superseded"):
            tool_inventory.check(self.root, self.descriptor, "linux-x86_64", observe=cancelled)

    def test_adapter_requires_closed_inventory_and_tool_arguments(self):
        value = copy.deepcopy(self.descriptor)
        value["build"].update(adapter={"language": "rust", "ownerIssue": 544, "version": "1"}, argv=["cargo", "@tool:cargo"])
        project.validate(value)
        value["build"]["argv"][-1] = "@tool:missing"
        with self.assertRaisesRegex(common.DevError, "unknown-recipe-tool"):
            project.validate(value)
        value["build"]["argv"] = ["cargo"]
        del value["build"]["inventory"]
        with self.assertRaisesRegex(common.DevError, "adapter-owner-or-inventory"):
            project.validate(value)


class AdapterResults(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "private Linux Cargo cache modes")
    def test_readonly_distribution_seeds_a_writable_private_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir(mode=0o700)
            (source / "index").mkdir(mode=0o700)
            (source / "index/record").write_bytes(b"pinned-index")
            (source / "index").chmod(0o500)
            try:
                destination = root / "private-cache"
                stage_registry(source, destination, lambda: None)
                self.assertEqual((destination / "index").stat().st_mode & 0o777, 0o700)
                (destination / "index/owned-lock").write_bytes(b"lock")
                self.assertFalse((source / "index/owned-lock").exists())
                self.assertEqual((source / "index/record").read_bytes(), b"pinned-index")
            finally:
                (source / "index").chmod(0o700)

    def test_missing_nested_cleanup_receipt_remains_uncertain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "src").mkdir()
            (source / "src/probe.py").write_text("print('{}')\n", encoding="utf-8")
            value = descriptor()
            value["build"].update(argv=["python", "-I", "probe.py"], adapter={"language": "rust", "ownerIssue": 544, "version": "1"})
            with self.assertRaisesRegex(common.DevError, "adapter-result-invalid") as error:
                build.compile_recipe(root, source, value, {"identity": "selected", "files": [{"path": "src/probe.py"}]},
                    {"python": Path(sys.executable).resolve()}, time.monotonic() + 10, lambda: None)
            self.assertTrue(error.exception.uncertain)


class LargeInventory(unittest.TestCase):
    def test_cached_tool_manifest_uses_the_signed_inventory_bound(self):
        files = [{"path": f"sdk/library-{index:04}.bin", "sha256": "sha256:" + "a" * 64, "size": 1, "executable": False}
                 for index in range(2000)]
        files.extend({"path": name, "sha256": "sha256:" + "b" * 64, "size": 1, "executable": False}
                     for name in ("licenses/license.txt", "sbom.spdx.json"))
        value = {"schemaVersion": "latent.dev.bundle.v1", "version": "test", "sourceCommit": "a" * 40,
            "target": "linux-x86_64", "hostAbi": common.HOST_ABI, "protocol": common.PROTOCOL,
            "archive": {"name": "tools.zip", "size": 1, "sha256": "sha256:" + "c" * 64}, "files": files,
            "licenses": ["licenses/license.txt"], "sbom": "sbom.spdx.json"}
        raw = common.encode(value)
        self.assertGreater(len(raw), common.MAX_DOCUMENT)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths.write_new(root / "verified-bundle.json", raw)
            self.assertEqual(bundle.cached(root), value)


class ManagedCompilerInputs(unittest.TestCase):
    def fixture(self, root):
        from tools.dev_managed_distribution import pack
        inputs, sdk = root / "input", root / "sdk"
        (inputs / "lib").mkdir(parents=True)
        sdk.mkdir()
        (inputs / "lib/compiler.bin").write_bytes(b"captured compiler")
        (inputs / "cache-entry").write_bytes(b"immutable dependency")
        value = pack({"compiler": inputs}, sdk)
        return inputs, sdk, value

    def test_expansion_is_private_and_source_is_immutable(self):
        from tools.dev_managed_tools import unpack
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, sdk, _value = self.fixture(root)
            target = unpack(sdk, root / "attempt", lambda: None)
            self.assertEqual((target / "compiler/lib/compiler.bin").read_bytes(), b"captured compiler")
            (target / "compiler/cache-entry").write_bytes(b"private lock")
            self.assertEqual((inputs / "cache-entry").read_bytes(), b"immutable dependency")
            with self.assertRaisesRegex(common.DevError, "staging-must-be-fresh"):
                unpack(sdk, root / "attempt", lambda: None)

    def test_changed_member_and_path_escape_are_rejected(self):
        from tools.dev_managed_tools import manifest, unpack
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _inputs, sdk, value = self.fixture(root)
            for path in ("../outside", "/outside", "compiler/../outside"):
                changed = copy.deepcopy(value)
                changed["files"][0]["path"] = path
                with self.assertRaises(common.DevError):
                    manifest(changed)
            value["files"][0]["sha256"] = "sha256:" + "a" * 64
            value["identity"] = common.digest(common.encode({k: v for k, v in value.items() if k != "identity"}))
            (sdk / "managed-inputs.json").write_bytes(common.encode(value))
            with self.assertRaisesRegex(common.DevError, "file-digest"):
                unpack(sdk, root / "attempt", lambda: None)

    def test_expansion_observes_cancellation_and_finite_byte_budget(self):
        from tools.dev_managed_tools import manifest, unpack
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _inputs, sdk, value = self.fixture(root)
            def cancelled():
                raise common.DevError("build-superseded")
            with self.assertRaisesRegex(common.DevError, "build-superseded"):
                unpack(sdk, root / "attempt", cancelled)
            with patch("tools.dev_managed_tools.MAX_BYTES", 1):
                with self.assertRaisesRegex(common.DevError, "expanded-limit"):
                    manifest(value)

    @unittest.skipUnless(os.name == "posix", "Linux compiler distribution symlinks")
    def test_distribution_materializes_internal_links_and_rejects_external_links(self):
        from tools.dev_managed_distribution import pack
        from tools.dev_managed_tools import unpack
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "tool").write_bytes(b"actual compiler")
            (inputs / "alias").symlink_to("tool")
            sdk = root / "sdk"
            sdk.mkdir()
            pack({"compiler": inputs}, sdk)
            target = unpack(sdk, root / "attempt", lambda: None)
            self.assertFalse((target / "compiler/alias").is_symlink())
            self.assertEqual((target / "compiler/alias").read_bytes(), b"actual compiler")
            (root / "outside").write_bytes(b"not an input")
            (inputs / "escaped").symlink_to(root / "outside")
            other = root / "other"
            other.mkdir()
            with self.assertRaisesRegex(common.DevError, "link-escape"):
                pack({"compiler": inputs}, other)


class NativeDifferential(unittest.TestCase):
    def report(self, operating_system):
        applications = {}
        for name in ("greeting", "word-count", "shipping"):
            applications[name] = {"passed": True, "environment": "portable", "cleanup": "owned-native-host-reaped",
                "identity": {"artifacts": {"component": "sha256:" + "a" * 64}, "hostAbi": common.HOST_ABI,
                    "runtime": {"runs": [{"os": operating_system.lower(), "productionNode": False,
                                          "runtimeProfile": "standard-v1"}]}},
                "results": [{"id": name, "status": "passed", "outcomeKnown": True, "category": "success",
                             "inputSha256": "sha256:" + "b" * 64, "payloadSha256": "sha256:" + "c" * 64,
                             "platformCode": None}]}
        return {"schemaVersion": "latent.dev.portable-applications.v1", "os": operating_system, "passed": True,
            "execution": "actual-component-production-wasmtime", "compilerInExecutionPath": False,
            "outsideCheckout": True, "cleanup": "owned-processes-reaped", "language": "rust", "ownerIssue": 544,
            "applications": applications}

    def test_actual_bytes_component_and_native_host_must_all_match(self):
        from tools.compare_portable_guest_tests import compare
        windows, linux = self.report("Windows"), self.report("Linux")
        self.assertTrue(compare(common.encode(windows), common.encode(linux))["passed"])
        for mutate in (
            lambda r: r["applications"]["greeting"]["results"][0].update(payloadSha256="sha256:" + "d" * 64),
            lambda r: r["applications"]["greeting"]["identity"]["artifacts"].update(component="sha256:" + "d" * 64),
            lambda r: r["applications"]["greeting"]["results"][0].update(status="unsupported"),
            lambda r: r["applications"]["greeting"]["identity"]["runtime"]["runs"][0].update(os="windows"),
        ):
            changed = copy.deepcopy(linux)
            mutate(changed)
            with self.assertRaises(common.DevError):
                compare(common.encode(windows), common.encode(changed))


if __name__ == "__main__":
    unittest.main()
