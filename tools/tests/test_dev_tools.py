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


class CompilerDownloadBounds(unittest.TestCase):
    def setUp(self):
        import hashlib
        from tools import build_dev_guest_tools
        self.builder = build_dev_guest_tools
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive"
        self.data = b"verified compiler bytes"
        self.source = {"url": "https://example.invalid/compiler", "maximum": len(self.data),
                       "sha256": "sha256:" + hashlib.sha256(self.data).hexdigest()}

    def transfer(self, *, data=None, elapsed=0):
        import io
        from unittest.mock import Mock
        stream = io.BytesIO(self.data if data is None else data)
        self.clock = 0
        def read(size):
            self.clock = elapsed
            return stream.read(size)
        incoming = Mock()
        incoming.__enter__ = Mock(return_value=incoming)
        incoming.__exit__ = Mock(return_value=False)
        incoming.read1.side_effect = read
        with patch.object(self.builder.urllib.request, "urlopen", return_value=incoming) as opened, \
                patch.object(self.builder.time, "monotonic", side_effect=lambda: self.clock):
            self.builder.download(self.path, self.source)
        opened.assert_called_once_with(self.source["url"], timeout=min(30, self.source.get("timeoutSeconds", self.builder.DOWNLOAD_TIMEOUT_SECONDS)))
        self.assertTrue(all(0 < call.args[0] <= len(self.data) + 1 for call in incoming.read1.call_args_list))

    def test_small_default_transfer_accepts_only_pinned_bytes(self):
        self.transfer(elapsed=89)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_pinned_zig_transfer_can_exceed_small_archive_deadline(self):
        pin = self.builder.SOURCES["zig"]
        self.assertEqual((pin["maximum"], pin["sha256"]),
                         (self.builder.ZIG_BYTES, "sha256:" + self.builder.ZIG_SHA256))
        self.assertEqual(pin["timeoutSeconds"], self.builder.DOWNLOAD_TIMEOUT_SECONDS)
        self.source["timeoutSeconds"] = pin["timeoutSeconds"]
        self.transfer(elapsed=120)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertTrue(all("timeoutSeconds" not in source for name, source in self.builder.SOURCES.items() if name != "zig"))

    def test_default_deadline_is_not_extended(self):
        with self.assertRaisesRegex(common.DevError, "compiler-download-deadline"):
            self.transfer(elapsed=self.builder.DOWNLOAD_TIMEOUT_SECONDS)
        self.assertFalse(self.path.exists())

    def test_large_archive_deadline_still_rejects_at_boundary(self):
        self.source["timeoutSeconds"] = 300
        with self.assertRaisesRegex(common.DevError, "compiler-download-deadline"):
            self.transfer(elapsed=300)
        self.assertFalse(self.path.exists())

    def test_eof_cannot_hide_an_expired_deadline(self):
        with self.assertRaisesRegex(common.DevError, "compiler-download-deadline"):
            self.transfer(data=b"", elapsed=self.builder.DOWNLOAD_TIMEOUT_SECONDS)

    def test_one_extra_byte_is_rejected_before_writing_or_digesting(self):
        with patch.object(self.builder, "file_digest") as digest:
            with self.assertRaisesRegex(common.DevError, "compiler-download-byte-limit"):
                self.transfer(data=self.data + b"!")
            digest.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_truncated_changed_and_empty_archives_still_fail_digest(self):
        for data in (self.data[:-1], b"x" * len(self.data), b""):
            with self.subTest(data=data):
                self.path.unlink(missing_ok=True)
                with self.assertRaises(common.DevError):
                    self.transfer(data=data)

    def test_invalid_limits_fail_before_network_or_output(self):
        for field, values in (("timeoutSeconds", (0, -1, 601, True, 90.0, "90")),
                              ("maximum", (0, -1, False, "100"))):
            for value in values:
                source = dict(self.source, **{field: value})
                with self.subTest(field=field, value=value), \
                        patch.object(self.builder.urllib.request, "urlopen") as opened:
                    with self.assertRaises(common.DevError):
                        self.builder.download(self.path, source)
                    opened.assert_not_called()
                    self.assertFalse(self.path.exists())

    def test_existing_file_and_symlink_are_not_replaced(self):
        target = self.path.with_name("target")
        target.write_bytes(b"unrelated")
        for linked in (False, True):
            with self.subTest(linked=linked):
                self.path.unlink(missing_ok=True)
                if linked:
                    self.path.symlink_to(target)
                else:
                    self.path.write_bytes(b"prior")
                with patch.object(self.builder.urllib.request, "urlopen") as opened:
                    with self.assertRaises(FileExistsError):
                        self.builder.download(self.path, self.source)
                    opened.assert_not_called()
                self.assertEqual(target.read_bytes(), b"unrelated")
                self.assertEqual(self.path.read_bytes(), b"unrelated" if linked else b"prior")

    def test_network_failure_is_not_retried(self):
        failure = TimeoutError("synthetic socket timeout")
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=failure) as opened:
            with self.assertRaises(TimeoutError) as caught:
                self.builder.download(self.path, self.source)
            self.assertIs(caught.exception, failure)
            self.assertEqual(opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
