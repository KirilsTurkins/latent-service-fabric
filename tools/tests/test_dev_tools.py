"""Companion integrity and typed cleanup at the language-owned adapter boundary."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from tools.dev_workflow import build, bundle, common, paths, project, tool_inventory
from tools.dev_guest_tools import stage_registry
from tools.tests.test_dev_contracts import descriptor


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


if __name__ == "__main__":
    unittest.main()
