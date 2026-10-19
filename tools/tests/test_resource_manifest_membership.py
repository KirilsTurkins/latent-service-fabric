"""Actual declaration bytes constrain application resource index membership."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_resources as resources
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import inventory


def source_inputs(files):
    return inventory({path: data for path, data in files.items()
                      if path != "latent.dependencies.lock.json" and not path.startswith("dependencies/")})


class ApplicationManifestMembership(unittest.TestCase):
    def fixture(self):
        payload = b"\x00immutable\xff\n"
        rows = [{"path": "app/data.bin", "source": "assets/data.bin", "mediaType": "application/octet-stream"},
                {"path": "app/empty.txt", "source": "assets/empty", "mediaType": "text/plain"}]
        files = {resources.MANIFEST: encode({"schemaVersion": resources.PROFILE, "resources": rows}),
                 "assets/data.bin": payload, "assets/empty": b"", "dependencies/data.bin": payload,
                 "latent.dependencies.lock.json": encode({"artifacts": [{"id": "outside:immutable:1.0",
                     "files": [{"path": "data.bin", "digest": digest(payload), "size": len(payload)}]}]})}
        additional = [{"path": "dependency/data.bin", "source": "dependencies/data.bin",
                       "mediaType": "application/octet-stream", "owner": "outside:immutable:1.0",
                       "digest": digest(payload)}]
        packaged = resources.capture(files, b"component", source_inputs(files), additional_resources=additional)
        return files, packaged

    def verify(self, packaged, files, manifest):
        return resources.verify(encode(packaged.index), packaged.objects,
            source_digest=digest(source_inputs(files)), source_inventory=source_inputs(files), component_digest=digest(b"component"),
            manifest_digest=packaged.index["manifestDigest"], manifest=manifest,
            dependency_lock_digest=packaged.index["dependencyLockDigest"],
            dependency_lock=files.get("latent.dependencies.lock.json"))

    def rehash(self, index):
        index["identity"] = digest(encode({key: value for key, value in index.items() if key != "identity"}))

    def test_rehashed_application_names_and_media_require_actual_declaration_membership(self):
        files, packaged = self.fixture()
        for field, forged in (("path", "app/absent.bin"), ("mediaType", "text/plain")):
            changed = copy.deepcopy(packaged.index)
            changed["resources"][0][field] = forged
            self.rehash(changed)
            with self.subTest(field=field), self.assertRaisesRegex(resources.ResourceError,
                    "^resource-application-not-declared$") as raised:
                self.verify(resources.PackagedResources(changed, packaged.objects), files, files[resources.MANIFEST])
            self.assertEqual(raised.exception.category, "denied")

    def test_declared_rows_cannot_be_omitted_even_when_the_remaining_inventory_is_rehashed(self):
        files, packaged = self.fixture()
        for count in (1, 2):
            changed = copy.deepcopy(packaged.index)
            changed["resources"] = changed["resources"][count:]
            changed["count"] = len(changed["resources"])
            changed["bytes"] = sum(row["size"] for row in changed["resources"])
            objects = {row["object"]: packaged.objects[row["object"]] for row in changed["resources"]}
            self.rehash(changed)
            with self.subTest(count=count), self.assertRaisesRegex(resources.ResourceError,
                    "^resource-index-application-inventory-mismatch$"):
                self.verify(resources.PackagedResources(changed, objects), files, files[resources.MANIFEST])

    def test_relabelling_either_origin_cannot_change_the_declared_application_inventory(self):
        files, packaged = self.fixture()
        changed = copy.deepcopy(packaged.index)
        changed["resources"][-1].update(origin="application")
        changed["resources"][-1].pop("owner")
        self.rehash(changed)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-application-not-declared$"):
            self.verify(resources.PackagedResources(changed, packaged.objects), files, files[resources.MANIFEST])
        changed = copy.deepcopy(packaged.index)
        changed["resources"][0].update(origin="dependency", owner="outside:immutable:1.0")
        self.rehash(changed)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-index-application-inventory-mismatch$"):
            self.verify(resources.PackagedResources(changed, packaged.objects), files, files[resources.MANIFEST])

    def test_missing_wrong_type_and_substituted_manifest_are_rejected_before_decoding(self):
        files, packaged = self.fixture()
        for raw, code, category in ((None, "resource-index-manifest-required", "missing"),
                ("not bytes", "resource-manifest-bytes-required", "malformed"),
                (bytearray(files[resources.MANIFEST]), "resource-manifest-bytes-required", "malformed"),
                (encode({"schemaVersion": resources.PROFILE, "resources": []}),
                 "resource-index-manifest-mismatch", "denied")):
            with self.subTest(code=code), patch.object(resources, "declarations",
                    side_effect=AssertionError("unbound manifest was parsed")) as parsed, \
                    self.assertRaisesRegex(resources.ResourceError, "^" + code + "$") as raised:
                self.verify(packaged, files, raw)
            self.assertEqual(raised.exception.category, category)
            parsed.assert_not_called()

    def test_manifest_document_shape_aliases_and_limits_still_fail_closed(self):
        files, packaged = self.fixture()
        declaration = {"path": "app/data.bin", "source": "assets/data.bin", "mediaType": "application/octet-stream"}
        invalid = [b"{}", b"[]", b"{", b"\xff", b'{"resources":[],"resources":[]}',
                   b'{"schemaVersion":"lsf.packaged-resources.v1","resources":NaN}',
                   encode({"schemaVersion": resources.PROFILE, "resources": [declaration, declaration]}),
                   encode({"schemaVersion": resources.PROFILE, "resources": [declaration,
                       {**declaration, "path": "app/DATA.bin"}]}),
                   encode({"schemaVersion": resources.PROFILE, "resources": [{**declaration, "source": "../outside"}]}),
                   encode({"schemaVersion": resources.PROFILE, "resources": [{**declaration, "mediaType": "text/plain; charset=utf-8"}]})]
        for raw in invalid:
            changed = copy.deepcopy(packaged.index)
            changed["manifestDigest"] = digest(raw)
            self.rehash(changed)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.verify(resources.PackagedResources(changed, packaged.objects), files, raw)
        with patch.object(resources, "MAX_DOCUMENT", len(files[resources.MANIFEST]) - 1), \
                patch.object(resources, "declarations", side_effect=AssertionError("oversized manifest was parsed")) as parsed, \
                self.assertRaisesRegex(resources.ResourceError, "^resource-manifest-limit$"):
            # Keep the index decoder's separate bound unchanged for this check.
            resources.application_declarations(files[resources.MANIFEST], packaged.index["manifestDigest"])
        parsed.assert_not_called()

    def test_exact_mixed_selection_preserves_shared_binary_empty_bytes_and_parses_once(self):
        files, packaged = self.fixture()
        before = copy.deepcopy(files)
        with patch.object(resources, "declarations", wraps=resources.declarations) as parsed:
            actual = self.verify(packaged, files, files[resources.MANIFEST])
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(actual, packaged.index)
        self.assertEqual(actual["count"], 3)
        self.assertEqual(set(packaged.objects.values()), {b"\x00immutable\xff\n", b""})
        self.assertEqual(files, before)

    def test_declared_empty_requires_its_bound_bytes_and_dependency_only_needs_no_manifest(self):
        files, _ = self.fixture()
        files[resources.MANIFEST] = encode({"schemaVersion": resources.PROFILE, "resources": []})
        packaged = resources.capture(files, b"component", source_inputs(files))
        self.assertEqual(self.verify(packaged, files, files[resources.MANIFEST]), packaged.index)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-index-manifest-required$"):
            self.verify(packaged, files, None)
        self.assertIsNone(resources.capture({}, b"component", b"source"))
        additional = [{"path": "dependency/data.bin", "source": "dependencies/data.bin",
                       "mediaType": "application/octet-stream", "owner": "outside:immutable:1.0",
                       "digest": digest(files["dependencies/data.bin"])}]
        packaged = resources.capture(files, b"component", source_inputs(files), additional_resources=additional)
        self.assertEqual(self.verify(packaged, files, files[resources.MANIFEST]), packaged.index)
        files.pop(resources.MANIFEST)
        packaged = resources.capture(files, b"component", source_inputs(files), additional_resources=additional)
        with patch.object(resources, "application_declarations", side_effect=AssertionError("no declaration is bound")):
            self.assertEqual(self.verify(packaged, files, None), packaged.index)

    def test_verified_manifest_validates_source_paths_without_ambient_file_reads(self):
        files, packaged = self.fixture()
        with patch("pathlib.Path.open", side_effect=AssertionError("verification read a host path")):
            self.assertEqual(self.verify(packaged, files, files[resources.MANIFEST]), packaged.index)

    def test_all_six_package_assembly_paths_keep_exact_mixed_manifest_and_dependency_membership(self):
        from tools.rust_capsule_build import package_inputs
        from tools.dev_workflow.common import decode

        files, expected = self.fixture()
        additional = [{"path": "dependency/data.bin", "source": "dependencies/data.bin",
                       "mediaType": "application/octet-stream", "owner": "outside:immutable:1.0",
                       "digest": digest(files["dependencies/data.bin"])}]
        for language in ("rust", "c", "typescript", "go", "java", "dotnet"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                selected = {**files, "sdk-lock.json": encode({"language": language}),
                            "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n'}
                (output / "source-inputs.json").write_bytes(source_inputs(files))
                project = {"name": "mixed-resources", "tenant": "examples", "service": "examples/mixed-resources",
                           "world": "examples:mixed-resources/service@1.0.0", "version": "1.0.0", "limits": {}}
                package_inputs(output, project, {"imports": [], "exports": []}, selected, b"component",
                               additional_resources=additional)
                index = decode((output / resources.INDEX).read_bytes())
                objects = {row["object"]: (output / row["object"]).read_bytes() for row in index["resources"]}
                actual = self.verify(resources.PackagedResources(index, objects), files, files[resources.MANIFEST])
                self.assertEqual(actual, expected.index)
                self.assertEqual(objects, expected.objects)


if __name__ == "__main__":
    unittest.main()
