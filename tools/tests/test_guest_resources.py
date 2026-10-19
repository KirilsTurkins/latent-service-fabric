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
from tools.rust_capsule_project import inventory

COMPONENT = b"\0asm component fixture bytes"


def manifest(rows):
    return encode({"schemaVersion": resources.PROFILE, "resources": rows})


def row(path="data/greeting.txt", source="assets/greeting.txt", media="text/plain"):
    return {"path": path, "source": source, "mediaType": media}


def captured():
    return {resources.MANIFEST: manifest([row()]), "assets/greeting.txt": "Hallo ☃\n".encode()}


def source_inputs(files):
    # This fixture's dependency capture has its own lock binding, separate
    # from the application snapshot whose resource membership is under test.
    return inventory({path: data for path, data in files.items()
                      if path != "latent.dependencies.lock.json" and not path.startswith("dependencies/")})


def check(packaged, *, source=None, component=COMPONENT, dependency=None, files=None):
    files = captured() if files is None else files
    return resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files) if source is None else source),
                            source_inventory=source_inputs(files),
                            component_digest=digest(component), manifest_digest=packaged.index["manifestDigest"],
                            dependency_lock_digest=dependency, manifest=files.get(resources.MANIFEST))


class ResourceCapture(unittest.TestCase):
    def test_windows_superscript_device_aliases_are_rejected_in_paths_and_sources(self):
        for prefix in ("COM", "com", "LPT", "lPt"):
            for digit in ("\u00b9", "\u00b2", "\u00b3"):
                alias = prefix + digit
                for name in (alias, alias + ".txt", "data/" + alias + ".txt", "data/" + alias + "/file.txt"):
                    for field in ("path", "source"):
                        files = captured()
                        declaration = {**row(), field: name}
                        files[resources.MANIFEST] = manifest([declaration])
                        if field == "source":
                            files[name] = files["assets/greeting.txt"]
                        original = copy.deepcopy(files)
                        with self.subTest(name=name, field=field):
                            with self.assertRaises(resources.ResourceError) as raised:
                                resources.capture(files, COMPONENT, source_inputs(files))
                            self.assertEqual((raised.exception.category, raised.exception.code),
                                             ("denied", "resource-name-alias-or-traversal"))
                            self.assertEqual(files, original)

    def test_rehashed_resource_indexes_cannot_adopt_superscript_device_aliases(self):
        packaged = resources.capture(captured(), COMPONENT, source_inputs(captured()))
        for name in ("COM\u00b9.txt", "LPT\u00b2", "data/COM\u00b3/file.txt"):
            changed = copy.deepcopy(packaged.index)
            changed["resources"][0]["path"] = name
            changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
            with self.subTest(name=name), self.assertRaisesRegex(resources.ResourceError, "alias-or-traversal"):
                resources.verify(encode(changed), packaged.objects, source_digest=digest(source_inputs(captured())), source_inventory=source_inputs(captured()),
                    component_digest=digest(COMPONENT), manifest_digest=packaged.index["manifestDigest"])

    def test_valid_unicode_and_undeclared_device_names_keep_the_original_selection_rules(self):
        names = ("data/caf\u00e9.txt", "data/document\u00b9.txt", "data/COM\u00b9note.txt", "data/COM10.txt")
        source = "assets/caf\u00e9\u00b2.txt"
        payload = b"\x00\xffexact immutable bytes\n"
        files = {resources.MANIFEST: manifest([row(path=name, source=source) for name in names]), source: payload,
                 "COM\u00b9.txt": b"undeclared bytes must not be packaged"}
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        self.assertEqual([row["path"] for row in check(packaged, files=files)["resources"]], sorted(names))
        self.assertEqual(list(packaged.objects.values()), [payload])
        self.assertIsNone(resources.select({"COM\u00b9.txt": b"undeclared"}))
        undeclared = {"LPT\u00b2": b"undeclared"}
        self.assertIsNone(resources.capture(undeclared, COMPONENT, source_inputs(undeclared)))

    def test_declared_utf8_and_binary_bytes_preserve_content_and_metadata(self):
        files = captured()
        files[resources.MANIFEST] = manifest([row(), row("binary/data.bin", "assets/data.bin", "application/octet-stream")])
        files["assets/data.bin"] = b"\0\xff\xfe\x80\n"
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        value = check(packaged, files=files)
        self.assertEqual(value["count"], 2)
        self.assertEqual(value["bytes"], len(files["assets/greeting.txt"]) + len(files["assets/data.bin"]))
        self.assertEqual(packaged.objects[value["resources"][1]["object"]], files["assets/greeting.txt"])
        self.assertEqual(value["runtimeLookup"], "language-profile-qualification-required")
        self.assertEqual(value["scratchStorage"], "unsupported")

    def test_only_declared_files_are_captured_and_equal_bytes_share_an_object(self):
        files = captured()
        files["private.txt"] = b"must not be packaged"
        files[resources.MANIFEST] = manifest([row(), row("copy.txt")])
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        self.assertEqual(len(packaged.objects), 1)
        self.assertNotIn(b"must not be packaged", packaged.objects.values())
        self.assertEqual(check(packaged, files=files)["count"], 2)

    def test_resource_order_has_deterministic_selected_identity(self):
        files = captured()
        rows = [row(), row("copy.txt")]
        files[resources.MANIFEST] = manifest(rows)
        first = resources.capture(files, COMPONENT, source_inputs(files))
        # Input manifest identity intentionally changes with source order;
        # selected resource/object order remains deterministic.
        files[resources.MANIFEST] = manifest(list(reversed(rows)))
        second = resources.capture(files, COMPONENT, source_inputs(files))
        self.assertEqual(first.index["resources"], second.index["resources"])
        self.assertEqual(first.objects, second.objects)
        self.assertNotEqual(first.index["manifestDigest"], second.index["manifestDigest"])

    def test_rehashed_index_cannot_reorder_selected_resources(self):
        files = captured()
        files[resources.MANIFEST] = manifest([row(), row("copy.txt")])
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        self.assertEqual([item["path"] for item in packaged.index["resources"]],
                         ["copy.txt", "data/greeting.txt"])
        changed = copy.deepcopy(packaged.index)
        changed["resources"].reverse()
        changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
        with self.assertRaisesRegex(resources.ResourceError, "resource-index-order"):
            check(resources.PackagedResources(changed, packaged.objects), files=files)

    def test_missing_file_and_unobserved_host_path_fail_without_reading_host(self):
        files = captured()
        for source in ("missing.txt", "/etc/passwd", "../private.txt", "C:/private.txt", "encoded%2fpath"):
            files[resources.MANIFEST] = manifest([row(source=source)])
            with self.subTest(source=source), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, source_inputs(files))
        files[resources.MANIFEST] = manifest([row(source="missing.txt")])
        try:
            resources.capture(files, COMPONENT, source_inputs(files))
        except resources.ResourceError as error:
            self.assertEqual(error.category, "missing")

    def test_case_unicode_and_file_directory_collisions_are_rejected(self):
        for first, second in (("data/A.txt", "DATA/B.txt"), ("data/A.txt", "data/a.txt"),
                              ("data", "data/child"), ("data/child", "data")):
            files = captured()
            files[resources.MANIFEST] = manifest([row(path=first), row(path=second)])
            with self.subTest(first=first, second=second), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, source_inputs(files))
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
                resources.capture(files, COMPONENT, source_inputs(files))

    def test_count_name_file_and_aggregate_limits_are_enforced(self):
        from unittest.mock import patch
        files = captured()
        files[resources.MANIFEST] = manifest([row(path=str(number)) for number in range(resources.MAX_COUNT + 1)])
        with self.assertRaisesRegex(resources.ResourceError, "count-limit"):
            resources.capture(files, COMPONENT, source_inputs(files))
        with self.assertRaisesRegex(resources.ResourceError, "name-limit"):
            resources.name("a" * (resources.MAX_NAME + 1))
        files[resources.MANIFEST] = manifest([row()])
        with patch.object(resources, "MAX_FILE", 1), self.assertRaisesRegex(resources.ResourceError, "byte-limit"):
            resources.capture(files, COMPONENT, source_inputs(files))
        with patch.object(resources, "MAX_TOTAL", 1), self.assertRaisesRegex(resources.ResourceError, "byte-limit"):
            resources.capture(files, COMPONENT, source_inputs(files))

    def test_source_component_and_dependency_changes_invalidate_resource_identity(self):
        files = captured()
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        for values in ({"source": b"different source"}, {"component": b"different component"},
                       {"dependency": digest(b"new lock")}):
            with self.subTest(values=values), self.assertRaisesRegex(resources.ResourceError, "source-binding"):
                check(packaged, **values)
        with self.assertRaisesRegex(resources.ResourceError, "source-binding"):
            resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                component_digest=digest(COMPONENT), manifest_digest=digest(b"changed declaration manifest"))

    def test_tamper_missing_object_or_unlisted_object_fails_exact_inventory(self):
        packaged = resources.capture(captured(), COMPONENT, source_inputs(captured()))
        path = next(iter(packaged.objects))
        for objects, code in (({path: b"same path new bytes"}, "integrity"), ({}, "missing"),
                              ({**packaged.objects, "extra": b"unlisted"}, "inventory")):
            with self.subTest(code=code), self.assertRaisesRegex(resources.ResourceError, code):
                resources.verify(encode(packaged.index), objects, source_digest=digest(source_inputs(captured())), source_inventory=source_inputs(captured()), component_digest=digest(COMPONENT),
                                 manifest_digest=digest(captured()[resources.MANIFEST]), manifest=captured()[resources.MANIFEST])
        changed = {**packaged.index, "scratchStorage": "host-tmp"}
        changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
        with self.assertRaisesRegex(resources.ResourceError, "profile"):
            resources.verify(encode(changed), packaged.objects, source_digest=digest(source_inputs(captured())), source_inventory=source_inputs(captured()), component_digest=digest(COMPONENT),
                             manifest_digest=digest(captured()[resources.MANIFEST]))

    def test_transitive_resource_owner_and_bytes_must_belong_to_reviewed_capture(self):
        payload = b"transitive private package data\n"
        lock = {"artifacts": [{"id": "private:transitive:2.0", "files": [{"path": "data.txt", "digest": digest(payload), "size": len(payload)}]}]}
        files = {"latent.dependencies.lock.json": encode(lock), "dependencies/java-resources/data.txt": payload}
        additional = {**row("data.txt", "dependencies/java-resources/data.txt"), "digest": digest(payload), "owner": "private:transitive:2.0"}
        packaged = resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])
        value = resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                                 component_digest=digest(COMPONENT), dependency_lock_digest=digest(files["latent.dependencies.lock.json"]),
                                 dependency_lock=files["latent.dependencies.lock.json"])
        self.assertEqual(value["resources"][0]["origin"], "dependency")
        for key, value in (("owner", "private:not-captured:1.0"), ("digest", digest(b"changed"))):
            with self.subTest(key=key), self.assertRaises(resources.ResourceError):
                resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[{**additional, key: value}])

    def test_rehashed_dependency_index_cannot_adopt_ambiguous_owner(self):
        payload = b"captured transitive bytes"
        owner = "private:transitive:2.0"
        lock = {"artifacts": [{"id": owner, "files": [{"path": "data.txt", "digest": digest(payload), "size": len(payload)}]}]}
        files = {"latent.dependencies.lock.json": encode(lock), "dependencies/java-resources/data.txt": payload}
        additional = {**row("data.txt", "dependencies/java-resources/data.txt"), "digest": digest(payload), "owner": owner}
        packaged = resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])
        for forged in ("private:other..owner:2.0", "private:other//owner:2.0"):
            changed = copy.deepcopy(packaged.index)
            changed["resources"][0]["owner"] = forged
            changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
            with self.subTest(owner=forged), self.assertRaisesRegex(resources.ResourceError, "resource-index-origin"):
                resources.verify(encode(changed), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                    component_digest=digest(COMPONENT), dependency_lock_digest=digest(files["latent.dependencies.lock.json"]))

    def test_forged_dependency_mapping_without_lock_cannot_package_bytes(self):
        files = {"data.txt": b"outside unverified data"}
        additional = {**row("data.txt", "data.txt"), "digest": digest(files["data.txt"]), "owner": "external:unknown:1.0"}
        with self.assertRaisesRegex(resources.ResourceError, "lock-missing"):
            resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])

    def test_dependency_origin_requires_bound_lock_even_after_index_rehash(self):
        packaged = resources.capture(captured(), COMPONENT, source_inputs(captured()))
        self.assertEqual(check(packaged)["resources"][0]["origin"], "application")
        self.assertIsNone(packaged.index["dependencyLockDigest"])
        changed = copy.deepcopy(packaged.index)
        changed["resources"][0].update(origin="dependency", owner="external:uncaptured:1.0")
        changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
        with self.assertRaises(resources.ResourceError) as raised:
            check(resources.PackagedResources(changed, packaged.objects))
        self.assertEqual((raised.exception.category, raised.exception.code),
                         ("denied", "resource-index-origin-binding-missing"))

    def test_application_origin_requires_bound_manifest_even_after_index_rehash(self):
        payload = b"dependency-only immutable bytes"
        owner = "external:captured:1.0"
        lock = {"artifacts": [{"id": owner, "files": [{"path": "data.txt", "digest": digest(payload), "size": len(payload)}]}]}
        files = {"latent.dependencies.lock.json": encode(lock), "dependencies/data.txt": payload}
        additional = {**row("data.txt", "dependencies/data.txt"), "digest": digest(payload), "owner": owner}
        packaged = resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])
        dependency = digest(files["latent.dependencies.lock.json"])
        value = resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                                 component_digest=digest(COMPONENT), dependency_lock_digest=dependency,
                                 dependency_lock=files["latent.dependencies.lock.json"])
        self.assertEqual(value["resources"][0]["origin"], "dependency")
        self.assertIsNone(packaged.index["manifestDigest"])
        changed = copy.deepcopy(packaged.index)
        changed["resources"][0]["origin"] = "application"
        changed["resources"][0].pop("owner")
        changed["identity"] = digest(encode({key: value for key, value in changed.items() if key != "identity"}))
        with self.assertRaises(resources.ResourceError) as raised:
            check(resources.PackagedResources(changed, packaged.objects), dependency=dependency, files=files)
        self.assertEqual((raised.exception.category, raised.exception.code),
                         ("denied", "resource-index-origin-binding-missing"))

    def test_mixed_origins_bind_both_inputs_and_preserve_shared_immutable_objects(self):
        files = captured()
        payload = files["assets/greeting.txt"]
        owner = "external:captured:1.0"
        lock = {"artifacts": [{"id": owner, "files": [{"path": "data.txt", "digest": digest(payload), "size": len(payload)}]}]}
        files.update({"latent.dependencies.lock.json": encode(lock), "dependencies/data.txt": payload})
        additional = {**row("dependency/data.txt", "dependencies/data.txt"), "digest": digest(payload), "owner": owner}
        before = copy.deepcopy(files)
        packaged = resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])
        value = resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                                 component_digest=digest(COMPONENT), manifest_digest=digest(files[resources.MANIFEST]),
                                 dependency_lock_digest=digest(files["latent.dependencies.lock.json"]),
                                 dependency_lock=files["latent.dependencies.lock.json"], manifest=files[resources.MANIFEST])
        self.assertEqual([item["origin"] for item in value["resources"]], ["application", "dependency"])
        self.assertEqual(value["manifestDigest"], digest(files[resources.MANIFEST]))
        self.assertEqual(value["dependencyLockDigest"], digest(files["latent.dependencies.lock.json"]))
        self.assertEqual(value["count"], 2)
        self.assertEqual(value["bytes"], 2 * len(payload))
        self.assertEqual(list(packaged.objects.values()), [payload])
        self.assertEqual(files, before)

    def test_six_language_package_inputs_include_index_and_original_bytes(self):
        for language in ("rust", "c", "java", "go", "typescript", "dotnet"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                files = {**captured(), "sdk-lock.json": encode({"language": language}),
                         "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n'}
                project = {"name": "resource-fixture", "tenant": "examples", "service": "examples/resource-fixture",
                           "world": "examples:resource-fixture/service@1.0.0", "version": "1.0.0", "limits": {}}
                (output / "source-inputs.json").write_bytes(source_inputs(files))
                package_inputs(output, project, {"imports": [], "exports": []}, files, COMPONENT)
                source = json.loads((output / "package-source.json").read_bytes())
                layers = {item["path"]: item for item in source["layers"]}
                self.assertEqual(layers[resources.INDEX]["role"], "asset")
                index = json.loads((output / resources.INDEX).read_bytes())
                objects = {item["object"]: (output / item["object"]).read_bytes() for item in index["resources"]}
                resources.verify((output / resources.INDEX).read_bytes(), objects,
                                 source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files), component_digest=digest(COMPONENT),
                                 manifest_digest=digest(files[resources.MANIFEST]), manifest=files[resources.MANIFEST])
                self.assertEqual(list(objects.values()), [files["assets/greeting.txt"]])

    def test_source_only_and_declared_empty_resource_behavior(self):
        self.assertIsNone(resources.capture({}, COMPONENT, source_inputs({})))
        files = {resources.MANIFEST: manifest([])}
        packaged = resources.capture(files, COMPONENT, source_inputs(files))
        self.assertEqual(check(packaged, files=files)["count"], 0)

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


class DependencyIndexProvenance(unittest.TestCase):
    def fixture(self):
        payload = b"owned transitive bytes"
        other = b"other captured bytes"
        lock = {"artifacts": [
            {"id": "external:owner-a:1.0", "files": [{"path": "data.bin", "digest": digest(payload), "size": len(payload)}]},
            {"id": "external:owner-b:1.0", "files": [{"path": "other.bin", "digest": digest(other), "size": len(other)}]}]}
        files = {resources.MANIFEST: manifest([row("app/data.bin", "assets/data.bin", "application/octet-stream")]),
                 "assets/data.bin": payload, "dependencies/data.bin": payload,
                 "latent.dependencies.lock.json": encode(lock)}
        additional = {**row("dependency/data.bin", "dependencies/data.bin", "application/octet-stream"),
                      "digest": digest(payload), "owner": "external:owner-a:1.0"}
        return files, resources.capture(files, COMPONENT, source_inputs(files), additional_resources=[additional])

    def verify(self, packaged, files, dependency_lock):
        return resources.verify(encode(packaged.index), packaged.objects, source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files),
                                component_digest=digest(COMPONENT), manifest_digest=digest(files[resources.MANIFEST]),
                                dependency_lock_digest=digest(files["latent.dependencies.lock.json"]),
                                dependency_lock=dependency_lock, manifest=files[resources.MANIFEST])

    def rehash(self, index):
        index["identity"] = digest(encode({key: value for key, value in index.items() if key != "identity"}))

    def test_rehashed_owner_must_belong_to_the_actual_bound_lock(self):
        files, packaged = self.fixture()
        changed = copy.deepcopy(packaged.index)
        changed["resources"][1]["owner"] = "external:not-captured:1.0"
        self.rehash(changed)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-dependency-owner-not-captured$"):
            self.verify(resources.PackagedResources(changed, packaged.objects), files, files["latent.dependencies.lock.json"])

    def test_captured_owner_cannot_claim_another_owners_or_unobserved_bytes(self):
        files, packaged = self.fixture()
        changed = copy.deepcopy(packaged.index)
        changed["resources"][1]["owner"] = "external:owner-b:1.0"
        self.rehash(changed)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-dependency-bytes-not-captured$"):
            self.verify(resources.PackagedResources(changed, packaged.objects), files, files["latent.dependencies.lock.json"])
        changed = copy.deepcopy(packaged.index)
        payload = b"outside every captured owner"
        identity = digest(payload)
        object_path = "resources/objects/" + identity[7:]
        changed["bytes"] += len(payload) - changed["resources"][1]["size"]
        changed["resources"][1].update(digest=identity, object=object_path, size=len(payload))
        self.rehash(changed)
        objects = {**packaged.objects, object_path: payload}
        with self.assertRaisesRegex(resources.ResourceError, "^resource-dependency-bytes-not-captured$"):
            self.verify(resources.PackagedResources(changed, objects), files, files["latent.dependencies.lock.json"])

    def test_digest_only_wrong_type_and_substituted_lock_cannot_supply_membership(self):
        from unittest.mock import patch
        files, packaged = self.fixture()
        for raw, code in ((None, "resource-index-dependency-lock-required"),
                          ("not lock bytes", "resource-dependency-lock-invalid"),
                          (bytearray(files["latent.dependencies.lock.json"]), "resource-dependency-lock-invalid"),
                          (encode({"artifacts": []}), "resource-index-dependency-lock-mismatch")):
            with self.subTest(code=code), patch.object(resources, "dependency_artifacts", side_effect=AssertionError("unbound lock was parsed")) as parsed, \
                    self.assertRaisesRegex(resources.ResourceError, "^" + code + "$"):
                self.verify(packaged, files, raw)
            parsed.assert_not_called()

    def test_bound_lock_document_rejects_malformed_duplicate_nonfinite_and_oversized_input(self):
        from unittest.mock import patch
        files, packaged = self.fixture()
        for raw in (b"{}", b"[]", b'{"artifacts":null}', b'{"artifacts":[],"artifacts":[]}',
                    b'{"artifacts":NaN}', b"{", b"\xff"):
            changed = copy.deepcopy(packaged.index)
            changed["dependencyLockDigest"] = digest(raw)
            self.rehash(changed)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.verify(resources.PackagedResources(changed, packaged.objects),
                            {**files, "latent.dependencies.lock.json": raw}, raw)
        raw = files["latent.dependencies.lock.json"]
        with patch.object(resources, "MAX_DEPENDENCY_LOCK", len(raw) - 1), \
                patch.object(resources, "dependency_artifacts", side_effect=AssertionError("oversized lock was parsed")) as parsed, \
                self.assertRaisesRegex(resources.ResourceError, "^resource-dependency-lock-limit$"):
            self.verify(packaged, files, raw)
        parsed.assert_not_called()

    def test_ambiguous_owner_or_changed_file_inventory_cannot_authenticate_resource(self):
        files, packaged = self.fixture()
        lock = json.loads(files["latent.dependencies.lock.json"])
        variants = []
        duplicate = copy.deepcopy(lock)
        duplicate["artifacts"].append(copy.deepcopy(duplicate["artifacts"][0]))
        variants.append((duplicate, "resource-dependency-owner-not-captured"))
        wrong_files = copy.deepcopy(lock)
        wrong_files["artifacts"][0]["files"] = "not an inventory"
        variants.append((wrong_files, "resource-dependency-owner-not-captured"))
        wrong_size = copy.deepcopy(lock)
        wrong_size["artifacts"][0]["files"][0]["size"] += 1
        variants.append((wrong_size, "resource-dependency-bytes-not-captured"))
        for lock, code in variants:
            raw = encode(lock)
            changed = copy.deepcopy(packaged.index)
            changed["dependencyLockDigest"] = digest(raw)
            self.rehash(changed)
            with self.subTest(code=code), self.assertRaisesRegex(resources.ResourceError, "^" + code + "$"):
                self.verify(resources.PackagedResources(changed, packaged.objects),
                            {**files, "latent.dependencies.lock.json": raw}, raw)

    def test_valid_mixed_origins_and_shared_owner_bytes_keep_index_identity_and_parse_lock_once(self):
        from unittest.mock import patch
        files, _ = self.fixture()
        payload = files["dependencies/data.bin"]
        lock = json.loads(files["latent.dependencies.lock.json"])
        lock["artifacts"][1]["files"] = copy.deepcopy(lock["artifacts"][0]["files"])
        files["latent.dependencies.lock.json"] = encode(lock)
        additional = [{**row("dependency/" + str(number) + ".bin", "dependencies/data.bin", "application/octet-stream"),
                       "digest": digest(payload), "owner": artifact["id"]} for number, artifact in enumerate(lock["artifacts"])]
        before = copy.deepcopy(files)
        packaged = resources.capture(files, COMPONENT, source_inputs(files), additional_resources=additional)
        with patch.object(resources, "dependency_artifacts", wraps=resources.dependency_artifacts) as parsed:
            value = self.verify(packaged, files, files["latent.dependencies.lock.json"])
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(value, packaged.index)
        self.assertEqual(value["count"], 3)
        self.assertEqual(value["bytes"], 3 * len(payload))
        self.assertEqual([row["origin"] for row in value["resources"]], ["application", "dependency", "dependency"])
        self.assertEqual(list(packaged.objects.values()), [payload])
        self.assertEqual(files, before)
