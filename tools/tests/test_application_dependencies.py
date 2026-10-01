"""Hostile inputs and real offline materialization of captured native graphs."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.application_dependencies import MANIFEST, LOCK, capture, prepare, trust_inputs, validate_manifest
from tools.application_dependency_store import (
    DependencyError, Store, archive_files, captured_files, tree_identity,
)
from tools.application_dependency_tools import execute, specification
from tools.build_snapshot import canonical, digest


class Dependencies(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.library = self.root / "outside-private-library"
        self.library.mkdir()
        (self.library / "pure.c").write_bytes(b"int double_value(int x) { return x * 2; }\n")
        (self.project / "native.lock").write_bytes(b'{"direct":"unknown/1.2","transitive":"other/3.0"}')
        self.manifest = {"formatVersion": 1, "language": "c", "selection": {
            "target": "wasm32", "compiler": "zig-0.15.2", "runtimeProfile": "closed-c-v1", "features": ["pure"]},
            "nativeLocks": ["native.lock"], "artifacts": [{"id": "unknown/1.2", "role": "application",
                "format": "directory", "mount": "dependencies/unknown", "source": {"path": "../outside-private-library"},
                "dependencies": [], "metadata": {"license": "MIT", "scope": "runtime", "repository": "private-alias"}}],
            "transformations": []}

    def tearDown(self):
        self.temporary.cleanup()

    def write(self):
        (self.project / MANIFEST).write_bytes(canonical(self.manifest))

    def lock(self):
        self.write()
        result = capture(self.project)
        (self.project / LOCK).write_bytes(canonical(result))
        return result

    def build(self):
        work, output = self.root / "work", self.root / "output"
        work.mkdir(); output.mkdir()
        return prepare(self.project, work, output, "c")

    def test_unknown_private_local_library_offline_without_original(self):
        self.lock()
        (self.library / "pure.c").unlink()
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("network called")):
            closure = self.build()
            closure.check_unchanged()
        self.assertEqual((closure.work / "dependencies/unknown/pure.c").read_bytes(), b"int double_value(int x) { return x * 2; }\n")
        public = (self.root / "output/application-dependencies.json").read_text()
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("outside-private-library", public)
        self.assertEqual(trust_inputs(self.project)["applicationLock"], digest((self.project / LOCK).read_bytes()))

    def test_selected_feature_runtime_or_lock_change_invalidates(self):
        self.lock()
        self.manifest["selection"]["runtimeProfile"] = "changed-v2"
        self.write()
        with self.assertRaisesRegex(DependencyError, "lock-drift"):
            self.build()

    def test_native_resolution_changed(self):
        self.lock()
        (self.project / "native.lock").write_bytes(b"other graph")
        with self.assertRaisesRegex(DependencyError, "native-lock-drift"):
            self.build()

    def test_missing_or_same_name_changed_bytes_fails(self):
        lock = self.lock()
        row = lock["artifacts"][0]["files"][0]
        Store(self.project / "dependency-inputs/objects").path(row["digest"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(DependencyError, "integrity"):
            self.build()

    def test_after_compile_rechecks_materialized_and_original_inputs(self):
        self.lock()
        closure = self.build()
        (closure.work / "dependencies/unknown/pure.c").write_bytes(b"tampered output")
        with self.assertRaisesRegex(DependencyError, "output-mutated"):
            closure.check_unchanged()

    def test_automatic_transform_separates_preimage_and_selected_bytes(self):
        self.write()
        initial = capture(self.project)
        original = initial["artifacts"][0]
        replacement = b"int double_value(int x) { return x + x; }\n"
        (self.project / "runtime-port.c").write_bytes(replacement)
        store = Store(self.project / "dependency-inputs/objects")
        transformed = [{"path": "pure.c", **store.put(replacement)}]
        self.manifest["transformations"] = [{"id": "runtime-port/v1", "artifact": "unknown/1.2",
            "inputDigest": original["treeDigest"], "outputDigest": tree_identity(transformed),
            "files": [{"path": "pure.c", "inputDigest": original["files"][0]["digest"],
                       "source": "runtime-port.c", "outputDigest": digest(replacement)}],
            "tool": {"name": "captured-replacement", "version": "1"}, "selection": {"target": "wasm32"}}]
        lock = self.lock()
        self.assertNotEqual(lock["transformations"][0]["inputDigest"], lock["transformations"][0]["outputDigest"])
        closure = self.build()
        self.assertEqual((closure.work / "dependencies/unknown/pure.c").read_bytes(), replacement)
        closure.check_unchanged()

    def test_wrong_patch_preimage_does_not_apply(self):
        self.manifest["transformations"] = [{"id": "runtime-port/v1", "artifact": "unknown/1.2",
            "inputDigest": digest(b"wrong"), "outputDigest": digest(b"wrong"), "files": [{
                "path": "pure.c", "inputDigest": digest(b"wrong"), "source": "runtime-port.c", "outputDigest": digest(b"wrong")}],
            "tool": {"name": "capture", "version": "1"}, "selection": {}}]
        self.write()
        with self.assertRaisesRegex(DependencyError, "preimage"):
            capture(self.project)

    def test_source_only_projects_unchanged(self):
        self.assertIsNone(prepare(self.project, self.root, self.root, "c"))

    def test_graph_must_include_transitive_edges(self):
        self.manifest["artifacts"][0]["dependencies"] = ["not-captured/1.0"]
        with self.assertRaisesRegex(DependencyError, "not-closed"):
            validate_manifest(self.manifest)

    def test_private_registry_tokens_or_query_not_in_lock(self):
        self.manifest["artifacts"][0]["metadata"] = {"repository": "https://user:secret@example.com/x"}
        with self.assertRaisesRegex(DependencyError, "credentials"):
            validate_manifest(self.manifest)
        self.manifest["artifacts"][0]["metadata"] = {"token": "secret"}
        with self.assertRaisesRegex(DependencyError, "credentials"):
            validate_manifest(self.manifest)

    def test_build_tools_require_separate_approved_isolation(self):
        self.manifest["artifacts"][0]["role"] = "build-tool"
        self.lock()
        with self.assertRaisesRegex(DependencyError, "isolated-stage"):
            self.build()

    def test_generator_approval_denied_and_windows_isolation_fail_closed(self):
        executable = self.library / "generator"
        executable.write_bytes(b"#!/bin/sh\ncp /inputs/pure.c /outputs/out.c\n")
        selected = specification(executable, [], self.library, tool_version="1")
        with self.assertRaisesRegex(DependencyError, "approval"):
            execute(executable, [], self.library, self.root / "generated", self.root / "receipt.json",
                    tool_version="1", approved_identity=digest(b"wrong"))
        with patch("tools.application_dependency_tools.sys.platform", "win32"):
            with self.assertRaisesRegex(DependencyError, "host-unsupported"):
                execute(executable, [], self.library, self.root / "generated", self.root / "receipt.json",
                        tool_version="1", approved_identity=digest(canonical(selected)))

    def test_concurrent_writers_verify_all_objects(self):
        store = Store(self.root / "shared-cache")
        data = b"real immutable captured bytes" * 1000
        with ThreadPoolExecutor(max_workers=8) as workers:
            rows = list(workers.map(lambda _: store.put(data), range(24)))
        self.assertEqual(len({row["digest"] for row in rows}), 1)
        self.assertEqual(store.get(**rows[0]), data)
        self.assertFalse(list(store.root.rglob(".capture-*")))


class Archives(unittest.TestCase):
    def zip(self, rows):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, data in rows:
                info = zipfile.ZipInfo(name)
                info.filename = name  # Preserve hostile raw names on Windows.
                archive.writestr(info, data)
        return stream.getvalue()

    def test_zip_paths_and_case_prefix_collisions(self):
        for rows in [[("../escape", b"x")], [("/absolute", b"x")], [("C:/drive", b"x")],
                     [("X/a", b"x"), ("x/b", b"x")], [("a", b"x"), ("a/b", b"x")],
                     [("con", b"x")], [("x\\y", b"x")]]:
            with self.subTest(rows=rows):
                with self.assertRaises(DependencyError):
                    archive_files(self.zip(rows), "zip")

    def test_zip_link_denied(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "outside")
        with self.assertRaisesRegex(DependencyError, "entry-denied"):
            archive_files(stream.getvalue(), "zip")

    def test_tar_hardlinks_and_symlinks_denied(self):
        for kind in (tarfile.LNKTYPE, tarfile.SYMTYPE):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                info = tarfile.TarInfo("link"); info.type = kind; info.linkname = "../outside"
                archive.addfile(info)
            with self.assertRaisesRegex(DependencyError, "entry-denied"):
                archive_files(stream.getvalue(), "tar")

    def test_entry_and_decompression_bounds(self):
        with patch("tools.application_dependency_store.MAX_FILES", 1):
            with self.assertRaisesRegex(DependencyError, "entry-limit"):
                archive_files(self.zip([("a", b"x"), ("b", b"x")]), "zip")
        with patch("tools.application_dependency_store.MAX_EXPANDED", 10):
            with self.assertRaisesRegex(DependencyError, "byte-limit"):
                archive_files(self.zip([("a", b"x" * 11)]), "zip")


if __name__ == "__main__":
    unittest.main()
