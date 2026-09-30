"""Immutable packaged bytes, exact dependency attribution and hostile manifests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import guest_resources as resources
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_build import package_inputs

COMPONENT = b"\0asm component fixture bytes"
SOURCE = b"captured source inventory"


def manifest(rows):
    return encode({"schemaVersion": resources.PROFILE, "resources": rows})


def row(path="data/greeting.txt", source="assets/greeting.txt", media="text/plain"):
    return {"path": path, "source": source, "mediaType": media}


def captured():
    return {resources.MANIFEST: manifest([row()]), "assets/greeting.txt": "Hallo ☃\n".encode()}


def check(packaged, *, source=SOURCE, component=COMPONENT, dependency=None):
    return resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source),
                            component_digest=digest(component), manifest_digest=packaged.index["manifestDigest"],
                            dependency_lock_digest=dependency)


class ResourceCapture(unittest.TestCase):
    def test_declared_utf8_and_binary_bytes_preserve_content_and_metadata(self):
        files = captured()
        files[resources.MANIFEST] = manifest([row(), row("binary/data.bin", "assets/data.bin", "application/octet-stream")])
        files["assets/data.bin"] = b"\0\xff\xfe\x80\n"
        packaged = resources.capture(files, COMPONENT, SOURCE)
        value = check(packaged)
        self.assertEqual(value["count"], 2)
        self.assertEqual(value["bytes"], len(files["assets/greeting.txt"]) + len(files["assets/data.bin"]))
        self.assertEqual(packaged.objects[value["resources"][1]["object"]], files["assets/greeting.txt"])
        self.assertEqual(value["runtimeLookup"], "language-profile-qualification-required")
        self.assertEqual(value["scratchStorage"], "unsupported")

    def test_only_declared_files_are_captured_and_equal_bytes_share_an_object(self):
        files = captured()
        files["private.txt"] = b"must not be packaged"
        files[resources.MANIFEST] = manifest([row(), row("copy.txt")])
        packaged = resources.capture(files, COMPONENT, SOURCE)
        self.assertEqual(len(packaged.objects), 1)
        self.assertNotIn(b"must not be packaged", packaged.objects.values())
        self.assertEqual(check(packaged)["count"], 2)

    def test_resource_order_has_deterministic_selected_identity(self):
        files = captured()
        rows = [row(), row("copy.txt")]
        files[resources.MANIFEST] = manifest(rows)
        first = resources.capture(files, COMPONENT, SOURCE)
        # Input manifest identity intentionally changes with source order;
        # selected resource/object order remains deterministic.
        files[resources.MANIFEST] = manifest(list(reversed(rows)))
        second = resources.capture(files, COMPONENT, SOURCE)
        self.assertEqual(first.index["resources"], second.index["resources"])
        self.assertEqual(first.objects, second.objects)
        self.assertNotEqual(first.index["manifestDigest"], second.index["manifestDigest"])

    def test_missing_file_and_unobserved_host_path_fail_without_reading_host(self):
        files = captured()
        for source in ("missing.txt", "/etc/passwd", "../private.txt", "C:/private.txt", "encoded%2fpath"):
            files[resources.MANIFEST] = manifest([row(source=source)])
            with self.subTest(source=source), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, SOURCE)
        files[resources.MANIFEST] = manifest([row(source="missing.txt")])
        try:
            resources.capture(files, COMPONENT, SOURCE)
        except resources.ResourceError as error:
            self.assertEqual(error.category, "missing")

    def test_case_unicode_and_file_directory_collisions_are_rejected(self):
        for first, second in (("data/A.txt", "DATA/B.txt"), ("data/A.txt", "data/a.txt"),
                              ("data", "data/child"), ("data/child", "data")):
            files = captured()
            files[resources.MANIFEST] = manifest([row(path=first), row(path=second)])
            with self.subTest(first=first, second=second), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, SOURCE)
        with self.assertRaisesRegex(resources.ResourceError, "not-normalized"):
            resources.name("data/cafe\u0301.txt")
        with self.assertRaisesRegex(resources.ResourceError, "encoding"):
            resources.name("\ud800")

    def test_media_and_closed_manifest_schema_cannot_be_extended_implicitly(self):
        files = captured()
        for value in ({"schemaVersion": "other", "resources": []},
                      {"schemaVersion": resources.PROFILE, "resources": [], "filesystemFallback": True},
                      {"schemaVersion": resources.PROFILE, "resources": [{**row(), "permission": "host-read"}]},
                      {"schemaVersion": resources.PROFILE, "resources": [row(media="text/plain; private=secret")]}):
            files[resources.MANIFEST] = encode(value)
            with self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, SOURCE)

    def test_count_name_file_and_aggregate_limits_are_enforced(self):
        from unittest.mock import patch
        files = captured()
        files[resources.MANIFEST] = manifest([row(path=str(number)) for number in range(resources.MAX_COUNT + 1)])
        with self.assertRaisesRegex(resources.ResourceError, "count-limit"):
            resources.capture(files, COMPONENT, SOURCE)
        with self.assertRaisesRegex(resources.ResourceError, "name-limit"):
            resources.name("a" * (resources.MAX_NAME + 1))
        files[resources.MANIFEST] = manifest([row()])
        with patch.object(resources, "MAX_FILE", 1), self.assertRaisesRegex(resources.ResourceError, "byte-limit"):
            resources.capture(files, COMPONENT, SOURCE)
        with patch.object(resources, "MAX_TOTAL", 1), self.assertRaisesRegex(resources.ResourceError, "byte-limit"):
            resources.capture(files, COMPONENT, SOURCE)

    def test_source_component_and_dependency_changes_invalidate_resource_identity(self):
        files = captured()
        packaged = resources.capture(files, COMPONENT, SOURCE)
        for values in ({"source": b"different source"}, {"component": b"different component"},
                       {"dependency": digest(b"new lock")}):
            with self.subTest(values=values), self.assertRaisesRegex(resources.ResourceError, "source-binding"):
                check(packaged, **values)
        with self.assertRaisesRegex(resources.ResourceError, "source-binding"):
            resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(SOURCE),
                component_digest=digest(COMPONENT), manifest_digest=digest(b"changed declaration manifest"))

    def test_tamper_missing_object_or_unlisted_object_fails_exact_inventory(self):
        packaged = resources.capture(captured(), COMPONENT, SOURCE)
        path = next(iter(packaged.objects))
        for objects, code in (({path: b"same path new bytes"}, "integrity"), ({}, "missing"),
                              ({**packaged.objects, "extra": b"unlisted"}, "inventory")):
            with self.subTest(code=code), self.assertRaisesRegex(resources.ResourceError, code):
                resources.verify(encode(packaged.index), objects, source_digest=digest(SOURCE), component_digest=digest(COMPONENT),
                                 manifest_digest=digest(captured()[resources.MANIFEST]))
        changed = {**packaged.index, "scratchStorage": "host-tmp"}
        changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
        with self.assertRaisesRegex(resources.ResourceError, "profile"):
            resources.verify(encode(changed), packaged.objects, source_digest=digest(SOURCE), component_digest=digest(COMPONENT),
                             manifest_digest=digest(captured()[resources.MANIFEST]))

    def test_transitive_resource_owner_and_bytes_must_belong_to_reviewed_capture(self):
        payload = b"transitive private package data\n"
        lock = {"artifacts": [{"id": "private:transitive:2.0", "files": [{"path": "data.txt", "digest": digest(payload), "size": len(payload)}]}]}
        files = {"latent.dependencies.lock.json": encode(lock), "dependencies/java-resources/data.txt": payload}
        additional = {**row("data.txt", "dependencies/java-resources/data.txt"), "digest": digest(payload), "owner": "private:transitive:2.0"}
        packaged = resources.capture(files, COMPONENT, SOURCE, additional_resources=[additional])
        self.assertEqual(check(packaged, dependency=digest(files["latent.dependencies.lock.json"]))["resources"][0]["origin"], "dependency")
        for key, value in (("owner", "private:not-captured:1.0"), ("digest", digest(b"changed"))):
            with self.subTest(key=key), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, SOURCE, additional_resources=[{**additional, key: value}])

    def test_forged_dependency_mapping_without_lock_cannot_package_bytes(self):
        files = {"data.txt": b"outside unverified data"}
        additional = {**row("data.txt", "data.txt"), "digest": digest(files["data.txt"]), "owner": "external:unknown:1.0"}
        with self.assertRaisesRegex(resources.ResourceError, "lock-missing"):
            resources.capture(files, COMPONENT, SOURCE, additional_resources=[additional])

    def test_six_language_package_inputs_include_index_and_original_bytes(self):
        for language in ("rust", "c", "java", "go", "typescript", "dotnet"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                files = {**captured(), "sdk-lock.json": encode({"language": language}),
                         "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n'}
                project = {"name": "resource-fixture", "tenant": "examples", "service": "examples/resource-fixture",
                           "world": "examples:resource-fixture/service@1.0.0", "version": "1.0.0", "limits": {}}
                (output / "source-inputs.json").write_bytes(SOURCE)
                package_inputs(output, project, {"imports": [], "exports": []}, files, COMPONENT)
                source = json.loads((output / "package-source.json").read_bytes())
                layers = {item["path"]: item for item in source["layers"]}
                self.assertEqual(layers[resources.INDEX]["role"], "asset")
                index = json.loads((output / resources.INDEX).read_bytes())
                objects = {item["object"]: (output / item["object"]).read_bytes() for item in index["resources"]}
                resources.verify((output / resources.INDEX).read_bytes(), objects,
                                 source_digest=digest(SOURCE), component_digest=digest(COMPONENT),
                                 manifest_digest=digest(files[resources.MANIFEST]))
                self.assertEqual(list(objects.values()), [files["assets/greeting.txt"]])

    def test_source_only_and_declared_empty_resource_behavior(self):
        self.assertIsNone(resources.capture({}, COMPONENT, SOURCE))
        packaged = resources.capture({resources.MANIFEST: manifest([])}, COMPONENT, SOURCE)
        self.assertEqual(check(packaged)["count"], 0)

    def test_developer_resource_selection_changes_trust_and_bytes_change_watch(self):
        from tools.dev_workflow import project, resource_inputs, snapshot
        from tools.tests.test_dev_contracts import descriptor
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src/main.rs").write_bytes(b"captured source")
            (root / "assets").mkdir()
            (root / "assets/greeting.txt").write_bytes(b"first resource")
            (root / resources.MANIFEST).write_bytes(manifest([row()]))
            (root / "latent.project.json").write_bytes(encode(descriptor()))
            selected, _ = project.load(root)
            before, _ = snapshot.observe(root, selected["inputRoots"])
            resource_inputs.verify(root, selected)
            self.assertIn(resources.MANIFEST, selected["inputRoots"])
            self.assertIn("assets/greeting.txt", selected["inputRoots"])
            (root / "assets/greeting.txt").write_bytes(b"changed resource")
            changed, _ = project.load(root)
            self.assertEqual(project.trust_identity(selected), project.trust_identity(changed))
            self.assertNotEqual(before["identity"], snapshot.observe(root, changed["inputRoots"])[0]["identity"])
            (root / resources.MANIFEST).write_bytes(manifest([row(media="application/octet-stream")]))
            changed, _ = project.load(root)
            self.assertNotEqual(project.trust_identity(selected), project.trust_identity(changed))

    def test_missing_or_excluded_resources_cannot_reuse_approved_snapshot(self):
        from tools.dev_workflow import common, project, resource_inputs
        from tools.tests.test_dev_contracts import descriptor
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / resources.MANIFEST).write_bytes(manifest([row()]))
            value = descriptor()
            (root / "latent.project.json").write_bytes(encode(value))
            selected, _ = project.load(root)
            with self.assertRaisesRegex(common.DevError, "source-file-unavailable|windows-protected-open-failed"):
                resource_inputs.verify(root, selected)
            selected.pop("resourceInputs")
            with self.assertRaisesRegex(common.DevError, "resource-trust-binding-drift"):
                resource_inputs.verify(root, selected)
            value["exclude"] = ["assets"]
            (root / "latent.project.json").write_bytes(encode(value))
            with self.assertRaisesRegex(common.DevError, "resource-input-excluded"):
                project.load(root)
