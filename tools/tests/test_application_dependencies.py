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

    def test_empty_captured_directory_is_materialized_offline_and_rechecked(self):
        (self.library / "pure.c").unlink()
        self.lock()
        self.library.rmdir()
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("network called")):
            closure = self.build()
            destination = closure.work / "dependencies/unknown"
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])
            closure.check_unchanged()
        (destination / "uncaptured.c").write_bytes(b"int changed;\n")
        with self.assertRaisesRegex(DependencyError, "unobserved-materialized-input"):
            closure.check_unchanged()

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

    def test_literal_exclamation_names_roundtrip_without_interpretation(self):
        from tools.application_dependency_store import directory_files, materialize

        files = {"testdata/expect/yo!.go": b"package expect\n", "data/!name!.txt": b"literal bytes"}
        selected = archive_files(self.zip(list(files.items())), "zip")
        self.assertEqual(selected, files)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "store")
            inventory = captured_files(selected, store)
            self.assertEqual({row["path"] for row in inventory}, set(files))
            materialize(inventory, root / "offline", store)
            self.assertEqual(directory_files(root / "offline"), files)
            self.assertNotEqual(tree_identity(inventory), tree_identity(captured_files(
                {name.replace("!", ""): data for name, data in files.items()}, store)))
        for rows in [[("../yo!.go", b"x")], [("/yo!.go", b"x")],
                     [("C:/yo!.go", b"x")], [("x\\yo!.go", b"x")],
                     [("Expect/yo!.go", b"x"), ("expect/other.go", b"y")],
                     [("yo!", b"x"), ("yo!/child", b"y")],
                     [("yo!.go", b"x"), ("yo!.go", b"y")]]:
            with self.subTest(rows=rows), self.assertRaises(DependencyError):
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

    def test_zip_empty_unix_directory_sentinel_preserves_files(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name in ("META-INF/maven/", "META-INF/maven/ordinary/",
                         "META-INF/maven/ordinary/library/"):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = 0xffff0010
                archive.writestr(info, b"")
            archive.writestr("META-INF/maven/ordinary/library/pom.xml", b"original metadata")
            archive.writestr("ordinary/Library.class", b"original class")
        self.assertEqual(archive_files(stream.getvalue(), "zip"), {
            "META-INF/maven/ordinary/library/pom.xml": b"original metadata",
            "ordinary/Library.class": b"original class",
        })
        with patch("tools.application_dependency_store.MAX_FILES", 2):
            with self.assertRaisesRegex(DependencyError, "entry-limit"):
                archive_files(stream.getvalue(), "zip")

    def test_zip_directory_sentinel_keeps_hostile_entry_guards(self):
        cases = [("marker", 3, 0xffff0010, b"", None),
                 ("marker/", 0, 0xffff0010, b"", None),
                 ("marker/", 3, 0xffff0000, b"", None),
                 ("marker/", 3, 0xffff0010, b"payload", None),
                 ("../escape/", 3, 0xffff0010, b"", None),
                 ("Marker/", 3, 0xffff0010, b"", "marker/file"),
                 ("parent/child/", 3, 0xffff0010, b"", "parent")]
        cases.extend(("marker/", 3, (kind | 0o777) << 16 | 0x10, b"", None)
                     for kind in (stat.S_IFLNK, stat.S_IFBLK, stat.S_IFCHR, stat.S_IFIFO))
        for name, system, attributes, payload, other in cases:
            with self.subTest(name=name, system=system, attributes=attributes, payload=payload, other=other):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    info = zipfile.ZipInfo(name)
                    info.create_system = system
                    info.external_attr = attributes
                    archive.writestr(info, payload)
                    if other:
                        archive.writestr(other, b"file")
                with self.assertRaises(DependencyError):
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


class TransformedClosureRechecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project, source = root / "project", root / "original-library"
        self.project.mkdir(); source.mkdir()
        (source / "pure.c").write_bytes(b"int value(void) { return 1; }\n")
        (self.project / "native.lock").write_bytes(b"unknown-library/1.0.0")
        manifest = {"formatVersion": 1, "language": "c", "selection": {"target": "wasm32"},
                    "nativeLocks": ["native.lock"], "artifacts": [{"id": "unknown-library/1.0.0",
                    "role": "application", "format": "directory", "mount": "dependencies/library",
                    "source": {"path": "../original-library"}, "dependencies": [], "metadata": {}}],
                    "transformations": []}
        (self.project / MANIFEST).write_bytes(canonical(manifest))
        initial = capture(self.project)["artifacts"][0]
        self.original = initial["files"][0]
        self.store = Store(self.project / "dependency-inputs/objects")
        before = initial
        for ordinal in (2, 3):
            payload = f"int value(void) {{ return {ordinal}; }}\n".encode()
            replacement = self.project / f"runtime-port-{ordinal}.c"
            replacement.write_bytes(payload)
            after = {"path": "pure.c", **self.store.put(payload)}
            manifest["transformations"].append({"id": f"runtime-port/v{ordinal}",
                "artifact": "unknown-library/1.0.0", "inputDigest": before["treeDigest"],
                "outputDigest": tree_identity([after]), "files": [{"path": "pure.c",
                "inputDigest": before["files"][0]["digest"], "source": replacement.name,
                "outputDigest": after["digest"]}], "tool": {"name": "captured-replacement", "version": "1"},
                "selection": {"target": "wasm32"}})
            before = {"treeDigest": tree_identity([after]), "files": [after]}
            if ordinal == 2:
                self.intermediate = after
        (self.project / MANIFEST).write_bytes(canonical(manifest))
        (self.project / LOCK).write_bytes(canonical(capture(self.project)))
        self.documents = {name: (self.project / name).read_bytes() for name in (MANIFEST, LOCK, "native.lock")}
        (source / "pure.c").unlink(); source.rmdir()
        self.assertFalse(source.exists())
        work, output = root / "work", root / "output"
        work.mkdir(); output.mkdir()
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("offline build fetched")):
            self.closure = prepare(self.project, work, output, "c")
        self.receipt_path = output / "application-dependencies.json"
        self.receipt_bytes = self.receipt_path.read_bytes()
        self.selected = before["files"][0]

    def unchanged_selection(self):
        self.assertEqual((self.closure.work / "dependencies/library/pure.c").read_bytes(),
                         b"int value(void) { return 3; }\n")
        self.assertEqual(self.receipt_path.read_bytes(), self.receipt_bytes)
        self.assertEqual({name: (self.project / name).read_bytes() for name in self.documents}, self.documents)

    def test_changed_original_directory_preimage_refuses_post_build_success(self):
        self.store.path(self.original["digest"]).write_bytes(b"changed original preimage")
        with self.assertRaisesRegex(DependencyError, "dependency-artifact-integrity"):
            self.closure.check_unchanged()
        self.unchanged_selection()

    def test_missing_original_directory_preimage_refuses_post_build_success(self):
        self.store.path(self.original["digest"]).unlink()
        with self.assertRaisesRegex(DependencyError, "dependency-artifact-missing-resolve-explicitly"):
            self.closure.check_unchanged()
        self.unchanged_selection()

    def test_changed_intermediate_transform_refuses_post_build_success(self):
        self.store.path(self.intermediate["digest"]).write_bytes(b"changed intermediate output")
        with self.assertRaisesRegex(DependencyError, "dependency-patch-output-mismatch"):
            self.closure.check_unchanged()
        self.unchanged_selection()

    def test_valid_transformation_chain_stays_offline_without_original_sources(self):
        with patch("tools.application_dependencies.fetch", side_effect=AssertionError("offline recheck fetched")):
            self.closure.check_unchanged()
        self.assertEqual(self.store.get(self.original["digest"], self.original["size"]),
                         b"int value(void) { return 1; }\n")
        self.assertEqual(self.store.get(self.intermediate["digest"], self.intermediate["size"]),
                         b"int value(void) { return 2; }\n")
        receipt = json.loads(self.receipt_bytes)
        self.assertEqual(len(receipt["transformations"]), 2)
        self.assertEqual(receipt["artifacts"][0]["files"], [self.selected])
        self.assertFalse(receipt["networkResolution"])
        self.assertFalse(receipt["hermetic"])
        self.unchanged_selection()


if __name__ == "__main__":
    unittest.main()
